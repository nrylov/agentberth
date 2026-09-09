# Architecture

## Components

| Component | Responsibility | Privileges |
|---|---|---|
| React console | Configure agents, submit tasks, inspect results | Administration token in browser session storage after manual login |
| FastAPI service | Authentication, run acceptance, provider gateway, events/artifacts, static UI | Database credentials and provider API key |
| PostgreSQL | Durable agents, runs, event sequence, binary/text artifacts, temporary run inputs, worker heartbeat | Internal database network only |
| Worker | Claim queued work, launch and monitor containers, terminate and clean up | Database credentials; Docker socket locally or sandbox namespace RBAC on Kubernetes |
| Runtime | Agent loop and local tools | Run-scoped bearer token and temporary workspace |

The runtime uses Python plus a locked JSON Schema validator; custom handlers target the standard library. The API and worker share a locked platform image but have separate environments and network attachments. A one-shot `runtime-image` Compose service makes sure the runtime image is built during the quick start. Its successful exit is expected.

## Run lifecycle

1. Authenticate the request with the local administration key.
2. Resolve the endpoint slug and copy its current configuration, version, and model into a run record.
3. Atomically record the run and the `run.queued` event. Return HTTP 202.
4. The single worker claims a queued row using a transaction and row lock.
5. Generate a random token; store its SHA-256 hash in PostgreSQL. Give the raw token only to that run's container.
6. Create a non-root, resource-limited container. The runtime fetches its input/configuration from the internal API.
7. In real-provider mode, the runtime asks the gateway for a model response, executes requested tools, and sends tool results back on the next model turn. Provider-specific reasoning metadata is preserved in the in-memory conversation, but not emitted in the activity log.
8. The runtime submits its final text and bounded binary/text output files to the API, then exits.
9. The worker checks the exit result, removes the container, sets a terminal state, and revokes the token.

States: `queued → running → completed | failed | cancelled | timed_out`. A queued run can be cancelled directly. Cancelling a running run immediately blocks new authenticated runtime work; the worker destroys the container on its next monitor cycle. An in-flight provider call may still finish and incur usage, which is recorded even after cancellation.

A successful result callback alone does not complete a run: the worker also requires a successful process exit and successful teardown.

## Persistence

- PostgreSQL stores the latest agent configuration and a monotonically increasing version number.
- Every accepted run stores its own full configuration snapshot. Editing an agent cannot change queued or running work.
- This preview does **not** retain a separately browsable history of unused agent versions or implement rollback.
- Event IDs are increasing database sequence values. They are not guaranteed to be contiguous within a run.
- Binary/text artifacts are stored in PostgreSQL: at most eight files, 1 MiB each and 4 MiB total. Inputs are staged per run and purged on all terminal transitions; sandbox inputs and extracted archives are ephemeral. Multiple outputs can be downloaded as ZIP. Larger files and object storage are future work.
- The container workspace and in-memory conversation are ephemeral. Sessions and persistent workspace reuse are not implemented.
- PostgreSQL's named volume survives `docker compose down`.

Schema setup is additive `CREATE TABLE IF NOT EXISTS` under an advisory lock. Before changing existing table structures, introduce versioned migrations; this is not yet a general migration system.

## Scheduling and failure semantics

One worker owns a database advisory lock. A second worker exits instead of concurrently reconciling the same backend resources. The worker reports a heartbeat every scheduling/monitor cycle.

On restart, the worker first removes Agentberth-labelled orphan containers, then marks previously running jobs failed. Queued runs remain queued and can execute. Failed/running work is never automatically replayed, because tools may already have produced side effects. Clients choose whether to submit a new invocation.

Idempotency is scoped to the deployment slug. Reusing a key with identical input returns the original run; different input returns HTTP 409. The original run is returned even after an agent configuration changes. The key deduplicates run acceptance, not arbitrary external tool effects.

This is not a distributed lease scheduler. PostgreSQL failure or failed sandbox teardown may require the worker to restart before status can be reconciled. Do not horizontally scale the worker or run multiple installations with the same Docker labels/network names yet.

## Backend extension point

`services/agentberth/backends/__init__.py` defines `RunSpec` and `ExecutionBackend`:

- `submit`: create a sandbox and return its handle.
- `status`: report process state and exit code.
- `cancel`: terminate execution.
- `cleanup`: remove the environment idempotently.

The worker selects Docker by default or Kubernetes with `EXECUTION_BACKEND=kubernetes`. Both implement startup orphan reconciliation and the lifecycle operations. Kubernetes runs the worker in-cluster; Jobs use a dedicated sandbox namespace and short-lived token Secrets. See [Kubernetes deployment](kubernetes.md) for Helm configuration and the tested isolation boundaries.

See the [Kubernetes/microVM roadmap](roadmap.md) for runtime classes, packaging, and acceptance criteria.


## Tool package storage

Bundled folders are discovered at API startup and registered transactionally in `tool_versions`. Imported drafts and published packages persist as JSONB, including source and fixtures. Registration parses source syntax without importing it. Versions are immutable; the hash covers the complete package.

New runs embed their resolved package contents and hashes in `spec.tool_packages`; registry publication cannot change an accepted run. The gateway uses snapshot schemas and runtime invocations execute snapshot handlers in child processes inside the container. No package source is executed by the API or worker. Fixture runs use the same queue, container backend, events, deadlines, and cleanup behavior with `spec.tool_test` enabled and no model calls.

The registry table is created additively under the existing startup schema lock. Existing agent defaults and queued runs are upgraded transactionally; historical terminal runs are left unchanged. A general schema migration framework is still future work.
