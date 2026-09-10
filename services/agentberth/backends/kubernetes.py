"""Kubernetes Job backend using the stable REST API and in-cluster identity."""

import base64
import json
import logging
import os
from pathlib import Path
import ssl
import time

import httpx

from agentberth.backends import BackendError, CleanupError


class KubernetesBackend:
    name = "kubernetes"

    def __init__(self):
        logging.getLogger("httpx").setLevel(logging.WARNING)
        self.namespace = os.environ["KUBERNETES_RUN_NAMESPACE"]
        self.owner = os.environ["KUBERNETES_OWNER"]
        self.token_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
        self.client = httpx.Client(
            base_url="https://kubernetes.default.svc",
            verify=ssl.create_default_context(cafile="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"),
            timeout=10,
            trust_env=False,
        )
        self.jobs = f"/apis/batch/v1/namespaces/{self.namespace}/jobs"
        self.core = f"/api/v1/namespaces/{self.namespace}"

    def close(self):
        self.client.close()

    def request(self, method, path, body=None, params=None, missing_ok=False):
        # Read each time: projected service-account tokens rotate.
        response = self.client.request(
            method,
            path,
            json=body,
            params=params,
            headers={"Authorization": "Bearer " + self.token_path.read_text().strip()},
        )
        if response.status_code == 404 and missing_ok:
            return None
        if not response.is_success:
            raise BackendError(
                f"Kubernetes {method} failed (HTTP {response.status_code}). Check worker RBAC and cluster events."
            )
        return response.json()

    def labels(self, run_id=None):
        labels = {"app.kubernetes.io/managed-by": "agentberth", "agentberth.owner": self.owner}
        if run_id:
            labels["agentberth.run"] = run_id
        return labels

    def job(self, spec):
        labels = self.labels(spec.id)
        name = "run-" + spec.id
        pod = {
            "restartPolicy": "Never",
            "automountServiceAccountToken": False,
            "serviceAccountName": os.getenv("KUBERNETES_RUN_SERVICE_ACCOUNT", "agentberth-run"),
            "enableServiceLinks": False,
            "terminationGracePeriodSeconds": 5,
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 10001,
                "runAsGroup": 10001,
                "fsGroup": 10001,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "containers": [
                {
                    "name": "runtime",
                    "image": os.environ["RUNTIME_IMAGE"],
                    "imagePullPolicy": os.getenv("RUNTIME_IMAGE_PULL_POLICY", "IfNotPresent"),
                    "securityContext": {
                        "readOnlyRootFilesystem": True,
                        "allowPrivilegeEscalation": False,
                        "capabilities": {"drop": ["ALL"]},
                    },
                    "env": [
                        {"name": "RUN_ID", "value": spec.id},
                        {"name": "API_URL", "value": os.environ["INTERNAL_API_URL"]},
                        {"name": "RUN_TOKEN", "valueFrom": {"secretKeyRef": {"name": name, "key": "token"}}},
                    ],
                    "resources": {
                        "requests": {"cpu": os.getenv("RUN_CPU_REQUEST", "100m"), "memory": "128Mi"},
                        "limits": {
                            "cpu": os.getenv("RUN_CPU_LIMIT", "1"),
                            "memory": "256Mi",
                            "ephemeral-storage": "32Mi",
                        },
                    },
                    "volumeMounts": [
                        {"name": "workspace", "mountPath": "/workspace"},
                        {"name": "tmp", "mountPath": "/tmp"},
                    ],
                }
            ],
            "volumes": [
                {"name": "workspace", "emptyDir": {"medium": "Memory", "sizeLimit": "64Mi"}},
                {"name": "tmp", "emptyDir": {"medium": "Memory", "sizeLimit": "16Mi"}},
            ],
        }
        for env, key in [
            ("KUBERNETES_NODE_SELECTOR", "nodeSelector"),
            ("KUBERNETES_TOLERATIONS", "tolerations"),
            ("KUBERNETES_IMAGE_PULL_SECRETS", "imagePullSecrets"),
        ]:
            if os.getenv(env):
                pod[key] = json.loads(os.environ[env])
        if os.getenv("KUBERNETES_RUNTIME_CLASS"):
            pod["runtimeClassName"] = os.environ["KUBERNETES_RUNTIME_CLASS"]
        return {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": name, "labels": labels},
            "spec": {
                "backoffLimit": 0,
                "activeDeadlineSeconds": spec.timeout_seconds,
                "ttlSecondsAfterFinished": 600,
                "template": {"metadata": {"labels": labels}, "spec": pod},
            },
        }

    def submit(self, spec):
        body = self.job(spec)
        name = body["metadata"]["name"]
        try:
            job = self.request("POST", self.jobs, body)
            uid = job["metadata"]["uid"]
            self.request(
                "POST",
                self.core + "/secrets",
                {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "type": "Opaque",
                    "metadata": {
                        "name": name,
                        "labels": self.labels(spec.id),
                        "ownerReferences": [
                            {
                                "apiVersion": "batch/v1",
                                "kind": "Job",
                                "name": name,
                                "uid": uid,
                                "controller": True,
                            }
                        ],
                    },
                    "data": {"token": base64.b64encode(spec.token.encode()).decode()},
                },
            )
            return name + ":" + uid
        except Exception:
            # A create timeout may have committed. Never blindly retry execution.
            job = self.request("GET", self.jobs + "/" + name, missing_ok=True)
            if job and job["metadata"].get("labels", {}).get("agentberth.owner") == self.owner:
                try:
                    self.cleanup(name + ":" + job["metadata"]["uid"])
                except Exception:
                    raise CleanupError(
                        "Job submission cleanup is uncertain; restarting for reconciliation."
                    ) from None
            raise

    def owned_job(self, handle):
        name, uid = handle.split(":", 1)
        job = self.request("GET", self.jobs + "/" + name, missing_ok=True)
        if job and (
            job["metadata"]["uid"] != uid
            or job["metadata"].get("labels", {}).get("agentberth.owner") != self.owner
        ):
            raise BackendError("Job identity changed; refusing to touch an unrelated workload.")
        return job

    def status(self, handle):
        job = self.owned_job(handle)
        if not job:
            return False, 1
        status = job.get("status", {})
        if status.get("succeeded", 0):
            return False, 0
        for condition in status.get("conditions", []):
            if condition.get("status") == "True" and condition["type"] in ("Failed", "FailureTarget"):
                return False, 124 if condition.get("reason") == "DeadlineExceeded" else 1
        pods = self.request(
            "GET", self.core + "/pods", params={"labelSelector": "job-name=" + handle.split(":")[0]}
        )
        for pod in pods["items"]:
            for state in pod.get("status", {}).get("containerStatuses", []):
                terminated = state.get("state", {}).get("terminated")
                if terminated and terminated.get("exitCode") != 0:
                    return False, terminated["exitCode"]
                reason = state.get("state", {}).get("waiting", {}).get("reason")
                if reason in ("InvalidImageName", "ImagePullBackOff"):
                    raise BackendError(
                        f"Runtime Pod cannot start ({reason}). Check the runtime image and registry credentials."
                    )
        return True, None  # Includes Pending; the run deadline also bounds scheduling/image pulls.

    def cancel(self, handle):
        self.cleanup(handle)

    def cleanup(self, handle):
        name, uid = handle.split(":", 1)
        if self.owned_job(handle):
            self.request(
                "DELETE",
                self.jobs + "/" + name,
                {"propagationPolicy": "Foreground", "gracePeriodSeconds": 5, "preconditions": {"uid": uid}},
                missing_ok=True,
            )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            job = self.owned_job(handle)
            pods = self.request(
                "GET",
                self.core + "/pods",
                params={"labelSelector": f"job-name={name},agentberth.owner={self.owner}"},
            )
            if not job and not pods["items"]:
                # Owner GC normally removes this; explicitly remove any delayed token Secret.
                secret = self.request("GET", self.core + "/secrets/" + name, missing_ok=True)
                if secret and secret["metadata"].get("labels", {}).get("agentberth.owner") == self.owner:
                    self.request(
                        "DELETE",
                        self.core + "/secrets/" + name,
                        {"preconditions": {"uid": secret["metadata"]["uid"]}},
                        missing_ok=True,
                    )
                return
            time.sleep(0.5)
        raise CleanupError(
            "Job cleanup could not be confirmed. Worker will restart and reconcile; inspect cluster health."
        )

    def cleanup_orphans(self):
        selector = f"agentberth.owner={self.owner},app.kubernetes.io/managed-by=agentberth"
        jobs = self.request("GET", self.jobs, params={"labelSelector": selector})
        for job in jobs["items"]:
            self.cleanup(job["metadata"]["name"] + ":" + job["metadata"]["uid"])
        secrets = self.request("GET", self.core + "/secrets", params={"labelSelector": selector})
        for secret in secrets["items"]:
            self.request(
                "DELETE",
                self.core + "/secrets/" + secret["metadata"]["name"],
                {"preconditions": {"uid": secret["metadata"]["uid"]}},
                missing_ok=True,
            )
