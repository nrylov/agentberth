# Tools and runtime authoring

The curated runtime includes three tools:

| Tool | Arguments | Result |
|---|---|---|
| `python` | `code` | `exit_code`, bounded combined stdout/stderr |
| `write_file` | `path`, `content` | Relative path and byte count |
| `read_file` | `path` | First 8,000 characters of UTF-8 text |

All tools execute inside the run's container. Tools selected in an agent's configuration are advertised to the model; unknown or disabled tools return a tool error. Tool output is data, not instructions for the control plane.

Example model-requested tool call:

```json
{"name":"write_file","arguments":{"path":"report.md","content":"# Report\n\nThe answer is 56."}}
```

## Add a curated tool

1. Add its JSON schema and description to `SCHEMAS` in `runtime/tools.py`.
2. Implement its dispatch branch in `execute`, with argument validation and bounded output.
3. Add its name to `ToolName` in `services/agentberth/schemas.py` and the console's tool selector.
4. Add meaningful tests for behavior and failure boundaries.
5. Rebuild both the platform and runtime images with `docker compose up --build -d`.

For example, a `list_files` tool could accept no arguments and return up to 100 workspace-relative filenames. Its implementation should avoid symlink traversal and omit files outside the workspace. Do not expose an unconstrained host path or pass Docker/LLM credentials to a tool.

Runtime dependencies belong in the runtime Dockerfile stage; adding a package only to the platform's `pyproject.toml` does not install it into sandboxes. The current runtime intentionally uses the standard library only. Installing arbitrary packages during a run and user-supplied images are not supported.

## Failure and limits

Python runs have a 10-second timeout; their process group is killed afterward to clean up child processes. Output capture is bounded and backed by limited temporary storage. Other failures become tool results so the model can correct a bad call. Reaching the overall step/deadline limits terminates the run.

Artifacts are collected only after successful agent-loop completion, before the container exits. They are small UTF-8 files, not a general workspace export.

Remote HTTP tools are intentionally absent in v0.1 because sandboxes have no direct internet route. Add an authenticated, destination-restricted integration gateway before exposing remote tools. The future Kubernetes backend should use the same tool schemas and runtime HTTP protocol.
