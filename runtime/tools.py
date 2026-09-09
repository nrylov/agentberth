import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

WORKSPACE = Path(os.getenv("WORKSPACE", "/workspace"))

SCHEMAS = {
    "python": {
        "description": "Run Python code in the temporary workspace. Standard library only. Print the result.",
        "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]},
    },
    "write_file": {
        "description": "Write a UTF-8 text artifact to a relative path in the workspace.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    "read_file": {
        "description": "Read a UTF-8 text file from the workspace.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
}


def definitions(names):
    return [
        {"type": "function", "function": {"name": name, **SCHEMAS[name]}} for name in dict.fromkeys(names)
    ]


def workspace_path(value):
    root = WORKSPACE.resolve()
    path = (root / value).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError("Path must stay inside the workspace.")
    return path


def execute(name, args, allowed):
    if name not in allowed:
        raise ValueError("Tool is not enabled for this agent.")
    if name == "python":
        code = args["code"]
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
    if name == "write_file":
        path = workspace_path(args["path"])
        content = args["content"]
        if len(content.encode()) > 64000:
            raise ValueError("Text artifacts are limited to 64 KB.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"path": args["path"], "bytes": len(content.encode())}
    if name == "read_file":
        with workspace_path(args["path"]).open("r", encoding="utf-8") as handle:
            return {"content": handle.read(8000)}
    raise ValueError("Unknown tool.")
