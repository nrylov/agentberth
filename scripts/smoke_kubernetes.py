"""Kubernetes-only isolation and recovery checks against a dedicated test installation."""

import argparse
import json
import os
import subprocess
import time
import urllib.request
import uuid

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--kubeconfig", required=True)
parser.add_argument("--context", required=True)
parser.add_argument("--namespace", default="agentberth")
parser.add_argument("--sandbox-namespace", default="agentberth-sandbox")
parser.add_argument("--release", default="agentberth")
parser.add_argument("--base-url", default="http://127.0.0.1:8081")
args = parser.parse_args()
kube = ["kubectl", "--kubeconfig", args.kubeconfig, "--context", args.context]
name = (args.release + "-agentberth")[:50].rstrip("-")


def kubectl(*arguments, body=None):
    return subprocess.check_output(
        kube + list(arguments),
        input=json.dumps(body).encode() if body is not None else None,
        stderr=subprocess.DEVNULL,
    )


def request(path, body=None):
    req = urllib.request.Request(
        args.base_url + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": "Bearer " + os.environ["AGENTBERTH_ADMIN_KEY"],
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def wait_run(id, expected):
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        run = request("/v1/runs/" + id)
        if run["status"] in {"completed", "failed", "timed_out", "cancelled"}:
            assert run["status"] == expected, run["error"]
            assert run["files"][0]["download_url"] is None
            return
        time.sleep(0.5)
    raise AssertionError("Run did not terminate")


def suspended_run(slug):
    id = request(
        "/v1/deployments/" + slug + "/runs",
        {
            "input": "Kubernetes lifecycle test.",
            "files": [{"name": "temporary.txt", "content_base64": "dGVzdA=="}],
        },
    )["id"]
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        jobs = json.loads(
            kubectl("-n", args.sandbox_namespace, "get", "jobs", "-l", "agentberth.run=" + id, "-o", "json")
        )["items"]
        if jobs:
            job = jobs[0]
            pod = job["spec"]["template"]["spec"]
            assert pod["automountServiceAccountToken"] is False
            assert pod["restartPolicy"] == "Never" and job["spec"]["backoffLimit"] == 0
            assert pod["containers"][0]["securityContext"]["readOnlyRootFilesystem"]
            assert all("emptyDir" in v for v in pod["volumes"])
            kubectl(
                "-n",
                args.sandbox_namespace,
                "patch",
                "job",
                job["metadata"]["name"],
                "--type=merge",
                "-p",
                '{"spec":{"suspend":true}}',
            )
            return id
        time.sleep(0.1)
    raise AssertionError("Job not found")


settings = request("/v1/settings")
assert settings["backend"] == "kubernetes" and settings["worker_online"]
worker = json.loads(kubectl("-n", args.namespace, "get", "deployment", name + "-worker", "-o", "json"))
env = {e["name"]: e.get("value") for e in worker["spec"]["template"]["spec"]["containers"][0]["env"]}
api_ip = json.loads(kubectl("-n", "default", "get", "service", "kubernetes", "-o", "json"))["spec"][
    "clusterIP"
]
probe_name = "network-check-" + uuid.uuid4().hex[:8]
code = """import os,socket,urllib.request
assert not os.path.exists('/var/run/secrets/kubernetes.io/serviceaccount/token')
with urllib.request.urlopen(os.environ['API_URL']+'/healthz',timeout=5) as r: assert r.status==200
for host,port in [(os.environ['DB_HOST'],5432),(os.environ['CLUSTER_API'],443),('169.254.169.254',80),('1.1.1.1',443)]:
    try:
        connection=socket.create_connection((host,port),timeout=3)
    except OSError: continue
    connection.close()
    raise RuntimeError('Sandbox egress was not blocked for '+host)
print('PASS: API reachable; database, cluster API, metadata, internet blocked; no service-account token')
"""
probe = {
    "apiVersion": "v1",
    "kind": "Pod",
    "metadata": {"name": probe_name, "namespace": args.sandbox_namespace},
    "spec": {
        "restartPolicy": "Never",
        "automountServiceAccountToken": False,
        "serviceAccountName": "agentberth-run",
        "securityContext": {
            "runAsNonRoot": True,
            "runAsUser": 10001,
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "imagePullSecrets": json.loads(env.get("KUBERNETES_IMAGE_PULL_SECRETS") or "[]"),
        "containers": [
            {
                "name": "probe",
                "image": env["RUNTIME_IMAGE"],
                "command": ["python", "-c", code],
                "securityContext": {
                    "readOnlyRootFilesystem": True,
                    "allowPrivilegeEscalation": False,
                    "capabilities": {"drop": ["ALL"]},
                },
                "resources": {
                    "requests": {"cpu": "20m", "memory": "32Mi"},
                    "limits": {"cpu": "100m", "memory": "64Mi"},
                },
                "env": [
                    {"name": "API_URL", "value": env["INTERNAL_API_URL"]},
                    {"name": "DB_HOST", "value": name + "-postgres." + args.namespace + ".svc"},
                    {"name": "CLUSTER_API", "value": api_ip},
                ],
            }
        ],
    },
}
try:
    kubectl("create", "-f", "-", body=probe)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        phase = json.loads(kubectl("-n", args.sandbox_namespace, "get", "pod", probe_name, "-o", "json"))[
            "status"
        ]["phase"]
        if phase in {"Succeeded", "Failed"}:
            logs = kubectl("-n", args.sandbox_namespace, "logs", probe_name).decode()
            assert phase == "Succeeded", logs
            print(logs.strip())
            break
        time.sleep(1)
    else:
        raise AssertionError("Network probe did not finish")
finally:
    kubectl("-n", args.sandbox_namespace, "delete", "pod", probe_name, "--ignore-not-found", "--wait=false")

slug = "kube-check-" + uuid.uuid4().hex[:8]
request(
    "/v1/agents",
    {
        "slug": slug,
        "name": "Kubernetes integration check",
        "example_task": "Run the fixed demonstration in a Kubernetes sandbox and save report.md with the total and average of 12, 18, and 24.",
        "instructions": "Run demo.",
        "timeout_seconds": 30,
    },
)
id = suspended_run(slug)
request("/v1/runs/" + id + "/cancel", {})
wait_run(id, "cancelled")
id = suspended_run(slug)
wait_run(id, "timed_out")
id = suspended_run(slug)
kubectl("-n", args.namespace, "delete", "pod", "-l", "app=" + name + "-worker", "--grace-period=0", "--force")
wait_run(id, "failed")
assert not json.loads(
    kubectl("-n", args.sandbox_namespace, "get", "jobs", "-l", "agentberth.owner=" + name, "-o", "json")
)["items"]
assert not json.loads(
    kubectl("-n", args.sandbox_namespace, "get", "secrets", "-l", "agentberth.owner=" + name, "-o", "json")
)["items"]
print(
    "PASS: Job security, cancellation, deadline, worker restart/orphan cleanup, input expiry, token Secret cleanup"
)
