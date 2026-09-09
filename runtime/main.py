import json
import os
import base64
import sys
import time
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from runtime.tools import WORKSPACE, execute
from runtime.archives import is_archive
from runtime.files import MAX_FILE_BYTES, MAX_TOTAL_BYTES, validate_name, decode_file


def request(path, data=None):
    req = urllib.request.Request(
        os.environ["API_URL"] + "/internal/runs/" + os.environ["RUN_ID"] + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Authorization": "Bearer " + os.environ["RUN_TOKEN"], "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=70) as response:
        return json.load(response)


def event(kind, data):
    request("/events", {"kind": kind, "data": data})


def preview(data):
    text = json.dumps(data)
    return data if len(text) < 12000 else {"preview": text[:10000], "truncated": True}


def tool(name, args, allowed, fail_on_error=False):
    package = next((p for p in allowed if p["manifest"]["name"] == name), None)
    event(
        "tool.started",
        {
            "name": name,
            "arguments": preview(args),
            "tool": {
                "id": package["manifest"]["id"],
                "version": package["manifest"]["version"],
                "sha256": package["sha256"],
            }
            if package
            else None,
        },
    )
    try:
        output = execute(name, args, allowed)
    except Exception as exc:
        if fail_on_error:
            raise
        output = {"error": str(exc)[:1000]}
    event("tool.completed", {"name": name, "result": preview(output)})
    return output


def demo(context):
    event("agent.message", {"text": "Demo mode: running a fixed example without contacting an LLM."})
    time.sleep(1)
    allowed = context["spec"]["tool_packages"]
    names = context["spec"]["tools"]
    result = {"output": "Tool execution is disabled."}
    if "python" in names:
        result = tool(
            "python",
            {
                "code": "import json\nprint(json.dumps({'values': [12, 18, 24], 'total': sum([12, 18, 24]), 'average': sum([12, 18, 24])/3}))"
            },
            allowed,
        )
    text = "# Agentberth demo report\n\nThis is a deterministic demo, not a model-generated answer.\n\n"
    if context["spec"].get("input_files"):
        text += (
            "Uploaded files (demo does not interpret their contents):\n"
            + "\n".join("- inputs/" + f["name"] for f in context["spec"]["input_files"])
            + "\n\n"
        )
    text += "Your input: " + context["input"] + "\n\nExample calculation:\n" + result.get("output", "")
    if "write_file" in names:
        tool("write_file", {"path": "report.md", "content": text}, allowed)
    return (
        "Demo complete. The example calculated a total of 54 and an average of 18."
        if "python" in names
        else "Demo complete. Enable Python to run the example calculation."
    )


def agent(context):
    spec = context["spec"]
    file_note = ""
    if spec.get("input_files"):
        file_note = (
            "\n\nUploaded files in the workspace (use tools to read them):\n"
            + "\n".join("inputs/" + f["name"] for f in spec["input_files"])
            + "\nUploaded archives were automatically extracted under inputs/extracted/<upload index>/. Use Python to list/read those files. Save deliverables outside inputs/ so they are collected for download."
        )
    messages = [
        {"role": "system", "content": spec["instructions"]},
        {"role": "user", "content": context["input"] + file_note},
    ]
    for _ in range(spec["max_steps"]):
        message = request("/model", {"messages": messages})["message"]
        # Keep provider reasoning_details intact for subsequent tool turns. Never emit them as events.
        messages.append(message)
        calls = message.get("tool_calls") or []
        if not calls:
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError(
                    "Model returned no final answer. Try a different model or a simpler request."
                )
            return content[:30000]
        if len(calls) > 8:
            raise ValueError("Model requested too many tools in one step.")
        for call in calls:
            function = call["function"]
            try:
                args = json.loads(function["arguments"])
                if not isinstance(args, dict):
                    raise ValueError("Tool arguments must be an object.")
                output = tool(function["name"], args, spec["tool_packages"])
            except (ValueError, KeyError):
                output = {"error": "Invalid tool call arguments."}
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(output)})
    raise ValueError("Agent reached its model-step limit before returning a final answer.")


def stage_files(context):
    for item in context["spec"].get("files", []):
        name = validate_name(item["name"])
        target = WORKSPACE / "inputs" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(decode_file(item["content_base64"]))


def artifacts():
    items, total, scanned = [], 0, 0
    for root, directories, files in os.walk(WORKSPACE, followlinks=False):
        directories[:] = sorted(
            d
            for d in directories
            if not d.startswith(".")
            and not (Path(root) / d).is_symlink()
            and not (Path(root) == WORKSPACE and d == "inputs")
        )
        scanned += len(directories) + len(files)
        if scanned > 200:
            raise ValueError("Output workspace exceeds the 200-entry scan limit.")
        for filename in sorted(files):
            path = Path(root) / filename
            if filename.startswith(".") or path.is_symlink() or not path.is_file():
                continue
            name = validate_name(str(path.relative_to(WORKSPACE)))
            with path.open("rb") as source:
                content = source.read(MAX_FILE_BYTES + 1)
            total += len(content)
            if len(content) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES or len(items) >= 8:
                raise ValueError(
                    "Output file limits exceeded: 8 files, 1 MiB each, 4 MiB total. Save fewer or smaller deliverables."
                )
            items.append({"name": name, "content_base64": base64.b64encode(content).decode("ascii")})
    return items


def test_package(context):
    from runtime import tools

    package = context["spec"]["tool_packages"][0]
    original = tools.WORKSPACE
    try:
        for fixture in package["tests"]:
            with tempfile.TemporaryDirectory(dir=original, prefix="fixture-") as directory:
                tools.WORKSPACE = Path(directory)
                for path, content in fixture["files"].items():
                    target = Path(directory) / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content)
                event("agent.message", {"text": "Testing: " + fixture["name"]})
                result = tool(
                    package["manifest"]["name"], fixture["arguments"], [package], fail_on_error=True
                )
                if result != fixture["expected"]:
                    raise ValueError("Fixture failed: " + fixture["name"] + ". Inspect the tool result.")
        return f"All {len(package['tests'])} fixtures passed for {package['manifest']['id']}@{package['manifest']['version']}."
    finally:
        tools.WORKSPACE = original


def main():
    try:
        context = request("/context")
        stage_files(context)
        context["spec"].pop("files", None)
        for i, item in enumerate(context["spec"].get("input_files", [])):
            if is_archive(item["name"]):
                tool(
                    "archive",
                    {"path": "inputs/" + item["name"], "destination": f"inputs/extracted/{i}"},
                    context["spec"]["tool_packages"],
                    fail_on_error=True,
                )
        output = (
            test_package(context)
            if context["spec"].get("tool_test")
            else (demo(context) if context["spec"]["provider"] == "demo" else agent(context))
        )
        request("/result", {"output": output, "artifacts": artifacts()})
    except Exception as exc:
        if isinstance(exc, urllib.error.HTTPError):
            message = "Platform request failed (HTTP " + str(exc.code) + ")."
            try:
                message += " " + str(json.load(exc).get("detail", ""))[:500]
            except Exception:
                pass
        else:
            message = str(exc)[:1000]
        try:
            event("agent.message", {"text": message, "level": "error"})
        except Exception:
            pass
        # Avoid raw exceptions/tracebacks containing environment or request details.
        print("Agent runtime failed. See run events.", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
