from fastapi.testclient import TestClient

from agentberth.api import app


def test_unauthenticated_requests_are_rejected_before_database_access():
    client = TestClient(app)
    assert client.get("/v1/agents").status_code == 401
    assert client.get("/v1/runs/example/files/0").status_code == 401
    assert client.get("/v1/runs/example/artifacts/example").status_code == 401
    assert client.delete("/v1/tools/example/1.0.0").status_code == 401
    assert client.post("/v1/deployments/harbor-guide/runs", json={"input": "hello"}).status_code == 401


def test_oversized_request_is_rejected_before_json_parsing():
    client = TestClient(app)
    assert client.post("/v1/agents", content=b"x" * 600001).status_code == 413


def test_public_schema_has_bearer_auth_and_excludes_internal_routes():
    schema = app.openapi()
    assert schema["paths"]["/v1/agents"]["get"]["security"] == [{"HTTPBearer": []}]
    assert not any(path.startswith("/internal/") for path in schema["paths"])
    assert "token_hash" not in schema["components"]["schemas"]["RunDetail"]["properties"]
    assert "LLM_API_KEY" not in str(schema)


def test_malformed_tool_selection_returns_validation_error():
    from agentberth.api import ADMIN_KEY

    response = TestClient(app).post(
        "/v1/agents",
        headers={"Authorization": "Bearer " + ADMIN_KEY},
        json={"slug": "invalid-tools", "name": "Example", "instructions": "Help.", "tools": None},
    )
    assert response.status_code == 422
