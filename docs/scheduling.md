# Queueing and scheduled tasks

Agentberth stores its queue and schedules in PostgreSQL. The same API, GUI, and worker implement scheduling for Docker and Kubernetes; no Redis, external cron service, or Kubernetes CronJob is required. Each installation has its own independent schedules and run history.

## Queue behavior

Every `POST /v1/deployments/{slug}/runs` already queues a task and returns HTTP 202. Submit several requests without waiting for completion to queue a batch. One coordinator starts up to `MAX_CONCURRENT_RUNS` isolated sandboxes concurrently (default 3), taking the oldest queued task whenever a slot becomes available. Completion order can differ from submission order. Queued tasks survive API and worker restarts. Up to `MAX_QUEUED_RUNS` tasks can wait (default 50); additional submissions return HTTP 429. Running work does not count toward the waiting queue limit. An idempotent replay still returns the original run when the queue is full.

The **Schedules** menu opens the queue and scheduling page, which shows queue counts, pending tasks, and cancellation controls. Run history and the playground retain their existing run details, events, input-file handling, and output downloads. The pending list uses the latest 100 runs; queue counts cover all runs. Cancel via the GUI or `POST /v1/runs/{id}/cancel`. Queued cancellation prevents execution and expires uploads; running cancellation asks the worker to stop the sandbox.

This release does not provide priorities, multiple workers, automatic retries, or an exactly-once guarantee for tool side effects. A task interrupted by a worker restart is marked failed and is not retried.

## Create a schedule in the GUI

1. Open **Schedules**.
2. Choose a name, agent, task prompt, and optional tool overrides.
3. Choose the first run in your local timezone, or leave it blank to start now.
4. Choose **Once**, or a fixed interval in seconds (minimum 60; maximum 31,536,000).
5. Select **Create schedule**. Use **Latest run** to inspect its output and download artifacts.
6. Use **Pause**, **Resume**, or **Delete** to control future submissions.

Schedules save an immutable copy of the agent version, resolved model name, and executable tool packages when created. Subsequent agent edits or tool deletion do not change that copy. To change the prompt, timing, agent, or tools, pause/delete the old schedule and create a replacement. The API provider credential is still supplied by the deployment and is never copied into a schedule or sandbox.

Schedules accept prompts and tool overrides, **not uploaded files**. Input uploads remain exclusive to an individual run and expire when it finishes. Send file-bearing tasks through the ordinary run endpoint. Output files from scheduled tasks use the same artifact and ZIP download endpoints as other tasks.

## Timing, downtime, and overlap

- Schedules are evaluated approximately once a second by the active worker, including while another run executes. Sandbox startup/cleanup and infrastructure delays can postpone evaluation. A due time is a queue submission time, not a guaranteed execution time.
- Times are stored as timezone-aware timestamps. API timestamps must include `Z` or a numeric offset; GUI inputs are converted from local time. Repetition is an elapsed duration, not a calendar/cron expression: every 86,400 seconds does not preserve a local wall-clock time across daylight-saving changes.
- The cadence stays anchored to the first run. Following downtime or pause, missed intervals produce at most one catch-up task, and the next due time advances to the next future slot. There is no burst of backfilled tasks.
- If a schedule already has a queued or running task, its due occurrence is skipped. Different schedules can queue independently.
- When the queue is full, the due schedule waits for capacity; it is not discarded. Missed intervals are still combined when it is eventually submitted.
- Run creation, the queued event, and advancement of the schedule commit in one database transaction. A uniqueness constraint protects each schedule/time pair from duplicate materialization.
- Pause/delete does not cancel a run already submitted. Cancel that run separately. Deleting a schedule retains its run history and outputs, including the original `schedule_id` and `scheduled_for` fields.
- One-time schedules become finished after submission. Their task can still be queued, running, or failed: inspect **Latest run** for the outcome. A finished one-time schedule cannot be rerun by resuming it; create another schedule.
- At most 100 schedule records are supported, including paused/finished entries. Delete unused schedules to free space.
- Schedules require a running worker. Closing the browser or port-forward does not stop schedules in a running deployment. Repeating OpenRouter tasks consume credits; pause them when no longer needed.

## API examples

Run from the repository root. Docker defaults are shown; for the test cluster, use `http://127.0.0.1:8081` and its admin key. Keep credentials out of Git.

```bash
export AGENTBERTH_BASE_URL=http://127.0.0.1:8080
export AGENTBERTH_ADMIN_KEY=agentberth-local

# Inspect the queue.
curl -fsS "$AGENTBERTH_BASE_URL/v1/queue" \
  -H "Authorization: Bearer $AGENTBERTH_ADMIN_KEY"

# Queue three independent tasks immediately.
for task in first second third; do
  curl -fsS "$AGENTBERTH_BASE_URL/v1/deployments/harbor-guide/runs" \
    -H "Authorization: Bearer $AGENTBERTH_ADMIN_KEY" \
    -H 'Content-Type: application/json' \
    -d "{\"input\":\"Create the $task demonstration report.\"}"
done
```

Create a report schedule with an explicit first time. Replace `start_at` with your desired timestamp; a past value intentionally starts one catch-up run.

```bash
curl -fsS "$AGENTBERTH_BASE_URL/v1/schedules" \
  -H "Authorization: Bearer $AGENTBERTH_ADMIN_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Hourly report",
    "agent_slug": "harbor-guide",
    "input": "Calculate the total and average of 12, 18, and 24. Save report.md.",
    "start_at": "2026-09-09T18:00:00Z",
    "interval_seconds": 3600,
    "additional_tools": [],
    "disabled_tools": []
  }'
```

Omit `interval_seconds` or set it to `null` for a one-time scheduled task. All routes below require the same bearer header:

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/v1/queue` | Total queued/running counts and capacity |
| GET | `/v1/schedules` | List schedules, next due time, and latest run |
| POST | `/v1/schedules` | Create an immutable task schedule |
| PATCH | `/v1/schedules/{id}` | Pause with `{"enabled":false}`; resume with `{"enabled":true}` |
| DELETE | `/v1/schedules/{id}` | Delete future scheduling; retain runs |
| GET | `/v1/runs` | Latest 100 runs, including schedule identifiers/times |
| GET | `/v1/runs/{id}` | Status, output, inputs, resolved tools, and artifact metadata |
| POST | `/v1/runs/{id}/cancel` | Cancel a queued/running task |

For example, after copying the schedule ID from the response:

```bash
SCHEDULE_ID=replace-with-returned-id
curl -fsS -X PATCH "$AGENTBERTH_BASE_URL/v1/schedules/$SCHEDULE_ID" \
  -H "Authorization: Bearer $AGENTBERTH_ADMIN_KEY" \
  -H 'Content-Type: application/json' -d '{"enabled":false}'
```

Use `last_run_id` to fetch `/v1/runs/{id}` and then download `/v1/runs/{id}/artifacts/{artifact_id}` or `/v1/runs/{id}/artifacts.zip` when multiple output files exist. See [files and archives](files.md) for complete download examples and the generated `/openapi.json` for request/response schemas.

## Runnable example: a report every minute

```bash
python3 scripts/example_schedules.py
```

For the DigitalOcean deployment (keep port-forwarding running):

```bash
python3 scripts/example_schedules.py \
  --base-url http://127.0.0.1:8081 \
  --admin-key-file work/kubernetes-admin-key \
  --output-dir work/scheduled-example-kubernetes
```

The script creates a clearly named demo agent and schedule, waits for two distinct scheduled runs, verifies both reports contain the expected total **54** and average **18**, and downloads the reports. It pauses the schedule in a `finally` block, including on ordinary errors/interruption. Inspect the paused example in the GUI and resume it when desired. Abrupt process termination can prevent cleanup; the schedule remains visible and can be paused manually. `--cleanup` deletes the schedule after validation; agent/run records and downloaded files remain for inspection.

The demo runs real isolated tools but uses a deterministic provider, so it needs no model key and consumes no LLM credits. To schedule a real AI task, select an agent configured with OpenRouter in the GUI or use that agent's slug in the API request.

## Verification and upgrades

```bash
uv run pytest
# Isolated PostgreSQL schema; no application rows changed.
docker compose exec -T api python < scripts/check_scheduler_db.py
python3 scripts/example_schedules.py --cleanup
```

Database integration checks cover concurrent ticks, transaction rollback, cadence, overlap, queue capacity/idempotent replay, pause/resume/delete, one-time schedules, and pinned configuration. CI runs these checks and the end-to-end example; Kubernetes CI runs the public example too.

Rebuild with `docker compose up -d --build`, or deploy a new platform image through the [Kubernetes guide](kubernetes.md). No runtime-image or Helm value change is required for scheduling. API startup adds the schedule table and run metadata columns; the worker waits for the new schema. Back up PostgreSQL before upgrades. A rollback to an older worker leaves schedules stored but stops evaluating them.

## Configuring concurrency

The concurrency limit is configurable, not fixed at three. Docker and Kubernetes use the same coordinator and queue semantics. Each active run gets its own container or Kubernetes Job/pod; each slot is released only after sandbox teardown and terminal-state persistence. Pods awaiting scheduling or image pulls also occupy slots. Additional tasks remain in PostgreSQL until a slot is available.

For Docker Compose, set these values in `.env`:

```dotenv
MAX_CONCURRENT_RUNS=6
MAX_QUEUED_RUNS=50
```

Apply with `docker compose up -d`. Both the API and worker receive the same settings. For Kubernetes, add these values to your Helm overrides and apply your normal Helm upgrade:

```yaml
execution:
  maxConcurrentRuns: 6
  maxQueuedRuns: 50
```

Both settings must be positive integers. Raising concurrency increases resource demand: each sandbox has a 256 MiB memory limit, in addition to the platform and database. Kubernetes can leave pods pending when resources are unavailable. This setting does not add cluster nodes or worker replicas. Keep the worker Deployment at one replica.

Settings take effect after the API and worker restart. Wait for active work to finish before changing them: a worker shutdown stops its active sandboxes and marks those runs failed without retrying; queued runs are retained. Reducing the queue limit preserves existing queued work and prevents new admissions until the backlog falls below the new limit.

`GET /v1/queue` returns `queued`, `running`, `capacity` (waiting queue limit), and `max_concurrent_runs`. The Queue & schedules page displays both limits. The playground allows **Run another task** while the current task is active; it switches to the new run, and earlier runs remain available in Run history. Example response:

```json
{"queued": 2, "running": 3, "capacity": 50, "max_concurrent_runs": 3}
```

## Concurrent report example

On an idle development installation with schedules paused, run:

```bash
python3 scripts/example_concurrency.py
```

For another installation, use `--base-url` and set `AGENTBERTH_ADMIN_KEY` in your shell. The script submits two more tasks than the configured concurrency limit (five at the default), prints running/queued counts, verifies the concurrency ceiling and overlapping runs using persisted timestamps, and downloads every report to verify its run-specific contents. It uses the demo provider and spends no LLM credits. Short tasks may finish between queue polls; persisted timestamps provide the final overlap check. The example agent and run history remain available in the GUI.
