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

## Queue and schedule validation (2026-09-09)

- Python unit/contract suite: **57 passed**; Ruff lint/format and TypeScript/Vite/Prettier checks passed.
- Seven isolated PostgreSQL integration tests passed: concurrent scheduler ticks, rollback, capacity/idempotency, overlap, cadence, pause/resume/delete, one-time execution, and pinned agent configuration.
- Docker and DigitalOcean Kubernetes each completed two distinct minute-interval report runs through `scripts/example_schedules.py`. Both reports were downloaded and checked for total 54 and average 18. Example schedules were left paused for inspection; no LLM calls or credits were used.
- GUI verification: created a one-time schedule and opened its completed run and report; inspected the scheduling page and corrected sidebar label visually.
- Existing local auth/run/idempotency/event/artifact/cancellation smoke checks passed. File/archive regression checks also passed, including exact binary downloads, automatic archive extraction, multi-output ZIPs, and input expiry.
- CI definitions now include scheduler checks and the recurring example, but the updated GitHub Actions workflow has not been observed running. This scheduling increment was not retested on kind or MicroK8s.

## Varied agent examples (2026-09-09)

- **60 unit/contract tests passed**, plus Ruff, Prettier, and production frontend builds.
- GUI checks verified that selecting the auditor/planner loads distinct prompts, switching preserves a draft, and Use suggested task restores the example.
- Live OpenRouter validation on Docker: sales auditor completed in 8 model calls ($0.04052775), dependency planner in 6 ($0.038214). Verified five valid CSV rows and regional/overall revenue, baseline/delayed finish days 10/12, required output files, and ZIP downloads.
- Two initial auditor attempts returned empty model answers at the legacy 2,048-token allowance. The successful checks used the new configurable 8,192-token allowance; no automatic retries or silent model substitutions were added.
- Final image deployed to DigitalOcean; verified all three example records, task suggestions, output allowances, and worker health. Live example runs were performed on Docker only. Release notes editor is bundled and schema-validated but was not live-tested in this increment.
- Bundled examples are inserted only when absent, preserving existing administrator configuration. Older agents and run snapshots keep the default output allowance.

## External access testing (2026-09-09)

- Added an opt-in external Helm Service while retaining the internal API Service on port 8080. Default chart rendering remains private; explicit source ranges are required when enabled.
- Helm lint, server-side validation of the external Service, and the Helm upgrade passed. DigitalOcean adopted the existing load balancer and assigned a NodePort, preserving its public IP.
- One direct public node request through the NodePort returned HTTP 200 for `/healthz`. Subsequent public requests timed out, including console/auth checks; the user subsequently confirmed the console loads through the direct node URL in their regular browser. Automated client connectivity was inconsistent. No administration key was transmitted during automated checks.
- The node health-check and API NodePort returned HTTP 200 from within the cluster. External load-balancer checks did not pass; end-to-end load-balancer access remains unverified. Its client allowlist was not broadened to a separately observed, potentially shared HTTP egress address.

## HTTP-origin run submission (2026-09-09)

Replaced the console's secure-context-only `crypto.randomUUID()` call with 16 random bytes from `crypto.getRandomValues()`, encoded as a 32-character hexadecimal idempotency key. TypeScript/Vite build and formatting passed. Exercised the actual key-generation expression with `randomUUID` unavailable and verified valid, distinct keys across 100 invocations. Updated Docker and DigitalOcean deployments. Authenticated browser execution was not completed because the available public-origin session was signed out.

## Legacy example suggestions (2026-09-09)

- 61 tests passed, plus Ruff. Fixture matching checks cover recognized names/slugs, unrelated agents, distinct suggestions, and the demo-provider tool-check variant.
- Updated Docker and DigitalOcean (Helm revision 10). Database checks confirmed saved suggestions for all four reported cluster fixtures and Harbor guide. The existing richer OpenRouter suggestions remain present.
- Startup backfills only absent suggestion keys for recognized fixtures. Custom agents and explicitly empty suggestions are preserved; existing run and schedule snapshots are unchanged. Example scripts now include suggestions when creating fixtures.

## Configurable concurrent execution (2026-09-09)

- 70 unit/contract tests passed, including real-thread coordinator checks at concurrency limits 1, 3, and 6, cleanup failure handling, coordinator failure shutdown, and invalid configuration. Ruff, TypeScript/Vite build, and Helm lint passed. Helm rejected a zero concurrency limit as expected.
- Docker and DigitalOcean Kubernetes (Helm revision 11) each completed the five-task batch with three overlapping runs and two waiting tasks. Persisted run timestamps confirmed the concurrency ceiling; every run-specific report was downloaded and verified. No LLM credits were used. Kubernetes task Jobs were removed and both platform Deployments were ready after completion.
- Docker API smoke checks passed. Fault injection verified timeout, cancellation, token revocation, input expiry, cancellation without interrupting concurrent peers, and recovery cleanup of multiple interrupted sandboxes without replay.
- Seven isolated PostgreSQL scheduler integration checks passed, including queue capacity/idempotency, concurrent scheduler ticks, no-overlap, and pinned snapshots.
- Both deployments use the default three concurrent runs and 50 waiting slots. Four/six-run deployment settings are configurable; limits 1 and 6 were tested at coordinator level, while infrastructure batch tests used 3. Kubernetes crash recovery and GUI interaction were not retested in this increment; the frontend production build passed.
