"""Materialize due schedules transactionally; execution remains the worker's responsibility."""

from datetime import timedelta

from psycopg.types.json import Jsonb

from agentberth import db
from agentberth.settings import MAX_QUEUED_RUNS


def next_occurrence(due, interval_seconds, now):
    """Keep the original cadence, coalescing missed ticks into at most one run."""
    if interval_seconds is None:
        return None
    elapsed = max(0, (now - due).total_seconds())
    return due + timedelta(seconds=(int(elapsed // interval_seconds) + 1) * interval_seconds)


def tick():
    with db.connect() as conn:
        # Shared with every API producer so the global queue bound is atomic.
        conn.execute("SELECT pg_advisory_xact_lock(71004)")
        now = conn.execute("SELECT now() AS value").fetchone()["value"]
        slots = (
            MAX_QUEUED_RUNS
            - conn.execute("SELECT count(*) AS n FROM runs WHERE status='queued'").fetchone()["n"]
        )
        due = conn.execute(
            "SELECT * FROM schedules WHERE enabled AND next_run_at <= %s ORDER BY next_run_at,id FOR UPDATE",
            (now,),
        ).fetchall()
        for schedule in due:
            active = conn.execute(
                "SELECT 1 FROM runs WHERE schedule_id=%s AND status IN ('queued','running') LIMIT 1",
                (schedule["id"],),
            ).fetchone()
            upcoming = next_occurrence(schedule["next_run_at"], schedule["interval_seconds"], now)
            if active:
                # No overlap: skip ticks while this schedule already has pending work.
                conn.execute("UPDATE schedules SET next_run_at=%s WHERE id=%s", (upcoming, schedule["id"]))
                continue
            if slots <= 0:
                break  # Retain the due time and retry after capacity becomes available.
            run_id = db.new_id()
            conn.execute(
                "INSERT INTO runs(id,agent_slug,version,spec,input,schedule_id,scheduled_for) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    run_id,
                    schedule["agent_slug"],
                    schedule["version"],
                    Jsonb(schedule["spec"]),
                    schedule["input"],
                    schedule["id"],
                    schedule["next_run_at"],
                ),
            )
            db.event(
                conn,
                run_id,
                "run.queued",
                {
                    "schedule_id": schedule["id"],
                    "scheduled_for": schedule["next_run_at"].isoformat(),
                    "version": schedule["version"],
                    "provider": schedule["spec"]["provider"],
                },
            )
            conn.execute(
                "UPDATE schedules SET next_run_at=%s,last_run_id=%s,enabled=%s WHERE id=%s",
                (upcoming, run_id, upcoming is not None, schedule["id"]),
            )
            slots -= 1
