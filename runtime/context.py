import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

WORKSPACE = Path(os.getenv("WORKSPACE", "/workspace"))


def workspace_path(value):
    root = WORKSPACE.resolve()
    path = (root / value).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError("Path must stay inside the workspace.")
    return path


def run_python(code):
    if len(code) > 20000:
        raise ValueError("Python code is too long.")
    # Bound memory capture: output goes to the size-limited tmpfs, not a PIPE.
    with tempfile.TemporaryFile() as out:
        process = subprocess.Popen(
            [sys.executable, "-c", code],
            cwd=WORKSPACE,
            stdout=out,
            stderr=out,
            env={"PATH": os.environ.get("PATH", ""), "HOME": str(WORKSPACE), "PYTHONIOENCODING": "utf-8"},
            start_new_session=True,
        )
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise ValueError("Python tool exceeded its 10-second limit.") from None
        finally:
            # Terminate subprocesses left behind after the parent exits.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        out.seek(0)
        return {
            "exit_code": process.returncode,
            "output": out.read(8000).decode("utf-8", errors="replace"),
        }


class Context:
    workspace_path = staticmethod(workspace_path)
    run_python = staticmethod(run_python)
