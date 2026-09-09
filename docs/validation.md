# Local validation record

Initial validation: 2026-09-09, macOS host, Docker Linux ARM64 engine, Compose 5.5.1.

| Check | Result |
|---|---|
| Python unit/contract tests | 11 passed |
| Ruff lint and formatting | Passed |
| Frontend TypeScript, Vite production build, Prettier | Passed |
| Docker multi-stage builds and Compose startup | Passed |
| Demo execution in a separate container | Passed |
| Authentication, idempotency and event replay | Passed |
| Text artifact persistence/download | Passed |
| Run version preserved across configuration update | Passed |
| Real OpenRouter agent | Passed: Python calculation, file write, final answer |
| Real model usage | 3 model calls; $0.00111675 reported for the live smoke test |
| Sandbox resource configuration and credential separation | Passed |
| Cross-run/admin token rejection and terminal revocation | Passed |
| Timeout and running cancellation cleanup | Passed |
| Abrupt worker loss and orphan reconciliation | Passed; no replay |
| Credential scan of source and documentation | Passed |

The real model test used `google/gemini-3.8-flash`; future availability and behavior are not guaranteed. Tests can be repeated with the scripts in `scripts/`. Fault-injection tests are for development environments only.

The GitHub Actions workflow is included but has not been run on GitHub as part of this local implementation. Browser interaction/accessibility automation, optional WebMCP runtime behavior, Kubernetes, microVMs, multi-tenancy, and production hardening have not been validated. The Python test run emitted upstream TestClient/AnyIO deprecation warnings; these did not fail the tests.

## Tool registry milestone

Validated locally after the initial preview:

- 21 Python unit/contract tests passed, including package parsing without source execution, schema/path rejection, hash tampering, custom handler execution, result validation, timeouts, and fixture error handling.
- Frontend TypeScript/Vite build and formatting passed.
- The existing PostgreSQL volume upgraded without resetting agents, runs, or provider configuration.
- Package import/export, draft isolation, sandbox fixtures, publication, immutable version conflicts, per-run additions/disabling, snapshot hashes, failed-test rejection, and override-aware idempotency passed integration checks.
- A real OpenRouter run used an added CSV tool while Python was disabled for that run: three model calls, provider-reported cost $0.001515.
- Existing demo, authentication, event replay, cancellation, timeout, and worker recovery checks passed after the package migration.
- The `summarize-csv@1.0.0` example was imported, tested, and published in the local workspace.

The registry/UI changes have not undergone browser interaction automation. LLM-assisted generation, arbitrary package dependencies, and remote tools remain future work. The GitHub Actions workflow now includes the key-free tool integration suite but has not been executed on GitHub here.

## Tool deletion

Validated on 2026-09-09 against the local Docker stack:

- All 21 Python tests, Ruff checks, and the TypeScript/Vite production build passed.
- Tool integration checks passed for draft/published deletion, bundled and agent-reference protection, deleted-version visibility and reuse prevention, and preservation of accepted/historical run snapshots.
- A sandbox test accepted immediately before deletion completed successfully afterward. No LLM calls were required.
- The tool smoke script now deletes its generated tool versions after successful verification.

## Console themes

The TypeScript/Vite production build and formatting checks pass for the default dark theme and light-mode switch. Theme initialization was checked with no saved preference, both valid preferences, an invalid stored value, and unavailable browser storage. The preference initializer is served as an external same-origin asset to comply with the console CSP. Visual browser verification was not performed.

## Run files and archives

Validated on 2026-09-09 against the local Docker stack:

- 43 Python tests passed, including binary transport validation, input staging, output limits, ZIP/TAR extraction, archive traversal/link rejection, expansion bounds, and ZIP creation.
- Ruff and the TypeScript/Vite production build passed. Browser visual verification was not performed.
- The file integration suite verified a 1 MiB binary upload through the real sandbox and byte-for-byte output download, automatic archive resolution/extraction, combined output ZIP, authentication, idempotency, and invalid-archive failure.
- Recovery checks verified input expiry after timeout, cancellation, and worker-restart failure. Completed/failed runs were also covered. A direct database assertion found no terminal run retaining its input payload.
- Existing demo integration checks and older UTF-8 artifact compatibility passed. The bundled archive fixture and documented `scripts/run_files.py` example passed without model credits.

## Kubernetes backend and Helm chart

Local checks on 2026-09-09: 50 Python tests, Ruff checks, frontend production build, Helm lint, and Kubernetes manifest client validation passed.

- kind v0.33.0 / Kubernetes v1.37.0 on macOS Docker Desktop ARM64: chart installation/upgrade, public demo and binary/archive workflow, sandbox network denial, Job security, cancellation, timeout, worker-restart reconciliation, input expiry, and token Secret cleanup passed.
- DigitalOcean Kubernetes v1.36.3 on a single AMD64 4 GiB node: registry image pulls, a 5 GiB block-storage PVC, chart deployment/upgrade, public demo and binary/archive workflow, sandbox network denial, Job security, cancellation, timeout, worker-restart reconciliation, input expiry, and token Secret cleanup passed.
- Published platform/runtime images include AMD64 and ARM64 manifests. The cloud test uses digest-pinned images from one DigitalOcean registry repository with separate tags.
- Worker readiness uses a local timestamp written after its database heartbeat, avoiding repeated database-driver imports under CPU limits. API/worker use Recreate rollouts.
- Docker Compose demo and recovery regressions passed after introducing backend selection.
- A Kubernetes CI workflow is included; its GitHub-hosted execution has not yet been observed. MicroK8s values/instructions are provided but have not been runtime-tested. VM-backed RuntimeClass execution remains unverified.
- No browser visual verification was performed.

The DigitalOcean OpenRouter/custom-tool integration also passed: 3 model calls, provider-reported cost $0.001305, followed by successful tool-version deletion and historical snapshot checks.
