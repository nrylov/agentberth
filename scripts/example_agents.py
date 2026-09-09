"""Run the two analytical OpenRouter examples and verify their downloadable results.

Explicit --live is required because this calls your configured model and spends credits.
"""

import argparse
import csv
import io
import json
import os
from pathlib import Path
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--admin-key-file", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("work/agent-examples"))
    args = parser.parse_args()
    key = (
        args.admin_key_file.read_text().strip()
        if args.admin_key_file
        else os.getenv("AGENTBERTH_ADMIN_KEY", "agentberth-local")
    )

    def request(path, body=None, raw=False):
        req = urllib.request.Request(
            args.base_url + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()
            return data if raw else json.loads(data)

    agents = {a["slug"]: a for a in request("/v1/agents")}
    for slug, expected in [
        ("sales-data-auditor", {"cleaned.csv", "summary.json", "audit.md"}),
        ("project-dependency-planner", {"schedule.csv", "checks.json", "plan.md"}),
    ]:
        agent = agents[slug]
        run = request(f"/v1/deployments/{slug}/runs", {"input": agent["config"]["example_task"]})
        print(f"Running {slug}: {run['id']}", flush=True)
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            detail = request("/v1/runs/" + run["id"])
            if detail["status"] in {"completed", "failed", "cancelled", "timed_out"}:
                break
            time.sleep(1)
        assert detail["status"] == "completed", detail.get("error") or detail["status"]
        files = {}
        destination = args.output_dir / slug / run["id"]
        destination.mkdir(parents=True, exist_ok=True)
        for artifact in detail["artifacts"]:
            if artifact["name"] in expected:
                data = request(f"/v1/runs/{run['id']}/artifacts/{artifact['id']}", raw=True)
                (destination / artifact["name"]).write_bytes(data)
                files[artifact["name"]] = data
        assert expected <= files.keys(), files.keys()
        if slug == "sales-data-auditor":
            rows = list(csv.DictReader(io.StringIO(files["cleaned.csv"].decode())))
            assert len(rows) == 5, rows
            assert abs(sum(float(r["amount"]) for r in rows) - 425.75) < 0.0001
            totals = {}
            for row in rows:
                totals[row["region"]] = totals.get(row["region"], 0) + float(row["amount"])
            assert totals == {"North": 100.5, "South": 125.25, "West": 200.0}, totals
            json.loads(files["summary.json"])
        else:
            checks = json.loads(files["checks.json"])
            assert checks["baseline_finish_day"] == 10 and checks["delayed_finish_day"] == 12, checks
        archive = request(f"/v1/runs/{run['id']}/artifacts.zip", raw=True)
        (destination / "outputs.zip").write_bytes(archive)
        print(
            f"PASS {slug}: {detail['model_calls']} model calls; reported cost ${detail['cost']}; files: {destination}",
            flush=True,
        )


if __name__ == "__main__":
    main()
