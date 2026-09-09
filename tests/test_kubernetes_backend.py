import httpx
import pytest

from agentberth.backends import RunSpec, BackendError, backend_name
from agentberth.backends.kubernetes import KubernetesBackend


def backend(monkeypatch):
    monkeypatch.setenv("RUNTIME_IMAGE", "registry/runtime:v1")
    monkeypatch.setenv("INTERNAL_API_URL", "http://api.control.svc:8080")
    value = KubernetesBackend.__new__(KubernetesBackend)
    value.namespace, value.owner = "sandbox", "test"
    value.jobs = "/apis/batch/v1/namespaces/sandbox/jobs"
    value.core = "/api/v1/namespaces/sandbox"
    return value


def test_job_keeps_credentials_out_of_spec_and_restricts_runtime(monkeypatch):
    b = backend(monkeypatch)
    job = b.job(RunSpec("example", "sensitive-token", 37))
    assert "sensitive-token" not in str(job)
    assert job["spec"]["activeDeadlineSeconds"] == 37
    assert job["spec"]["backoffLimit"] == 0
    pod = job["spec"]["template"]["spec"]
    assert pod["restartPolicy"] == "Never"
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsNonRoot"]
    assert pod["containers"][0]["securityContext"]["readOnlyRootFilesystem"]
    assert pod["containers"][0]["resources"]["limits"]["memory"] == "256Mi"
    assert all(v["emptyDir"]["medium"] == "Memory" for v in pod["volumes"])
    assert not any("hostPath" in v for v in pod["volumes"])


def test_runtime_class_and_node_options(monkeypatch):
    b = backend(monkeypatch)
    monkeypatch.setenv("KUBERNETES_RUNTIME_CLASS", "kata")
    monkeypatch.setenv("KUBERNETES_NODE_SELECTOR", '{"pool":"sandbox"}')
    pod = b.job(RunSpec("example", "token"))["spec"]["template"]["spec"]
    assert pod["runtimeClassName"] == "kata"
    assert pod["nodeSelector"] == {"pool": "sandbox"}


def test_job_status_and_uid_guard(monkeypatch):
    b = backend(monkeypatch)
    job = {"metadata": {"uid": "uid", "labels": {"agentberth.owner": "test"}}, "status": {"succeeded": 1}}
    b.request = lambda *a, **kw: job
    assert b.status("example:uid") == (False, 0)
    job["status"] = {"conditions": [{"type": "Failed", "status": "True", "reason": "DeadlineExceeded"}]}
    assert b.status("example:uid") == (False, 124)
    with pytest.raises(BackendError, match="identity changed"):
        b.cleanup("example:unrelated-uid")


def test_request_refreshes_rotated_token_and_hides_error_body(monkeypatch, tmp_path):
    b = backend(monkeypatch)
    b.token_path = tmp_path / "token"
    b.token_path.write_text("first")
    seen = []

    def handler(request):
        seen.append(request.headers["Authorization"])
        return httpx.Response(403, json={"secret": "do-not-expose"})

    b.client = httpx.Client(base_url="https://cluster", transport=httpx.MockTransport(handler))
    for token in ["first", "second"]:
        b.token_path.write_text(token)
        with pytest.raises(BackendError) as exc:
            b.request("GET", "/api")
        assert "do-not-expose" not in str(exc.value)
    assert seen == ["Bearer first", "Bearer second"]


def test_backend_selection_is_explicit(monkeypatch):
    monkeypatch.delenv("EXECUTION_BACKEND", raising=False)
    assert backend_name() == "docker"
    monkeypatch.setenv("EXECUTION_BACKEND", "unknown")
    with pytest.raises(ValueError):
        backend_name()


@pytest.mark.parametrize("failure", ["job-response-lost", "secret-create"])
def test_submission_failure_cleans_up_without_replaying(monkeypatch, failure):
    b = backend(monkeypatch)
    calls, cleaned = [], []
    job = {"metadata": {"uid": "uid", "labels": {"agentberth.owner": "test"}}}

    def request(method, path, *a, **kw):
        calls.append((method, path))
        if method == "POST" and path == b.jobs:
            if failure == "job-response-lost":
                raise httpx.ReadTimeout("Response lost after possible server commit")
            return job
        if method == "POST":
            raise BackendError("Secret creation failed")
        return job

    b.request = request
    b.cleanup = cleaned.append
    with pytest.raises((httpx.ReadTimeout, BackendError)):
        b.submit(RunSpec("example", "secret"))
    assert cleaned == ["run-example:uid"]
    assert calls.count(("POST", b.jobs)) == 1
