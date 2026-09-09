"""Submit files, wait for a run, and download outputs using the public API only."""

import argparse
import base64
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--file", type=Path, action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Choose a new output directory; existing files are never overwritten.")
    headers = {
        "Authorization": "Bearer " + os.getenv("AGENTBERTH_ADMIN_KEY", "agentberth-local"),
        "Content-Type": "application/json",
    }

    def request(path, body=None, raw=False):
        req = urllib.request.Request(
            args.base_url.rstrip("/") + path,
            headers=headers,
            data=json.dumps(body).encode() if body is not None else None,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.read() if raw else json.load(response)
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"API request failed (HTTP {exc.code}): {exc.read().decode()[:1000]}") from None

    if (
        len(args.file) > 8
        or any(p.stat().st_size > 1024 * 1024 for p in args.file)
        or sum(p.stat().st_size for p in args.file) > 4 * 1024 * 1024
    ):
        parser.error("Use at most 8 files, 1 MiB each, 4 MiB total.")
    files = [{"name": p.name, "content_base64": base64.b64encode(p.read_bytes()).decode()} for p in args.file]
    accepted = request(f"/v1/deployments/{args.agent}/runs", {"input": args.task, "files": files})
    print("Run:", accepted["id"], flush=True)
    deadline = time.monotonic() + 360
    while time.monotonic() < deadline:
        run = request(accepted["status_url"])
        if run["status"] in {"completed", "failed", "timed_out", "cancelled"}:
            break
        time.sleep(0.5)
    else:
        raise SystemExit("Run still queued/running. Use the run ID to inspect it or cancel it.")
    if run["status"] != "completed":
        raise SystemExit(f"Run {run['status']}: {run['error']}")
    print(run["output"])
    args.output_dir.mkdir(parents=True)
    for artifact in run["artifacts"]:
        path = args.output_dir / artifact["name"]
        if not path.resolve().is_relative_to(args.output_dir.resolve()):
            raise SystemExit("Unsafe artifact path returned by server.")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as target:
            target.write(request(f"/v1/runs/{run['id']}/artifacts/{artifact['id']}", raw=True))
        print("Downloaded:", path)


if __name__ == "__main__":
    main()
