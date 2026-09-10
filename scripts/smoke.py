"""End-to-end test against a running Compose stack; standard library only.

python3 scripts/smoke.py          # demo, auth, idempotency, events, artifacts, cancellation
python3 scripts/smoke.py --live   # additionally spends a small amount on OpenRouter
"""

import argparse
import json
import os
import time
import urllib.error
import urllib.request
import uuid

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--base-url", default="http://127.0.0.1:8080")
parser.add_argument("--live", action="store_true")
args = parser.parse_args()
key = os.getenv("AGENTBERTH_ADMIN_KEY", "agentberth-local")


def request(path, body=None, headers=None, raw=False, method=None):
    req = urllib.request.Request(
        args.base_url + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        data = response.read().decode()
        return data if raw else json.loads(data)


def wait(run_id):
    end = time.monotonic() + 180
    while time.monotonic() < end:
        run = request("/v1/runs/" + run_id)
        if run["status"] in {"completed", "failed", "cancelled", "timed_out"}:
            return run
        time.sleep(0.5)
    raise AssertionError("Run did not reach a terminal state")


def expect_status(code, fn):
    try:
        fn()
    except urllib.error.HTTPError as exc:
        assert exc.code == code, (exc.code, code)
    else:
        raise AssertionError(f"Expected HTTP {code}")


expect_status(401, lambda: request("/v1/agents", headers={"Authorization": "Bearer incorrect"}))
expect_status(
    401, lambda: request("/internal/runs/not-a-run/context", headers={"Authorization": "Bearer incorrect"})
)
expect_status(404, lambda: request("/v1/runs/not-a-run"))
slug = "smoke-" + uuid.uuid4().hex[:8]
config = {
    "slug": slug,
    "name": "Smoke test",
    "example_task": "Run the fixed demonstration and generate report.md to verify task execution and artifact downloads.",
    "instructions": "Use tools to solve the task.",
    "provider": "demo",
    "tools": ["python", "write_file", "read_file"],
}
request("/v1/agents", config)
path = f"/v1/deployments/{slug}/runs"
idempotency = str(uuid.uuid4())
accepted = request(path, {"input": "Create a demo report."}, {"Idempotency-Key": idempotency})
assert (
    request(path, {"input": "Create a demo report."}, {"Idempotency-Key": idempotency})["id"]
    == accepted["id"]
)
expect_status(409, lambda: request(path, {"input": "Different input"}, {"Idempotency-Key": idempotency}))
# Publishing a new version must not change an already accepted run.
updated = request(
    "/v1/agents/" + slug,
    {**{k: v for k, v in config.items() if k != "slug"}, "instructions": "Updated after acceptance."},
    method="PUT",
)
assert updated["version"] == 2
run = wait(accepted["id"])
assert run["status"] == "completed", (run["status"], run.get("error"))
assert run["version"] == 1
assert "54" in run["output"] and run["model_calls"] == 0
assert run["artifacts"] and run["artifacts"][0]["name"] == "report.md"
artifact = request(f"/v1/runs/{run['id']}/artifacts/{run['artifacts'][0]['id']}", raw=True)
assert "deterministic demo" in artifact
stream = request(f"/v1/runs/{run['id']}/events", raw=True)
events = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith("data: ")]
assert events[-1]["kind"] == "run.completed"
assert any(e["kind"] == "tool.completed" for e in events)
replay = request(f"/v1/runs/{run['id']}/events", headers={"Last-Event-ID": str(events[-2]["id"])}, raw=True)
assert replay.count("data: ") == 1
cancelled = request(path, {"input": "Cancel this run."})
request(f"/v1/runs/{cancelled['id']}/cancel", {})
assert wait(cancelled["id"])["status"] == "cancelled"
print(
    "PASS: auth, isolated demo execution, version snapshot, idempotency, persisted events/replay, artifact download, cancellation"
)

if args.live:
    config.update({"slug": slug + "-live", "name": "OpenRouter smoke test", "provider": "openrouter"})
    request("/v1/agents", config)
    live = request(
        f"/v1/deployments/{config['slug']}/runs",
        {
            "input": "Use the python tool to compute 7 * 8, then use write_file to save the answer to answer.txt. Finish with a one-sentence answer."
        },
    )
    run = wait(live["id"])
    assert run["status"] == "completed", (run["status"], run.get("error"))
    assert run["model_calls"] >= 2 and run["artifacts"]
    assert any(
        "56" in request(f"/v1/runs/{run['id']}/artifacts/{a['id']}", raw=True) for a in run["artifacts"]
    )
    print(
        f"PASS: OpenRouter tool loop, saved artifact, {run['model_calls']} model calls; reported cost ${run['cost']}"
    )
