"""Submit a batch of isolated demo tasks and verify bounded concurrent execution.

Uses no LLM credits. Run against an idle development installation with schedules paused.
The example agent and completed run history remain available in the console.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
import time
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--base-url", default="http://127.0.0.1:8080")
args = parser.parse_args()
key = os.getenv("AGENTBERTH_ADMIN_KEY", os.getenv("ADMIN_KEY", "agentberth-local"))


def request(path, body=None, raw=False):
    req = urllib.request.Request(
        args.base_url + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode() if raw else json.load(response)


queue = request("/v1/queue")
assert queue["running"] == queue["queued"] == 0, "Wait for the installation to become idle."
limit = queue["max_concurrent_runs"]
count = limit + 2
assert count <= queue["capacity"], "Increase queue capacity to at least concurrency + 2 for this example."
slug = "concurrency-example"
if not any(a["slug"] == slug for a in request("/v1/agents")):
    request(
        "/v1/agents",
        {
            "slug": slug,
            "name": "Concurrent report example",
            "provider": "demo",
            "instructions": "Run the fixed demonstration and produce a report.",
            "example_task": "Generate the fixed demo report in an isolated sandbox. Submit a batch using scripts/example_concurrency.py to demonstrate concurrency.",
            "tools": ["python", "write_file", "read_file"],
        },
    )


def submit(index):
    return request(f"/v1/deployments/{slug}/runs", {"input": f"Concurrency example report {index + 1}."})[
        "id"
    ]


with ThreadPoolExecutor(max_workers=count) as pool:
    ids = list(pool.map(submit, range(count)))
print(f"Submitted {count} tasks; configured concurrency {limit}.")
end = time.monotonic() + 300
previous = None
while time.monotonic() < end:
    queue = request("/v1/queue")
    assert queue["running"] <= limit, queue
    snapshot = (queue["running"], queue["queued"])
    if snapshot != previous:
        print(f"Running: {snapshot[0]}/{limit}; queued: {snapshot[1]}")
        previous = snapshot
    runs = [request("/v1/runs/" + id) for id in ids]
    if all(r["status"] in {"completed", "failed", "cancelled", "timed_out"} for r in runs):
        break
    time.sleep(0.2)
else:
    raise AssertionError("Batch did not finish within five minutes.")

# Persisted timestamps prove overlap even when short tasks finish between polls.
timeline = []
for run in runs:
    assert run["status"] == "completed", (run["id"], run["status"], run.get("error"))
    timeline.extend(
        [
            (datetime.fromisoformat(run["started_at"].replace("Z", "+00:00")), 1),
            (datetime.fromisoformat(run["finished_at"].replace("Z", "+00:00")), -1),
        ]
    )
    artifact = next(a for a in run["artifacts"] if a["name"] == "report.md")
    report = request(f"/v1/runs/{run['id']}/artifacts/{artifact['id']}", raw=True)
    assert run["input"] in report and "54" in report
active = peak = 0
for _, delta in sorted(timeline):
    active += delta
    peak = max(peak, active)
assert peak == limit, f"Expected {limit} overlapping runs, observed {peak}."
print(f"PASS: peak concurrency {peak}; all {count} isolated reports completed and downloaded.")
