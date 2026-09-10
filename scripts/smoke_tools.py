"""Tool registry integration checks. --live optionally tests per-run tool use with OpenRouter."""

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--base-url", default="http://127.0.0.1:8080")
parser.add_argument("--live", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]


def request(path, body=None, method=None, headers=None):
    req = urllib.request.Request(
        args.base_url + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Authorization": "Bearer " + os.getenv("AGENTBERTH_ADMIN_KEY", "agentberth-local"),
            "Content-Type": "application/json",
            **(headers or {}),
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def expect(code, fn):
    try:
        fn()
    except urllib.error.HTTPError as exc:
        assert exc.code == code, (exc.code, code)
    else:
        raise AssertionError(f"Expected HTTP {code}")


def wait(id):
    end = time.monotonic() + 180
    while time.monotonic() < end:
        run = request("/v1/runs/" + id)
        if run["status"] in {"completed", "failed", "timed_out", "cancelled"}:
            return run
        time.sleep(0.3)
    raise AssertionError("Run did not finish")


def test_version(id, version):
    accepted = request(f"/v1/tools/{id}/{version}/test", method="POST")
    return wait(accepted["id"])


suffix = uuid.uuid4().hex[:8]
folder = root / "tools/examples/summarize-csv"
p = {
    "manifest": json.loads((folder / "tool.json").read_text()),
    "handler": (folder / "handler.py").read_text(),
    "tests": json.loads((folder / "tests.json").read_text()),
}
p["manifest"]["id"] = id = "csv-check-" + suffix
p["manifest"]["name"] = name = "csv_check_" + suffix
row = request("/v1/tools/import", p)
assert row["status"] == "draft"
expect(409, lambda: request(f"/v1/tools/{id}/1.0.0/publish", method="POST"))
agent = "tool-check-" + suffix
request(
    "/v1/agents",
    {
        "slug": agent,
        "name": "Tool integration check",
        "example_task": "Run the fixed demonstration to verify built-in tool execution and save report.md. Select OpenRouter to process arbitrary data.",
        "instructions": "Use the provided tools.",
    },
)
path = f"/v1/deployments/{agent}/runs"
body = {
    "input": "Demo with a run-specific CSV tool.",
    "additional_tools": [{"id": id, "version": "1.0.0"}],
    "disabled_tools": ["python"],
}
expect(422, lambda: request(path, body))
assert test_version(id, "1.0.0")["status"] == "completed"
request(f"/v1/tools/{id}/1.0.0/publish", method="POST")
assert request(f"/v1/tools/{id}/1.0.0/export") == p
assert request("/v1/tools/import", p)["sha256"] == row["sha256"]
changed = deepcopy(p)
changed["handler"] += "\n# changed"
expect(409, lambda: request("/v1/tools/import", changed))
accepted = request(path, body, headers={"Idempotency-Key": "tool-snapshot"})
# Publish a new version while v1 is accepted; v1 must stay pinned.
p2 = deepcopy(p)
p2["manifest"]["version"] = "1.0.1"
p2["manifest"]["description"] += " New description."
request("/v1/tools/import", p2)
assert test_version(id, "1.0.1")["status"] == "completed"
request(f"/v1/tools/{id}/1.0.1/publish", method="POST")
run = wait(accepted["id"])
assert run["status"] == "completed", run["error"]
assert next(t for t in run["resolved_tools"] if t["id"] == id)["sha256"] == row["sha256"]
assert "python" not in [t["id"] for t in run["resolved_tools"]]
assert request(path, body, headers={"Idempotency-Key": "tool-snapshot"})["id"] == accepted["id"]
expect(
    409, lambda: request(path, {**body, "disabled_tools": []}, headers={"Idempotency-Key": "tool-snapshot"})
)
expect(422, lambda: request(path, {**body, "additional_tools": body["additional_tools"] * 2}))
expect(422, lambda: request(path, {**body, "additional_tools": [{"id": "not-found", "version": "1.0.0"}]}))
assert any(
    t["id"] == "python"
    for t in next(a for a in request("/v1/agents") if a["slug"] == agent)["config"]["tools"]
)
failed = deepcopy(p)
failed["manifest"]["version"] = "2.0.0"
failed["handler"] = 'def run(arguments, context):\n    return {"row_count": 999, "columns": []}\n'
request("/v1/tools/import", failed)
assert test_version(id, "2.0.0")["status"] == "failed"
expect(409, lambda: request(f"/v1/tools/{id}/2.0.0/publish", method="POST"))
print(
    "PASS: import/export, draft isolation, sandbox fixtures, publication, version conflicts, snapshots, per-run overrides, idempotency, failed-test rejection"
)
if args.live:
    request(
        "/v1/agents/" + agent,
        {
            "name": "Tool integration check",
            "example_task": "Use Python to create sample.csv with columns name,score and rows Ada,10 and Lin,20. Read it back, calculate the average score, and write the row count, column names, and average to report.md.",
            "instructions": "Use the requested tools exactly. Return a concise answer.",
            "provider": "openrouter",
        },
        method="PUT",
    )
    live = request(
        path,
        {
            **body,
            "input": f"Use write_file to write sample.csv with this exact content: name,score\\nAda,10\\nLin,20\\n (interpret \\n as newlines). Then call {name} on sample.csv. Report its row count and column names.",
        },
    )
    result = wait(live["id"])
    assert result["status"] == "completed", result["error"]
    req = urllib.request.Request(
        args.base_url + f"/v1/runs/{live['id']}/events",
        headers={"Authorization": "Bearer " + os.getenv("AGENTBERTH_ADMIN_KEY", "agentberth-local")},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        events = [
            json.loads(line[6:])
            for line in response.read().decode().splitlines()
            if line.startswith("data: ")
        ]
    assert any(
        e["kind"] == "tool.completed"
        and e["data"]["name"] == name
        and e["data"]["result"].get("row_count") == 2
        for e in events
    )
    print(
        f"PASS: OpenRouter used the per-run custom tool; {result['model_calls']} model calls, reported cost ${result['cost']}"
    )

# Deletion keeps accepted runs intact, rejects agent references, and reserves version IDs.
expect(409, lambda: request("/v1/tools/python/1.0.0", method="DELETE"))
agent_config = next(a for a in request("/v1/agents") if a["slug"] == agent)["config"]
original_config = deepcopy(agent_config)
agent_config["tools"].append({"id": id, "version": "1.0.1"})
request("/v1/agents/" + agent, agent_config, method="PUT")
expect(409, lambda: request(f"/v1/tools/{id}/1.0.1", method="DELETE"))
request("/v1/agents/" + agent, original_config, method="PUT")
# Delete a draft immediately after its test is accepted, before waiting for completion.
p3 = deepcopy(p)
p3["manifest"]["version"] = "3.0.0"
request("/v1/tools/import", p3)
pending = request(f"/v1/tools/{id}/3.0.0/test", method="POST")
request(f"/v1/tools/{id}/3.0.0", method="DELETE")
assert wait(pending["id"])["status"] == "completed"
for version in ("1.0.0", "1.0.1", "2.0.0"):
    assert request(f"/v1/tools/{id}/{version}", method="DELETE")["status"] == "deleted"
assert not any(t["tool_id"] == id for t in request("/v1/tools"))
expect(404, lambda: request(f"/v1/tools/{id}/1.0.0", method="DELETE"))
expect(404, lambda: request(f"/v1/tools/{id}/1.0.0/export"))
expect(404, lambda: request(f"/v1/tools/{id}/1.0.0/test", method="POST"))
expect(404, lambda: request(f"/v1/tools/{id}/1.0.0/publish", method="POST"))
expect(409, lambda: request("/v1/tools/import", p))
expect(409, lambda: request("/v1/tools/import", changed))
expect(422, lambda: request(path, body))
assert request("/v1/runs/" + accepted["id"])["resolved_tools"] == run["resolved_tools"]
assert request("/v1/runs/" + pending["id"])["resolved_tools"][0]["id"] == id
print(
    "PASS: deletion of drafts/published versions, agent/bundled protection, accepted run snapshots, hidden deleted versions, immutable deleted IDs"
)
