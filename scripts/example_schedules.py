"""Create a demo schedule, observe two report runs, download output, and leave it paused.

No LLM credits are used. Standard library only. See docs/scheduling.md.
"""

import argparse
import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--admin-key-file", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("work/scheduled-example"))
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete the schedule after validation instead of keeping it paused.",
    )
    args = parser.parse_args()
    key = (
        args.admin_key_file.read_text().strip()
        if args.admin_key_file
        else os.getenv("AGENTBERTH_ADMIN_KEY", "agentberth-local")
    )

    def request(path, body=None, method=None, raw=False):
        req = urllib.request.Request(
            args.base_url + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()
            return data if raw else json.loads(data)

    slug = "scheduled-example-" + uuid.uuid4().hex[:8]
    request(
        "/v1/agents",
        {
            "slug": slug,
            "name": "Scheduled report example",
            "example_task": "Generate the scheduled demonstration report for 12, 18, and 24. Save the total and average to report.md.",
            "provider": "demo",
            "instructions": "Create a report using the available tools.",
            "tools": ["python", "write_file", "read_file"],
        },
    )
    schedule = request(
        "/v1/schedules",
        {
            "name": "Report every minute (example)",
            "agent_slug": slug,
            "input": "Calculate the total and average of 12, 18, and 24. Save a short report to report.md.",
            "start_at": datetime.now(timezone.utc).isoformat(),
            "interval_seconds": 60,
        },
    )
    schedule_id = schedule["id"]
    print(f"Created schedule {schedule_id}. Waiting for two runs (about 70 seconds).", flush=True)
    found = {}
    try:
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            for run in request("/v1/runs"):
                if run.get("schedule_id") != schedule_id:
                    continue
                assert run["status"] not in {"failed", "timed_out", "cancelled"}, run
                if run["status"] == "completed" and run["id"] not in found:
                    detail = request("/v1/runs/" + run["id"])
                    artifact = next(a for a in detail["artifacts"] if a["name"] == "report.md")
                    data = request(f"/v1/runs/{run['id']}/artifacts/{artifact['id']}", raw=True)
                    assert b"54" in data and b"18" in data, data
                    args.output_dir.mkdir(parents=True, exist_ok=True)
                    destination = args.output_dir / (run["id"] + "-report.md")
                    destination.write_bytes(data)
                    found[run["id"]] = run
                    print(f"Completed {run['id']}; report saved to {destination}", flush=True)
            if len(found) >= 2:
                break
            time.sleep(1)
        assert len(found) >= 2, "Two scheduled runs did not complete within four minutes."
        assert len({r["scheduled_for"] for r in found.values()}) == len(found)
    finally:
        request("/v1/schedules/" + schedule_id, {"enabled": False}, method="PATCH")
        if args.cleanup:
            request("/v1/schedules/" + schedule_id, method="DELETE")
    print("PASS: repeated tasks, distinct occurrences, report downloads, and pause. No LLM credits used.")
    print(
        "Schedule deleted."
        if args.cleanup
        else "The example schedule is paused; resume it in Queue & schedules."
    )


if __name__ == "__main__":
    main()
