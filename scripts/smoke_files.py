"""Verify binary file transport through the real sandbox without an LLM call."""

import base64
import io
import zipfile
import json
import os
from pathlib import Path
import time
import urllib.request
import urllib.error
import uuid

base = os.getenv("AGENTBERTH_BASE_URL", "http://127.0.0.1:8080")
headers = {
    "Authorization": "Bearer " + os.getenv("AGENTBERTH_ADMIN_KEY", "agentberth-local"),
    "Content-Type": "application/json",
}


def request(path, body=None, method=None, raw=False, auth=None):
    req = urllib.request.Request(
        base + path,
        headers=auth or headers,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read() if raw else json.load(r)


def expect(code, fn):
    try:
        fn()
    except urllib.error.HTTPError as e:
        assert e.code == code, (e.code, code)
    else:
        raise AssertionError(f"Expected HTTP {code}")


def wait(id, expected="completed"):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        run = request("/v1/runs/" + id)
        if run["status"] in {"completed", "failed", "cancelled", "timed_out"}:
            assert run["status"] == expected, run
            return run
        time.sleep(0.3)
    raise AssertionError("Run did not finish")


folder = Path(__file__).resolve().parents[1] / "tools/builtin/write-file"
p = {
    "manifest": json.loads((folder / "tool.json").read_text()),
    "handler": (folder / "handler.py").read_text(),
    "tests": json.loads((folder / "tests.json").read_text()),
}
p["manifest"]["id"] = id = "file-check-" + uuid.uuid4().hex[:8]
# The deterministic demo calls write_file; this tested package also copies the uploaded binary.
p["handler"] += """\n_original = run
def run(arguments, context):
    result = _original(arguments, context)
    source = context.workspace_path("inputs/sample.bin")
    if source.exists():
        context.workspace_path("copy.bin").write_bytes(source.read_bytes())
    return result
"""
request("/v1/tools/import", p)
wait(request(f"/v1/tools/{id}/1.0.0/test", method="POST")["id"])
request(f"/v1/tools/{id}/1.0.0/publish", method="POST")
data = bytes(range(256)) * 4096  # Full 1 MiB, includes NUL and invalid UTF-8.
body = {
    "input": "Verify uploaded binary file.",
    "files": [{"name": "sample.bin", "content_base64": base64.b64encode(data).decode()}],
    "disabled_tools": ["write-file"],
    "additional_tools": [{"id": id, "version": "1.0.0"}],
}
path = "/v1/deployments/harbor-guide/runs"
key_headers = {**headers, "Idempotency-Key": id}


# Explicit request to supply an idempotency key.
def keyed(payload):
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode(), headers=key_headers)
    with urllib.request.urlopen(req) as r:
        return json.load(r)


accepted = keyed(body)
assert keyed(body)["id"] == accepted["id"]
changed = {**body, "files": [{"name": "sample.bin", "content_base64": "YWJj"}]}
expect(409, lambda: keyed(changed))
run = wait(accepted["id"])
assert run["files"][0]["size"] == len(data)
assert "content_base64" not in json.dumps(run)
assert run["files"][0]["download_url"] is None
expect(410, lambda: request(f"/v1/runs/{run['id']}/files/0"))
copy = next(a for a in run["artifacts"] if a["name"] == "copy.bin")
assert copy["size"] == len(data)
assert request(f"/v1/runs/{run['id']}/artifacts/{copy['id']}", raw=True) == data
assert all(not a["name"].startswith("inputs/") for a in run["artifacts"])
expect(401, lambda: request(f"/v1/runs/{run['id']}/files/0", auth={"Authorization": "Bearer wrong"}))
expect(410, lambda: request(f"/v1/runs/{run['id']}/files/-1"))
expect(404, lambda: request(f"/v1/runs/{run['id']}/artifacts/missing"))
expect(422, lambda: request(path, {**body, "files": [{"name": "../escape", "content_base64": "YQ=="}]}))
request(f"/v1/tools/{id}/1.0.0", method="DELETE")
print(
    "PASS: 1 MiB binary upload → sandbox processing → exact binary download, input expiry, metadata, idempotency, auth, path checks; temporary tool deleted"
)

archive = io.BytesIO()
with zipfile.ZipFile(archive, "w") as z:
    z.writestr("nested/data.csv", "name,score\nAda,10\n")
archive_body = {
    "input": "Inspect the archive.",
    "files": [{"name": "data.zip", "content_base64": base64.b64encode(archive.getvalue()).decode()}],
}
archive_run = wait(request(path, archive_body)["id"])
assert any(t["id"] == "archive" for t in archive_run["resolved_tools"])
events = request(f"/v1/runs/{archive_run['id']}/events", raw=True).decode()
assert "nested/data.csv" in events and "archive" in events
assert archive_run["files"][0]["download_url"] is None
bundle = request(run["artifacts_archive_url"], raw=True)
with zipfile.ZipFile(io.BytesIO(bundle)) as z:
    assert z.read("copy.bin") == data
    assert "report.md" in z.namelist()
print("PASS: automatic archive tool selection/extraction and multi-output ZIP download")

bad_archive = io.BytesIO()
with zipfile.ZipFile(bad_archive, "w") as z:
    z.writestr("../escape.txt", "unsafe")
bad = wait(
    request(
        path,
        {
            "input": "Inspect archive.",
            "files": [
                {"name": "bad.zip", "content_base64": base64.b64encode(bad_archive.getvalue()).decode()}
            ],
        },
    )["id"],
    expected="failed",
)
assert bad["files"][0]["download_url"] is None
expect(410, lambda: request(f"/v1/runs/{bad['id']}/files/0"))
print("PASS: unsafe archive fails the run and expires its uploads")
