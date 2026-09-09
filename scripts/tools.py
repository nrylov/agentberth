"""Import/export Agentberth Tool Package v1 folders. Standard library only."""

import argparse
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--base-url", default="http://127.0.0.1:8080")
sub = parser.add_subparsers(dest="command", required=True)
p = sub.add_parser("import")
p.add_argument("folder", type=Path)
p = sub.add_parser("export")
p.add_argument("id")
p.add_argument("version")
p.add_argument("folder", type=Path)
for command in ("test", "publish"):
    p = sub.add_parser(command)
    p.add_argument("id")
    p.add_argument("version")
sub.add_parser("reload")
args = parser.parse_args()


def request(path, body=None, method=None):
    req = urllib.request.Request(
        args.base_url + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Authorization": "Bearer " + os.getenv("AGENTBERTH_ADMIN_KEY", "agentberth-local"),
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            message = json.load(exc).get("detail", f"HTTP {exc.code}")
        except ValueError:
            message = f"HTTP {exc.code}"
        raise SystemExit(str(message)) from None


if args.command == "import":
    for name in ("tool.json", "handler.py", "tests.json"):
        file = args.folder / name
        if file.is_symlink() or not file.is_file() or file.stat().st_size > 100000:
            raise SystemExit(f"Missing, linked, or oversized package file: {name}")
    package = {
        "manifest": json.loads((args.folder / "tool.json").read_text()),
        "handler": (args.folder / "handler.py").read_text(),
        "tests": json.loads((args.folder / "tests.json").read_text()),
    }
    row = request("/v1/tools/import", package)
    print(f"{row['tool_id']}@{row['version']}: {row['status']} ({row['sha256']})")
elif args.command == "export":
    package = request(f"/v1/tools/{args.id}/{args.version}/export")
    if args.folder.exists():
        raise SystemExit("Destination already exists. Choose a new directory to avoid overwriting files.")
    args.folder.mkdir(parents=True)
    (args.folder / "tool.json").write_text(json.dumps(package["manifest"], indent=2) + "\n")
    (args.folder / "handler.py").write_text(package["handler"])
    (args.folder / "tests.json").write_text(json.dumps(package["tests"], indent=2) + "\n")
    print("Exported package to", args.folder)
elif args.command == "reload":
    print(json.dumps(request("/v1/tools/reload", method="POST"), indent=2))
elif args.command == "publish":
    print(json.dumps(request(f"/v1/tools/{args.id}/{args.version}/publish", method="POST"), indent=2))
elif args.command == "test":
    run = request(f"/v1/tools/{args.id}/{args.version}/test", method="POST")
    print("Sandbox test run:", run["id"])
    deadline = time.monotonic() + 360
    while time.monotonic() < deadline:
        detail = request(run["status_url"])
        if detail["status"] in {"completed", "failed", "cancelled", "timed_out"}:
            print(detail["output"] or detail["error"] or detail["status"])
            raise SystemExit(0 if detail["status"] == "completed" else 1)
        time.sleep(0.5)
    raise SystemExit("Still queued/running. Inspect this run in the console.")
