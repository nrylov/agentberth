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
