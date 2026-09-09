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
  "tools": ["python", "write_file", "read_file"],
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
| GET | `/v1/runs/{id}/artifacts/{artifact_id}` | Download a UTF-8 text attachment |

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

Limits: 8,000 input characters; 1–12 model calls; 2,048 completion tokens per call including any provider reasoning; 10–300 seconds per run; up to 8 tool calls per model turn; 10 seconds per Python tool; 50 queued runs; 600 KB HTTP request bodies. Prompt/context growth contributes to cost across turns.

Internal `/internal/runs/{id}/...` routes are reserved for the runtime and require a separate run-scoped token. They are not a public client integration surface.
