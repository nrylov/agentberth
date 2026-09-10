"""Fault-injection checks. Development stacks only: pauses test containers and restarts the worker.

Requires Python 3.10+, Docker CLI, and the running Compose stack. Uses no paid model calls.
"""

import argparse
import json
import os
import subprocess
import time
import urllib.request
import uuid

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--base-url", default="http://127.0.0.1:8080")
args = parser.parse_args()
key = os.getenv("AGENTBERTH_ADMIN_KEY", "agentberth-local")


def request(path, body=None, token=None):
    req = urllib.request.Request(
        args.base_url + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + (token or key), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def docker(*arguments):
    return subprocess.check_output(["docker", *arguments], text=True, stderr=subprocess.DEVNULL).strip()


def paused_run(slug):
    run_id = request(
        f"/v1/deployments/{slug}/runs",
        {
            "input": "Development fault injection.",
            "files": [{"name": "ephemeral.txt", "content_base64": "dGVzdA=="}],
        },
    )["id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        ids = docker("ps", "-q", "--filter", f"label=agentberth.run={run_id}")
        if ids:
            handle = ids.splitlines()[0]
            docker("pause", handle)
            req = urllib.request.Request(
                args.base_url + f"/v1/runs/{run_id}/files/0", headers={"Authorization": "Bearer " + key}
            )
            with urllib.request.urlopen(req) as response:
                assert response.read() == b"test"
            return run_id, handle
        time.sleep(0.05)
    raise AssertionError("Sandbox not found in time")


def terminal(run_id):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        run = request("/v1/runs/" + run_id)
        if run["status"] in {"completed", "failed", "cancelled", "timed_out"}:
            assert run["files"][0]["download_url"] is None
            try:
                request(f"/v1/runs/{run_id}/files/0")
            except urllib.error.HTTPError as exc:
                assert exc.code == 410
            else:
                raise AssertionError("Terminal inputs remained downloadable")
            return run
        time.sleep(0.25)
    raise AssertionError("Run did not finish")


slug = "recovery-" + uuid.uuid4().hex[:8]
request(
    "/v1/agents", {"slug": slug, "name": "Recovery test", "instructions": "Run demo.", "timeout_seconds": 10}
)
run_id, handle = paused_run(slug)
try:
    # Inspect only the explicit sandbox boundary fields; never print raw environment.
    info = json.loads(docker("inspect", handle))[0]
    host = info["HostConfig"]
    assert info["Config"]["User"] == "10001:10001"
    assert host["ReadonlyRootfs"] and host["Memory"] == 256 * 1024 * 1024
    assert host["NanoCpus"] == 1_000_000_000 and host["PidsLimit"] == 64
    assert not host.get("Binds")
    assert host["CapDrop"] == ["ALL"]
    assert set(info["NetworkSettings"]["Networks"]) == {"agentberth_sandbox"}
    env = dict(item.split("=", 1) for item in info["Config"]["Env"])
    assert "LLM_API_KEY" not in env and "DATABASE_URL" not in env and "ADMIN_KEY" not in env
    token = env["RUN_TOKEN"]
    # A run token cannot act as the administrator or read another run.
    for path in ["/v1/agents", "/internal/runs/not-this-run/context"]:
        try:
            request(path, token=token)
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        else:
            raise AssertionError("Run token crossed its authorization boundary")
    assert terminal(run_id)["status"] == "timed_out"
    assert not docker("ps", "-aq", "--filter", f"label=agentberth.run={run_id}")
    try:
        request(f"/internal/runs/{run_id}/context", token=token)
    except urllib.error.HTTPError as exc:
        assert exc.code == 401
    else:
        raise AssertionError("Terminal run token remained valid")
finally:
    subprocess.run(["docker", "rm", "-f", handle], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print("PASS: sandbox limits, credential separation, scoped token, timeout, teardown, token revocation")

run_id, handle = paused_run(slug)
try:
    request(f"/v1/runs/{run_id}/cancel", {})
    assert terminal(run_id)["status"] == "cancelled"
    assert not docker("ps", "-aq", "--filter", f"label=agentberth.run={run_id}")
finally:
    subprocess.run(["docker", "rm", "-f", handle], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print("PASS: cancellation destroys a running sandbox")

run_id, handle = paused_run(slug)
try:
    # Abrupt worker loss leaves an orphan; startup reconciliation must remove it.
    docker("compose", "kill", "-s", "SIGKILL", "worker")
    docker("compose", "up", "-d", "--no-deps", "worker")
    assert terminal(run_id)["status"] == "failed"
    assert not docker("ps", "-aq", "--filter", f"label=agentberth.run={run_id}")
finally:
    subprocess.run(["docker", "rm", "-f", handle], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print("PASS: worker restart removes orphan and fails interrupted run without replay")

# With concurrent admission, cancelling one sandbox must not stop its peers.
limit = request("/v1/queue")["max_concurrent_runs"]
if limit >= 2:
    batch = []
    try:
        for _ in range(min(limit, 3)):
            batch.append(paused_run(slug))
        first, _ = batch[0]
        request(f"/v1/runs/{first}/cancel", {})
        assert terminal(first)["status"] == "cancelled"
        for peer, _handle in batch[1:]:
            assert request("/v1/runs/" + peer)["status"] == "running"
            assert docker("ps", "-q", "--filter", f"label=agentberth.run={peer}")
        docker("compose", "kill", "-s", "SIGKILL", "worker")
        docker("compose", "up", "-d", "--no-deps", "worker")
        for peer, _handle in batch[1:]:
            assert terminal(peer)["status"] == "failed"
            assert not docker("ps", "-aq", "--filter", f"label=agentberth.run={peer}")
    finally:
        for _, handle in batch:
            subprocess.run(
                ["docker", "rm", "-f", handle], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
    print(
        "PASS: cancellation preserves concurrent peers; restart cleans all remaining sandboxes and expires uploads"
    )
