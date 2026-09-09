import hashlib
import logging
import secrets
import signal
import time
from pathlib import Path

from agentberth import db
from agentberth.backends import RunSpec, BackendError, CleanupError, create_backend

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
stopping = False


def stop(*_):
    global stopping
    stopping = True


def heartbeat(lock):
    # Use the same connection that owns the lock; if it fails, stop scheduling.
    lock.execute("INSERT INTO worker_status VALUES (1,now()) ON CONFLICT (id) DO UPDATE SET heartbeat=now()")
    Path("/tmp/agentberth-worker-heartbeat").write_text(str(time.time()))


def execute(backend, row, token, lock):
    handle = None
    status, error = "failed", "Worker could not start the sandbox."
    start = time.monotonic()
    try:
        handle = backend.submit(RunSpec(row["id"], token, row["spec"]["timeout_seconds"]))
        logging.info("Started sandbox for run %s", row["id"])
        while True:
            heartbeat(lock)
            with db.connect() as conn:
                current = conn.execute("SELECT * FROM runs WHERE id=%s", (row["id"],)).fetchone()
            if stopping:
                error = "Worker stopped during execution. Run was not retried."
                break
            if current["cancel_requested"]:
                status, error = "cancelled", None
                break
            if time.monotonic() - start > row["spec"]["timeout_seconds"]:
                status, error = "timed_out", "Run exceeded its wall-clock limit."
                break
            running, code = backend.status(handle)
            if not running:
                # The result may have committed after the previous status read.
                with db.connect() as conn:
                    current = conn.execute("SELECT output FROM runs WHERE id=%s", (row["id"],)).fetchone()
                if code == 0 and current["output"] is not None:
                    status, error = "completed", None
                elif code == 124:
                    status, error = "timed_out", "Run exceeded its Kubernetes deadline."
                else:
                    error = f"Sandbox exited with code {code}. Inspect the last run event for context."
                break
            time.sleep(0.5)
    except CleanupError:
        raise
    except Exception as exc:
        # Do not log Docker environment payloads or credentials.
        logging.error("Run %s: %s", row["id"], type(exc).__name__)
        error = (
            str(exc)
            if isinstance(exc, BackendError)
            else "Execution infrastructure failed. This run was not retried."
        )
    finally:
        # Revoke credentials and uploads even if infrastructure cleanup must be retried on restart.
        with db.connect() as conn:
            conn.execute("UPDATE runs SET token_hash=NULL,spec=spec-'files' WHERE id=%s", (row["id"],))
        if handle:
            # Do not claim completion if teardown cannot be confirmed.
            backend.cleanup(handle)
        with db.connect() as conn:
            current = conn.execute(
                "SELECT cancel_requested FROM runs WHERE id=%s FOR UPDATE", (row["id"],)
            ).fetchone()
            if current["cancel_requested"]:
                status, error = "cancelled", None
            db.finish(conn, row["id"], status, error)


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    backend = create_backend()
    # Kubernetes does not have Compose depends_on; wait for API schema initialization.
    deadline = time.monotonic() + 180
    while True:
        try:
            with db.connect() as conn:
                conn.execute("SELECT id FROM worker_status LIMIT 1")
            break
        except Exception:
            if time.monotonic() > deadline:
                raise RuntimeError("Database/schema unavailable after startup wait.") from None
            time.sleep(2)
    with db.connect() as lock:
        lock.autocommit = True
        if not lock.execute("SELECT pg_try_advisory_lock(71002) AS acquired").fetchone()["acquired"]:
            raise RuntimeError("This release supports one worker. Another worker owns the queue.")
        backend.cleanup_orphans()
        with db.connect() as conn:
            for row in conn.execute("SELECT id FROM runs WHERE status='running' FOR UPDATE").fetchall():
                db.finish(
                    conn, row["id"], "failed", "Worker restarted during execution. Run was not retried."
                )
        logging.info("%s worker ready", backend.name)
        while not stopping:
            heartbeat(lock)
            token = secrets.token_urlsafe(32)
            with db.connect() as conn:
                row = conn.execute(
                    "SELECT * FROM runs WHERE status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"
                ).fetchone()
                if row:
                    conn.execute(
                        "UPDATE runs SET status='running',started_at=now(),token_hash=%s WHERE id=%s",
                        (hashlib.sha256(token.encode()).hexdigest(), row["id"]),
                    )
                    db.event(conn, row["id"], "run.started", {"backend": backend.name, "memory_mb": 256})
            if row:
                execute(backend, row, token, lock)
            else:
                time.sleep(0.5)


if __name__ == "__main__":
    main()
