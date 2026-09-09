# API guide

Base URL: `http://localhost:8080`. All `/v1` endpoints require `Authorization: Bearer <AGENTBERTH_ADMIN_KEY>`. In this preview, one key administers and invokes the entire local workspace; deployment-scoped keys and user accounts are not implemented.

`GET /healthz` and `GET /openapi.json` are public. The OpenAPI schema is the full request/response shape reference. An embedded Swagger UI is deliberately omitted so the console and API reference do not depend on third-party CDN scripts.

## Agents and deployments

| Method | Path | Behavior |
|---|---|---|
| GET | `/v1/agents` | List agents and latest configurations |
| POST | `/v1/agents` | Create and immediately publish an agent (201) |
| PUT | `/v1/agents/{slug}` | Replace configuration, increment version, publish |
| GET | `/v1/settings` | Provider configuration status and worker heartbeat; no secret values |

Example creation body:

```json
{
  "slug": "report-writer",
  "name": "Report writer",
  "instructions": "Use Python when useful. Save requested reports as text files.",
  "provider": "openrouter",
  "model": "",
  "tools": [{"id":"python","version":"1.0.0"}, {"id":"write-file","version":"1.0.0"}, {"id":"read-file","version":"1.0.0"}],
  "max_steps": 6,
  "timeout_seconds": 120
}
```

Use `provider: "demo"` for a deterministic test. Slugs use lowercase letters, numbers, and hyphens, start with a letter, and are 2–48 characters long. Slugs are stable and not editable. A blank model uses the environment default at run acceptance. PUT uses the same body without `slug`.

The deployment is the agent's stable slug in this release. There is no separate deployment resource, draft state, or rollback API yet.

## Runs

```http
POST /v1/deployments/report-writer/runs
Authorization: Bearer <admin-key>
Content-Type: application/json
Idempotency-Key: example-001

{"input":"Compute 7 * 8 with Python and save answer.txt."}
```

Response (202):

```json
{
  "id": "<uuid>",
  "status_url": "/v1/runs/<uuid>",
  "events_url": "/v1/runs/<uuid>/events"
}
```

| Method | Path | Behavior |
|---|---|---|
| GET | `/v1/runs` | Most recent 100 runs |
| GET | `/v1/runs/{id}` | Status, output, error, timestamps, usage, artifact metadata |
| POST | `/v1/runs/{id}/cancel` | Request cancellation; terminal runs remain unchanged |
| GET | `/v1/runs/{id}/events` | Persisted events followed by live events via SSE |
| GET | `/v1/runs/{id}/artifacts/{artifact_id}` | Download a text or binary output attachment |

The `cost` value is the provider-reported cost in USD, not a billing guarantee. Demo calls report zero. Usage may finish updating after cancellation if an upstream model request was already in flight.

## Streaming and reconnecting

Each event is a standard SSE frame:

```text
id: 42
data: {"id":42,"run_id":"...","kind":"tool.completed","data":{"name":"python","result":{"output":"56\n","exit_code":0}},"created_at":"..."}

```

Kinds include `run.queued`, `run.started`, `model.started`, `model.completed`, `tool.started`, `tool.completed`, `agent.message`, `agent.result`, and terminal `run.*` events. Tool failures appear in tool result data; the model can respond to them. Infrastructure/model-loop failure terminates the run.

Reconnect with `Last-Event-ID: 42` or `?after=42`. If both are supplied, the larger cursor wins. The server emits comment heartbeats and closes after all persisted terminal-run events have been sent. The console uses authenticated `fetch()` streaming because native `EventSource` cannot set a bearer header.

Input, tool arguments/results, and artifacts can contain user data. Provider-internal reasoning is not part of the event stream.

## Errors and limits

- `401`: invalid administration key or expired/internal run token.
- `404`: unknown agent, run, or artifact.
- `409`: duplicate slug, conflicting idempotency input, or runtime state conflict.
- `413`: request body or event too large.
- `422`: invalid request or missing provider configuration.
- `429`: local queue or runtime step/event limit reached.
- `502`: upstream model call failed (internal gateway).

Limits: 8,000 input characters; 1–12 model calls; 2,048 completion tokens per call including any provider reasoning; 10–300 seconds per run; up to 8 tool calls per model turn; 10 seconds per Python tool; 50 queued runs; 600 KB HTTP request bodies, except run submissions/internal results (6 MB). Prompt/context growth contributes to cost across turns.

Internal `/internal/runs/{id}/...` routes are reserved for the runtime and require a separate run-scoped token. They are not a public client integration surface.


## Tool registry

All routes below require the administration key. The current workspace has one trusted administrator; deployment-scoped authorization remains future work.

| Method | Path | Behavior |
|---|---|---|
| GET | `/v1/tools` | Versions, manifests, hashes, publication and latest test status |
| POST | `/v1/tools/import` | Validate/register an immutable draft from a package envelope |
| POST | `/v1/tools/reload` | Transactionally register packages from the bundled directory |
| GET | `/v1/tools/{id}/{version}/export` | Download a JSON package envelope |
| POST | `/v1/tools/{id}/{version}/test` | Submit a key-free sandbox fixture run (202) |
| POST | `/v1/tools/{id}/{version}/publish` | Publish after a successful matching test run |

A package envelope contains `manifest`, `handler`, and `tests`. See [Tool Package v1](tools.md) for the complete contract. Conflicting contents at an existing ID/version return 409. Malformed packages and unresolved/draft tool references return 422. Test calls return the same run links as normal invocation, so status, streaming, and cancellation work identically.

Run invocation also accepts optional `additional_tools: [{"id":"summarize-csv","version":"1.0.0"}]` and `disabled_tools: ["python"]`. Disabled entries refer to inherited tool IDs. Duplicate IDs/names are rejected. These selections are included in idempotency checks. Run detail includes `resolved_tools` with IDs, versions, model-facing names, and package hashes. Legacy builtin string names are still accepted in agent configurations for compatibility, but responses use explicit references.

### Delete a tool version

`DELETE /v1/tools/{tool_id}/{version}` requires administration bearer authentication and returns `{ "status": "deleted", "tool_id": "...", "version": "..." }`. Only imported versions without agent-default references can be deleted (409 otherwise). Deleted or missing versions return 404. Existing run snapshots remain intact, and deleted version numbers cannot be reused. See [tool deletion](tools.md#delete-a-version) for the UI and CLI workflow.

## Files and archives

Run submission accepts `files: [{"name": "data.csv", "content_base64": "..."}]`: at most 8 files, 1 MiB each, 4 MiB decoded total. Files are isolated to their run and expire on every terminal state. Run detail includes metadata in `files`; `download_url` becomes null at expiry. `GET /v1/runs/{id}/files/{index}` requires admin auth and returns 410 after the run ends.

Supported archive uploads automatically select/invoke the archive tool. `GET /v1/runs/{id}/artifacts.zip` downloads all outputs as ZIP; run detail advertises `artifacts_archive_url` when there is more than one output. Individual outputs retain the existing artifact endpoint. See [files, complete examples, limits, and GUI/API parity](files.md).

## Queue and schedules

`GET /v1/queue` reports queue counts/capacity. `GET` and `POST /v1/schedules` list/create one-time or fixed-interval schedules; `PATCH /v1/schedules/{id}` pauses/resumes and `DELETE` removes future scheduling while preserving runs. All require administration authentication. Run responses include nullable `schedule_id` and `scheduled_for`. See [the complete scheduling contract and runnable example](scheduling.md).

## Suggested agent tasks

Agent creation/update accepts optional `example_task` (up to 8,000 characters, default empty). Agent responses expose it in `config`. It is a playground/schedule-form suggestion, not automatically executed; run requests still require `input`. Bundled OpenRouter workflows and live verification are documented in [examples](examples.md).

`max_output_tokens` controls the maximum output allowance per model call (256–16,384; default 2,048). It is saved in agent/run/schedule snapshots and configurable in the GUI. Legacy snapshots without the field retain the 2,048-token limit. Model-completed events include the provider’s `finish_reason` when supplied to help diagnose truncated or empty responses.
