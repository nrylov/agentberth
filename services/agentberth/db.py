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
        "UPDATE runs SET status=%s,error=%s,finished_at=now(),token_hash=NULL "
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
        CREATE TABLE IF NOT EXISTS worker_status (
            id integer PRIMARY KEY, heartbeat timestamptz NOT NULL
        );
        """)
        demo = {
            "name": "Harbor guide",
            "instructions": "Help the user. Use tools when useful. "
            "Save requested deliverables to files in the workspace.",
            "provider": "demo",
            "model": "",
            "tools": ["python", "write_file", "read_file"],
            "max_steps": 6,
            "timeout_seconds": 120,
        }
        conn.execute(
            "INSERT INTO agents(slug,name,config) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
            ("harbor-guide", demo["name"], Jsonb(demo)),
        )


def new_id():
    return str(uuid.uuid4())
