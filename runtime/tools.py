import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from runtime.context import WORKSPACE
from runtime.packages import digest, validate_arguments


def execute(name, arguments, packages):
    package = next((p for p in packages if p["manifest"]["name"] == name), None)
    if package is None:
        raise ValueError("Tool is not enabled for this run.")
    payload = {k: v for k, v in package.items() if k != "sha256"}
    if digest(payload) != package["sha256"]:
        raise ValueError("Tool package hash mismatch.")
    validate_arguments(package, arguments)
    limits = package["manifest"]["limits"]
    with tempfile.TemporaryDirectory(prefix="agentberth-tool-") as folder:
        root = Path(folder)
        (root / "handler.py").write_text(package["handler"])
        (root / "request.json").write_text(json.dumps(arguments))
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "runtime.invoke", folder],
                cwd=WORKSPACE,
                stdout=log,
                stderr=log,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "HOME": str(WORKSPACE),
                    "WORKSPACE": str(WORKSPACE),
                    "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                start_new_session=True,
            )
            try:
                process.wait(timeout=limits["timeout_seconds"])
            except subprocess.TimeoutExpired:
                raise ValueError("Tool exceeded its execution timeout.") from None
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            if process.returncode:
                log.seek(0)
                # This contains sandbox-local diagnostics, never a provider credential.
                raise ValueError("Tool process failed: " + log.read(2000).decode(errors="replace"))
        path = root / "result.json"
        if not path.is_file() or path.is_symlink() or path.stat().st_size > limits["max_output_bytes"]:
            raise ValueError("Tool result is missing or exceeds its output limit.")
        result = json.loads(
            path.read_text(),
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON number")),
        )
        try:
            Draft202012Validator(package["manifest"]["output_schema"]).validate(result)
        except ValidationError as exc:
            raise ValueError("Tool output does not match its schema: " + exc.message[:200]) from None
        return result
