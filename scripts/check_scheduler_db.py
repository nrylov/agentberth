"""Database integration checks in an isolated temporary schema.

Run with: docker compose exec -T api python < scripts/check_scheduler_db.py
Requires the platform's DATABASE_URL; never uses or modifies application tables.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
import unittest
import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from agentberth import db, scheduler
from agentberth.api import create_schedule, set_schedule_state, delete_schedule, submit
from agentberth.schemas import ScheduleInput, ScheduleState, RunInput
from fastapi import HTTPException

schema = "scheduler_test_" + uuid.uuid4().hex
original_connect = db.connect


def isolated_connect():
    return psycopg.connect(
        os.environ["DATABASE_URL"], options=f"-csearch_path={schema}", row_factory=dict_row
    )


class SchedulerDatabaseTests(unittest.TestCase):
    def setUp(self):
        with db.connect() as conn:
            conn.execute("TRUNCATE schedules,runs CASCADE")
            conn.execute(
                "INSERT INTO agents(slug,name,config) VALUES ('schedule-test','Test',%s) "
                "ON CONFLICT (slug) DO UPDATE SET version=1,config=EXCLUDED.config",
                (
                    Jsonb(
                        {
                            "provider": "demo",
                            "model": "",
                            "tools": [],
                            "max_steps": 1,
                            "timeout_seconds": 30,
                            "instructions": "Help",
                            "name": "Test",
                        }
                    ),
                ),
            )

    def create(self, interval=60):
        return create_schedule(
            ScheduleInput(
                name="Test",
                agent_slug="schedule-test",
                input="Hello",
                start_at=datetime.now(timezone.utc) - timedelta(seconds=185),
                interval_seconds=interval,
            )
        )

    def rows(self):
        with db.connect() as conn:
            return conn.execute("SELECT * FROM runs ORDER BY created_at,id").fetchall()

    def test_concurrent_ticks_create_one_occurrence_and_keep_cadence(self):
        schedule = self.create()
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: scheduler.tick(), range(4)))
        self.assertEqual(len(self.rows()), 1)
        with db.connect() as conn:
            current = conn.execute("SELECT * FROM schedules").fetchone()
        self.assertEqual(current["next_run_at"], schedule["next_run_at"] + timedelta(seconds=240))
        self.assertEqual(self.rows()[0]["scheduled_for"], schedule["next_run_at"])

    def test_no_overlap_then_next_due_occurrence_runs(self):
        self.create()
        scheduler.tick()
        with db.connect() as conn:
            conn.execute("UPDATE schedules SET next_run_at=now()-interval '1 second'")
        scheduler.tick()
        self.assertEqual(len(self.rows()), 1)
        with db.connect() as conn:
            db.finish(conn, self.rows()[0]["id"], "completed")
            conn.execute("UPDATE schedules SET next_run_at=now()-interval '1 second'")
        scheduler.tick()
        self.assertEqual(len(self.rows()), 2)

    def test_pause_resume_and_delete_preserve_runs(self):
        s = self.create()
        set_schedule_state(s["id"], ScheduleState(enabled=False))
        scheduler.tick()
        self.assertEqual(self.rows(), [])
        set_schedule_state(s["id"], ScheduleState(enabled=True))
        scheduler.tick()
        delete_schedule(s["id"])
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["schedule_id"], s["id"])

    def test_one_time_schedule_does_not_repeat(self):
        self.create(None)
        scheduler.tick()
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM schedules").fetchone()
            self.assertIsNone(row["next_run_at"])
            self.assertFalse(row["enabled"])
            db.finish(conn, self.rows()[0]["id"], "completed")
        scheduler.tick()
        self.assertEqual(len(self.rows()), 1)

    def test_full_queue_defers_schedule_and_idempotency_still_works(self):
        first = submit("schedule-test", RunInput(input="Hello"), "replay")
        for _ in range(49):
            submit("schedule-test", RunInput(input="Hello"), None)
        s = self.create()
        scheduler.tick()
        self.assertEqual(len(self.rows()), 50)
        self.assertEqual(submit("schedule-test", RunInput(input="Hello"), "replay"), first)
        with self.assertRaises(HTTPException) as ctx:
            submit("schedule-test", RunInput(input="Hello"), None)
        self.assertEqual(ctx.exception.status_code, 429)
        with db.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT next_run_at FROM schedules").fetchone()["next_run_at"], s["next_run_at"]
            )
            db.finish(conn, first["id"], "cancelled")
        scheduler.tick()
        self.assertEqual(len([r for r in self.rows() if r["status"] == "queued"]), 50)
        self.assertEqual(len([r for r in self.rows() if r["schedule_id"]]), 1)

    def test_agent_edits_do_not_change_schedule_snapshot(self):
        self.create()
        with db.connect() as conn:
            conn.execute(
                "UPDATE agents SET version=version+1,config=jsonb_set(config,'{instructions}', '\"Changed\"') "
                "WHERE slug='schedule-test'"
            )
        scheduler.tick()
        self.assertEqual(self.rows()[0]["spec"]["instructions"], "Help")
        self.assertEqual(self.rows()[0]["version"], 1)

    def test_failed_transaction_rolls_back_run_and_due_time(self):
        s = self.create()
        original_event = db.event

        def fail(*args):
            raise RuntimeError("Simulated crash before commit")

        db.event = fail
        try:
            with self.assertRaises(RuntimeError):
                scheduler.tick()
        finally:
            db.event = original_event
        self.assertEqual(self.rows(), [])
        with db.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT next_run_at FROM schedules").fetchone()["next_run_at"], s["next_run_at"]
            )
        scheduler.tick()
        self.assertEqual(len(self.rows()), 1)


if __name__ == "__main__":
    try:
        with original_connect() as conn:
            conn.execute(f"CREATE SCHEMA {schema}")
        db.connect = isolated_connect
        db.initialize()
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(SchedulerDatabaseTests)
        )
    finally:
        db.connect = original_connect
        with original_connect() as conn:
            conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    raise SystemExit(0 if result.wasSuccessful() else 1)
