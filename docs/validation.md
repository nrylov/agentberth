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
