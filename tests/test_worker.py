"""Exercise coordinator admission and failure behavior with real execution threads."""

from concurrent.futures import Future
from threading import Event, Lock, Thread

import pytest

from agentberth import worker
from agentberth.backends import CleanupError
from agentberth.settings import positive_integer


@pytest.mark.parametrize("limit", [1, 3, 6])
def test_concurrency_limit_and_queue_drain(monkeypatch, limit):
    monkeypatch.setattr(worker, "stopping", False)
    release = Event()
    saturated = Event()
    mutex = Lock()
    pending = list(range(limit + 2))
    completed = []
    executing = set()
    peak = 0
    errors = []

    def claim(*_):
        with mutex:
            return pending.pop(0) if pending else None

    def execute(row, token):
        nonlocal peak
        with mutex:
            executing.add(row)
            peak = max(peak, len(executing))
            if len(executing) == limit:
                saturated.set()
        assert release.wait(5)
        with mutex:
            executing.remove(row)
            completed.append(row)

    def heartbeat(_):
        with mutex:
            if len(completed) == limit + 2:
                worker.stop()

    monkeypatch.setattr(worker, "claim", claim)
    monkeypatch.setattr(worker, "execute_new", execute)
    monkeypatch.setattr(worker, "heartbeat", heartbeat)

    def run():
        try:
            worker.run_queue("test", None, limit)
        except Exception as exc:
            errors.append(exc)

    thread = Thread(target=run)
    thread.start()
    try:
        assert saturated.wait(5)
        with mutex:
            assert len(pending) == 2
            assert len(executing) == limit
    finally:
        release.set()
        thread.join(8)
        if thread.is_alive():
            worker.stop()
            thread.join(2)
    assert not thread.is_alive()
    assert not errors
    assert peak == limit
    assert sorted(completed) == list(range(limit + 2))


def test_cleanup_failure_is_not_a_free_slot():
    failure = Future()
    failure.set_exception(CleanupError("Unconfirmed cleanup"))
    with pytest.raises(CleanupError):
        worker.reap({failure})


def test_coordinator_failure_stops_active_executions(monkeypatch):
    monkeypatch.setattr(worker, "stopping", False)
    started = Event()
    stopped = Event()

    def execute(*_):
        started.set()
        while not worker.stopping:
            stopped.wait(0.01)
        stopped.set()

    def heartbeat(_):
        if started.is_set():
            raise RuntimeError("Lost coordinator connection")

    monkeypatch.setattr(worker, "execute_new", execute)
    monkeypatch.setattr(worker, "claim", lambda *_: {"id": "test"})
    monkeypatch.setattr(worker, "heartbeat", heartbeat)
    with pytest.raises(RuntimeError, match="Lost coordinator"):
        worker.run_queue("test", None, 1)
    assert stopped.is_set()


@pytest.mark.parametrize("value", ["0", "-1", "3.5", "invalid"])
def test_invalid_limits_fail_explicitly(monkeypatch, value):
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", value)
    with pytest.raises(ValueError, match="positive integer"):
        positive_integer("MAX_CONCURRENT_RUNS", 3)
