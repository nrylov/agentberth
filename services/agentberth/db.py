import os
import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

TERMINAL = {"completed", "failed", "cancelled", "timed_out"}


def connect():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


def event(conn, run_id, kind, data):
    conn.execute(
        "INSERT INTO events(run_id, kind, data) VALUES (%s,%s,%s)",
        (run_id, kind, Jsonb(data)),
    )


def finish(conn, run_id, status, error=None):
    row = conn.execute(
        "UPDATE runs SET status=%s,error=%s,finished_at=now(),token_hash=NULL,spec=spec-'files' "
        "WHERE id=%s AND status NOT IN ('completed','failed','cancelled','timed_out') RETURNING id",
        (status, error, run_id),
    ).fetchone()
    if row:
        event(conn, run_id, "run." + status, {"status": status, "error": error})


def initialize():
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(71001)")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            slug text PRIMARY KEY, name text NOT NULL, version integer NOT NULL DEFAULT 1,
            config jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS runs (
            id text PRIMARY KEY, agent_slug text NOT NULL REFERENCES agents(slug),
            version integer NOT NULL, spec jsonb NOT NULL, input text NOT NULL,
            status text NOT NULL DEFAULT 'queued', output text, error text,
            created_at timestamptz NOT NULL DEFAULT now(), started_at timestamptz, finished_at timestamptz,
            cancel_requested boolean NOT NULL DEFAULT false, token_hash text,
            model_calls integer NOT NULL DEFAULT 0, prompt_tokens bigint NOT NULL DEFAULT 0,
            completion_tokens bigint NOT NULL DEFAULT 0, cost numeric NOT NULL DEFAULT 0,
            idempotency_key text, request_hash text,
            UNIQUE(agent_slug, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS events (
            id bigserial PRIMARY KEY, run_id text NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            kind text NOT NULL, data jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS events_run_idx ON events(run_id,id);
        CREATE INDEX IF NOT EXISTS runs_queue_idx ON runs(created_at) WHERE status='queued';
        CREATE TABLE IF NOT EXISTS artifacts (
            id text PRIMARY KEY, run_id text NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            name text NOT NULL, content text NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tool_versions (
            tool_id text NOT NULL, version text NOT NULL, name text NOT NULL,
            package jsonb NOT NULL, sha256 text NOT NULL, status text NOT NULL,
            origin text NOT NULL, test_run_id text REFERENCES runs(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(tool_id,version)
        );
        CREATE TABLE IF NOT EXISTS worker_status (
            id integer PRIMARY KEY, heartbeat timestamptz NOT NULL
        );
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS schedules (
            id text PRIMARY KEY, name text NOT NULL,
            agent_slug text NOT NULL REFERENCES agents(slug), version integer NOT NULL,
            spec jsonb NOT NULL, input text NOT NULL, interval_seconds integer,
            next_run_at timestamptz, enabled boolean NOT NULL DEFAULT true,
            last_run_id text REFERENCES runs(id), created_at timestamptz NOT NULL DEFAULT now()
        );
        ALTER TABLE runs ADD COLUMN IF NOT EXISTS schedule_id text;
        ALTER TABLE runs ADD COLUMN IF NOT EXISTS scheduled_for timestamptz;
        CREATE UNIQUE INDEX IF NOT EXISTS runs_schedule_occurrence_idx
            ON runs(schedule_id,scheduled_for) WHERE schedule_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS schedules_due_idx ON schedules(next_run_at) WHERE enabled;
        """)
        conn.execute("ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS data bytea")
        # Remove any terminal staging payloads left by older platform builds.
        conn.execute(
            "UPDATE runs SET spec=spec-'files' WHERE status IN ('completed','failed','cancelled','timed_out') AND spec ? 'files'"
        )
        from agentberth import registry

        registry.bundled(conn)
        # Upgrade legacy agent tool names to explicit immutable builtin references.
        from runtime.packages import reference

        for old in conn.execute("SELECT slug,config FROM agents").fetchall():
            if any(isinstance(ref, str) for ref in old["config"]["tools"]):
                old["config"]["tools"] = [reference(ref) for ref in old["config"]["tools"]]
                conn.execute("UPDATE agents SET config=%s WHERE slug=%s", (Jsonb(old["config"]), old["slug"]))
        for old in conn.execute(
            "SELECT id,spec FROM runs WHERE status='queued' AND NOT spec ? 'tool_packages'"
        ).fetchall():
            old["spec"]["tool_packages"] = registry.resolve(conn, old["spec"]["tools"])
            old["spec"]["tools"] = [p["manifest"]["name"] for p in old["spec"]["tool_packages"]]
            conn.execute("UPDATE runs SET spec=%s WHERE id=%s", (Jsonb(old["spec"]), old["id"]))
        demo = {
            "name": "Harbor guide",
            "instructions": "Help the user. Use tools when useful. "
            "Save requested deliverables to files in the workspace.",
            "provider": "demo",
            "model": "",
            "tools": [reference(n) for n in ["python", "write_file", "read_file"]],
            "max_steps": 6,
            "timeout_seconds": 120,
        }
        conn.execute(
            "INSERT INTO agents(slug,name,config) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
            ("harbor-guide", demo["name"], Jsonb(demo)),
        )


def new_id():
    return str(uuid.uuid4())
