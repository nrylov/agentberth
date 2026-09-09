# Development and troubleshooting

## Repository layout

```text
apps/web/                    React + TypeScript console
services/agentberth/api.py    FastAPI control plane and model gateway
services/agentberth/db.py     Schema, persistence, terminal transitions
services/agentberth/worker.py Single-worker queue and recovery
services/agentberth/backends/ Execution contract and Docker backend
runtime/                     Agent loop, schema validation, sandbox tool runner
tools/                       Bundled packages and shareable examples
scripts/                     End-to-end checks
tests/                       Unit tests
docs/                        Architecture, API, security, roadmap
```

## Local setup

Run `docker compose up --build -d` from the repository root. Compose reads `.env` automatically; you do not need to source it. Do not overwrite an existing `.env` with the example.

For Python editing/tests, install Python 3.12+ and [uv](https://docs.astral.sh/uv/):

```bash
uv sync --locked
uv run pytest
uv run ruff check services runtime tests scripts
uv run ruff format --check services runtime tests scripts
```

For frontend development, use Node 22+:

```bash
cd apps/web
npm ci
npm run dev
```

Vite prints a local URL and proxies `/v1` to the Compose API on port 8080. If you change `AGENTBERTH_PORT`, also change the local proxy target in `vite.config.ts`. The production UI is compiled into the API image; it does not require a separate frontend server.

After source changes, rebuild with `docker compose up --build -d`. Configuration-only `.env` changes need `docker compose up -d`; `docker compose restart` alone does not apply changed environment variables.

## Dependency updates

`uv.lock` is the authoritative Python lock. `requirements.lock` is its exported production dependency set used by Docker. After intentional dependency changes:

```bash
uv lock
uv export --no-dev --no-hashes --no-emit-project --format requirements-txt --output-file requirements.lock
uv sync --locked
```

Commit both files. The frontend uses `package-lock.json` and `npm ci`; run `npm run format:check` before contributing UI changes. Container base images are version-tagged rather than digest-pinned in this development preview.

## Verification

```bash
python3 scripts/smoke.py
python3 scripts/smoke.py --live  # requires credits; optional
python3 scripts/resilience.py   # pauses test sandboxes and restarts the worker
python3 scripts/smoke_tools.py  # registry, fixtures, snapshots, per-run selection
python3 scripts/smoke_tools.py --live  # optional paid custom-tool integration
```

For a custom administration key, set `AGENTBERTH_ADMIN_KEY` in the script environment. The scripts do not parse `.env` or print credentials. Pass `--base-url http://localhost:PORT` if needed. Test fixtures remain in run history so you can inspect them.

CI runs the Python checks, frontend build, Docker build, demo smoke test, and resilience test on Linux. Live model tests are opt-in and do not run in CI. Local macOS ARM64 validation does not by itself establish support for every host/architecture.

## Troubleshooting

### Docker socket not found / worker offline

Make sure Docker Desktop is running. Inspect the endpoint with `docker context inspect`; if `/var/run/docker.sock` is unavailable, set `DOCKER_SOCKET` in `.env` to your user's socket (often `/Users/your-name/.docker/run/docker.sock`) and recreate the worker. Do not make the socket world-writable.

`runtime-image` exiting successfully is normal. The API, worker, and PostgreSQL should stay running:

```bash
docker compose ps -a
docker compose logs --tail=50 worker api
```

Avoid sharing `docker compose config`, container environment dumps, or `.env`: they can reveal the provider key.

### Port 8080 already in use

Set `AGENTBERTH_PORT=8081` in `.env` and run `docker compose up -d`. The UI and public API share the selected port.

### Provider shows “Demo only”

Set `LLM_API_KEY`, recreate the API, and refresh Settings. The pre-seeded Harbor guide remains a demo even when credentials exist. Create/configure an OpenRouter agent explicitly to make paid calls.

### Model request failed

Check credits, model ID, and tool-calling support in OpenRouter. The gateway deliberately reports a sanitized error. Model step exhaustion can be addressed by simplifying the task or increasing the agent's step limit. A slow model can hit the per-call 60-second timeout or run deadline.

### Run stuck or interrupted

Check worker logs and Docker availability. Restarting the worker removes orphaned Agentberth containers and marks interrupted runs failed, without replaying tools. The worker supports only one process. Do not use `docker compose up --scale worker=...`.

### Artifact missing

Up to eight regular binary/text outputs are collected, with a 1 MiB per-file and 4 MiB total limit. Save deliverables outside `inputs/`; hidden files and symlinks are excluded. Exceeding size/count limits fails the run with a diagnostic event. The workspace and staged input bytes expire when the run ends. See [file workflows](files.md) for archive support, API examples, and downloads.

### Reset local data

`docker compose down` preserves data. `docker compose down -v` permanently removes the named database volume. There is no undo; export anything you need first.

## Browser integration

Browsers that expose the experimental `document.modelContext` interface can discover two optional tools: `agentberth_list_agents` and `agentberth_prepare_run`. Preparing a task changes the visible playground without executing it or spending credits. Both use the current console authentication. Unsupported browsers continue normally. The initial local validation covers compilation and the HTTP/SSE contracts; it does not claim browser interaction or WebMCP runtime verification.


## Runtime validator lock

`runtime/requirements.lock` pins the `jsonschema` dependency closure from `uv.lock` for the sandbox image. When updating the validator, regenerate both platform and runtime lock exports, then rebuild both images and run the tool integration checks. Tool handlers target the standard library; package dependency installation is not supported.

## Tool registry development

See [Tool Package v1](tools.md) for the format, immutable version rules, authoring UI, and CLI. `compose.tools-dev.yaml` optionally mounts repository defaults read-only for explicit reloads. Source changes at an existing ID/version are conflicts; bump the version before reloading. Imported packages persist across image rebuilds and restarts.

Run `python3 scripts/smoke_files.py` to verify binary transport, automatic archives, input expiry, and ZIP output without model credits. `scripts/resilience.py` also verifies expiry after timeout, cancellation, and worker restart.
