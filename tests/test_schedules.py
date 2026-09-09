from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentberth.api import app
from agentberth.scheduler import next_occurrence
from agentberth.schemas import ScheduleInput


def test_cadence_skips_missed_intervals_without_drift():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert next_occurrence(start, 60, start + timedelta(seconds=185)) == start + timedelta(seconds=240)
    assert next_occurrence(start, 60, start + timedelta(seconds=60)) == start + timedelta(seconds=120)
    assert next_occurrence(start, None, start) is None


@pytest.mark.parametrize(
    "override",
    [
        {"start_at": "2026-01-01T10:00:00"},
        {"interval_seconds": 1},
        {"files": []},
        {"interval_seconds": 31536001},
    ],
)
def test_schedule_rejects_ambiguous_time_files_and_unbounded_cadence(override):
    with pytest.raises(ValidationError):
        ScheduleInput(
            **{
                "name": "Report",
                "agent_slug": "harbor-guide",
                "input": "Report",
                "start_at": "2026-01-01T10:00:00Z",
                **override,
            }
        )


def test_schedule_and_queue_routes_require_authentication():
    client = TestClient(app)
    for method, path in [
        ("GET", "/v1/queue"),
        ("GET", "/v1/schedules"),
        ("POST", "/v1/schedules"),
        ("PATCH", "/v1/schedules/example"),
        ("DELETE", "/v1/schedules/example"),
    ]:
        assert client.request(method, path).status_code == 401


def test_schedule_schema_does_not_expose_executable_snapshot():
    schema = app.openapi()["components"]["schemas"]
    assert "spec" not in schema["ScheduleRecord"]["properties"]
    assert "files" not in schema["ScheduleInput"]["properties"]
