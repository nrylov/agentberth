import asyncio
import io
import zipfile
import hashlib
import hmac
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from agentberth import db
from agentberth.schemas import (
    AgentConfig,
    CreateAgent,
    ModelRequest,
    RunInput,
    RunResult,
    RuntimeEvent,
    AgentRecord,
    RunLinks,
    RunSummary,
    RunDetail,
    WorkspaceSettings,
)
from runtime.packages import definitions
from runtime.files import decode_file
from runtime.archives import is_archive
from agentberth import registry
from jsonschema.exceptions import SchemaError, ValidationError

ADMIN_KEY = os.getenv("ADMIN_KEY", "agentberth-local")
MODEL = os.getenv("LLM_MODEL", "google/gemini-3.8-flash")
BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
PROVIDER_KEY = os.getenv("LLM_API_KEY", "")
RUN_FIELDS = (
    "id,agent_slug,version,input,status,output,error,created_at,started_at,finished_at,"
    "cancel_requested,model_calls,prompt_tokens,completion_tokens,cost"
)


@asynccontextmanager
async def lifespan(app):
    db.initialize()
    yield


app = FastAPI(title="Agentberth API", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.exception_handler(registry.Conflict)
async def registry_conflict(request, exc):
    return Response(json.dumps({"detail": str(exc)}), status_code=409, media_type="application/json")


@app.exception_handler(ValueError)
async def package_value_error(request, exc):
    return Response(json.dumps({"detail": str(exc)[:500]}), status_code=422, media_type="application/json")


@app.exception_handler(SchemaError)
@app.exception_handler(ValidationError)
async def package_schema_error(request, exc):
    return Response(
        json.dumps({"detail": "Package schema or fixture is invalid: " + exc.message[:300]}),
        status_code=422,
        media_type="application/json",
    )


@app.middleware("http")
async def bounds(request: Request, call_next):
    # Bound request bodies before Pydantic/JSON parsing, including chunked requests.
    file_route = request.method == "POST" and (
        re.fullmatch(r"/v1/deployments/[^/]+/runs/?", request.url.path)
        or re.fullmatch(r"/internal/runs/[^/]+/result/?", request.url.path)
    )
    limit = 6_000_000 if file_route else 600_000
    size = 0
    chunks = []
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return Response("Request body too large", status_code=413)
        chunks.append(chunk)
    request._body = b"".join(chunks)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
    )
    if request.url.path.startswith(("/v1/", "/internal/")):
        response.headers["Cache-Control"] = "no-store"
    return response


bearer = HTTPBearer(auto_error=False)


def admin(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if credentials is None or not hmac.compare_digest(credentials.credentials, ADMIN_KEY):
        raise HTTPException(401, "A valid administration API key is required.")


def runtime_run(conn, run_id, authorization, lock=False):
    row = conn.execute(
        "SELECT * FROM runs WHERE id=%s" + (" FOR UPDATE" if lock else ""), (run_id,)
    ).fetchone()
    token = authorization.removeprefix("Bearer ")
    digest = hashlib.sha256(token.encode()).hexdigest()
    if not row or not row["token_hash"] or not hmac.compare_digest(digest, row["token_hash"]):
        raise HTTPException(401, "Invalid or expired run token.")
    if row["status"] != "running" or row["cancel_requested"]:
        raise HTTPException(409, "Run is no longer accepting work.")
    return row


def get_run(conn, run_id):
    row = conn.execute(f"SELECT {RUN_FIELDS} FROM runs WHERE id=%s", (run_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Run not found.")
    return row


@app.get("/healthz")
def health():
    with db.connect() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/v1/settings", response_model=WorkspaceSettings, dependencies=[Depends(admin)])
def settings():
    with db.connect() as conn:
        worker = conn.execute(
            "SELECT heartbeat > now() - interval '15 seconds' AS online FROM worker_status WHERE id=1"
        ).fetchone()
    return {
        "provider": {"base_url": BASE_URL, "model": MODEL, "configured": bool(PROVIDER_KEY)},
        "backend": "docker",
        "worker_online": bool(worker and worker["online"]),
        "auth_mode": "local-admin",
        "demo_key": ADMIN_KEY == "agentberth-local",
    }


@app.get("/v1/agents", response_model=list[AgentRecord], dependencies=[Depends(admin)])
def agents():
    with db.connect() as conn:
        return conn.execute("SELECT * FROM agents ORDER BY updated_at DESC").fetchall()


@app.post("/v1/agents", status_code=201, response_model=AgentRecord, dependencies=[Depends(admin)])
def create_agent(body: CreateAgent):
    config = body.model_dump(exclude={"slug"})
    try:
        with db.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(71003)")
            registry.resolve(conn, config["tools"])
            return conn.execute(
                "INSERT INTO agents(slug,name,config) VALUES (%s,%s,%s) RETURNING *",
                (body.slug, body.name, Jsonb(config)),
            ).fetchone()
    except UniqueViolation:
        raise HTTPException(409, "An agent with this slug already exists.") from None


@app.put("/v1/agents/{slug}", response_model=AgentRecord, dependencies=[Depends(admin)])
def update_agent(slug: str, body: AgentConfig):
    with db.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(71003)")
        registry.resolve(conn, body.model_dump()["tools"])
        row = conn.execute(
            "UPDATE agents SET name=%s,config=%s,version=version+1,updated_at=now() "
            "WHERE slug=%s RETURNING *",
            (body.name, Jsonb(body.model_dump()), slug),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Agent not found.")
        return row


@app.post(
    "/v1/deployments/{slug}/runs", status_code=202, response_model=RunLinks, dependencies=[Depends(admin)]
)
def submit(slug: str, body: RunInput, idempotency_key: str | None = Header(default=None, max_length=150)):
    # Preserve idempotency for pre-registry calls with no overrides.
    hash_input = (
        body.input
        if not body.additional_tools and not body.disabled_tools and not body.files
        else json.dumps(
            body.model_dump(exclude={"files"} if not body.files else set()),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    request_hash = hashlib.sha256(hash_input.encode()).hexdigest()
    with db.connect() as conn:
        # Serialize submissions for one deployment; acceptance and event are atomic.
        agent = conn.execute("SELECT * FROM agents WHERE slug=%s FOR UPDATE", (slug,)).fetchone()
        if not agent:
            raise HTTPException(404, "Deployment not found.")
        if idempotency_key:
            previous = conn.execute(
                "SELECT id,request_hash FROM runs WHERE agent_slug=%s AND idempotency_key=%s",
                (slug, idempotency_key),
            ).fetchone()
            if previous:
                if previous["request_hash"] != request_hash:
                    raise HTTPException(409, "Idempotency key was already used with different input.")
                return run_links(previous["id"])
        spec = agent["config"]
        if spec["provider"] == "openrouter" and not PROVIDER_KEY:
            raise HTTPException(422, "Set LLM_API_KEY in .env and recreate the API service first.")
        if spec["provider"] == "openrouter" and BASE_URL != "https://openrouter.ai/api/v1":
            raise HTTPException(422, "This release supports the OpenRouter endpoint only.")
        if conn.execute("SELECT count(*) AS n FROM runs WHERE status='queued'").fetchone()["n"] >= 50:
            raise HTTPException(429, "The local queue is full. Try again after some runs finish.")
        additions = [r.model_dump() for r in body.additional_tools]
        enabled = [r for r in spec["tools"] if r["id"] not in body.disabled_tools] + additions
        if any(is_archive(f.name) for f in body.files) and not any(r["id"] == "archive" for r in enabled):
            additions.append({"id": "archive", "version": "1.0.0"})
        spec["tools"], spec["tool_packages"] = registry.snapshot(
            conn, spec["tools"], additions, body.disabled_tools
        )
        spec["files"] = [f.model_dump() for f in body.files]
        spec["input_files"] = [{"name": f.name, "size": len(f.bytes_value())} for f in body.files]
        spec["model"] = spec["model"] or MODEL
        run_id = db.new_id()
        conn.execute(
            "INSERT INTO runs(id,agent_slug,version,spec,input,idempotency_key,request_hash) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (run_id, slug, agent["version"], Jsonb(spec), body.input, idempotency_key, request_hash),
        )
        db.event(conn, run_id, "run.queued", {"version": agent["version"], "provider": spec["provider"]})
        return run_links(run_id)


def run_links(run_id):
    return {"id": run_id, "status_url": f"/v1/runs/{run_id}", "events_url": f"/v1/runs/{run_id}/events"}


@app.get("/v1/runs", response_model=list[RunSummary], dependencies=[Depends(admin)])
def runs():
    with db.connect() as conn:
        return conn.execute(f"SELECT {RUN_FIELDS} FROM runs ORDER BY created_at DESC LIMIT 100").fetchall()


@app.get("/v1/runs/{run_id}", response_model=RunDetail, dependencies=[Depends(admin)])
def run(run_id: str):
    with db.connect() as conn:
        row = get_run(conn, run_id)
        spec = conn.execute("SELECT spec FROM runs WHERE id=%s", (run_id,)).fetchone()["spec"]
        row["files"] = [
            {
                "name": f["name"],
                "size": f["size"],
                "workspace_path": "inputs/" + f["name"],
                "download_url": f"/v1/runs/{run_id}/files/{i}" if row["status"] not in db.TERMINAL else None,
            }
            for i, f in enumerate(spec.get("input_files", []))
        ]
        row["resolved_tools"] = registry.refs(spec.get("tool_packages", []))
        row["artifacts"] = conn.execute(
            "SELECT id,name,COALESCE(octet_length(data),octet_length(content)) AS size FROM artifacts WHERE run_id=%s ORDER BY name",
            (run_id,),
        ).fetchall()
        row["artifacts_archive_url"] = (
            f"/v1/runs/{run_id}/artifacts.zip" if len(row["artifacts"]) > 1 else None
        )
        return row


@app.post("/v1/runs/{run_id}/cancel", response_model=RunSummary, dependencies=[Depends(admin)])
def cancel(run_id: str):
    with db.connect() as conn:
        row = conn.execute("SELECT status FROM runs WHERE id=%s FOR UPDATE", (run_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Run not found.")
        if row["status"] == "queued":
            db.finish(conn, run_id, "cancelled")
        elif row["status"] == "running":
            conn.execute("UPDATE runs SET cancel_requested=true WHERE id=%s", (run_id,))
        return get_run(conn, run_id)


@app.get("/v1/runs/{run_id}/events", dependencies=[Depends(admin)])
def events(
    run_id: str,
    request: Request,
    after: int = Query(default=0, ge=0),
    last_event_id: int | None = Header(default=None, ge=0),
):
    with db.connect() as conn:
        get_run(conn, run_id)

    async def stream():
        cursor = max(after, last_event_id or 0)
        while not await request.is_disconnected():

            def batch(event_cursor=cursor):
                with db.connect() as conn:
                    # Read status first: terminal status and its event commit together.
                    status = get_run(conn, run_id)["status"]
                    rows = conn.execute(
                        "SELECT * FROM events WHERE run_id=%s AND id>%s ORDER BY id LIMIT 200",
                        (run_id, event_cursor),
                    ).fetchall()
                    return rows, status

            rows, status = await asyncio.to_thread(batch)
            for row in rows:
                cursor = row["id"]
                yield f"id: {cursor}\ndata: {json.dumps(row, default=str)}\n\n"
            if status in db.TERMINAL and len(rows) < 200:
                return
            yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@app.get("/v1/runs/{run_id}/artifacts.zip", dependencies=[Depends(admin)])
def download_all(run_id: str):
    with db.connect() as conn:
        get_run(conn, run_id)
        rows = conn.execute(
            "SELECT name,content,data FROM artifacts WHERE run_id=%s ORDER BY name", (run_id,)
        ).fetchall()
    if not rows:
        raise HTTPException(404, "No output files are available.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for row in rows:
            archive.writestr(
                row["name"], bytes(row["data"]) if row["data"] is not None else row["content"].encode("utf-8")
            )
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="outputs.zip"'},
    )


@app.get("/v1/runs/{run_id}/artifacts/{artifact_id}", dependencies=[Depends(admin)])
def download(run_id: str, artifact_id: str):
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM artifacts WHERE id=%s AND run_id=%s", (artifact_id, run_id)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Artifact not found.")
    name = Path(row["name"]).name
    return Response(
        bytes(row["data"]) if row["data"] is not None else row["content"].encode("utf-8"),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.get("/v1/runs/{run_id}/files/{file_index}", dependencies=[Depends(admin)])
def download_input(run_id: str, file_index: int):
    with db.connect() as conn:
        row = conn.execute("SELECT spec,status FROM runs WHERE id=%s", (run_id,)).fetchone()
        if row and row["status"] in db.TERMINAL:
            raise HTTPException(410, "Input files expired when this run ended.")
        files = row["spec"].get("files", []) if row else []
        if file_index < 0 or file_index >= len(files):
            raise HTTPException(404, "Input file not found.")
        item = files[file_index]
    return Response(
        decode_file(item["content_base64"]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{Path(item["name"]).name}"'},
    )


@app.get("/internal/runs/{run_id}/context", include_in_schema=False)
def context(run_id: str, authorization: str = Header(default="")):
    with db.connect() as conn:
        row = runtime_run(conn, run_id, authorization)
        return {"input": row["input"], "spec": row["spec"]}


@app.post("/internal/runs/{run_id}/events", include_in_schema=False)
def add_event(run_id: str, body: RuntimeEvent, authorization: str = Header(default="")):
    if len(json.dumps(body.data)) > 20000:
        raise HTTPException(413, "Event too large.")
    with db.connect() as conn:
        runtime_run(conn, run_id, authorization, lock=True)
        count = conn.execute("SELECT count(*) AS n FROM events WHERE run_id=%s", (run_id,)).fetchone()["n"]
        if count >= 200:
            raise HTTPException(429, "Event limit reached.")
        db.event(conn, run_id, body.kind, body.data)
    return {"ok": True}


@app.post("/internal/runs/{run_id}/result", include_in_schema=False)
def result(run_id: str, body: RunResult, authorization: str = Header(default="")):
    with db.connect() as conn:
        row = runtime_run(conn, run_id, authorization, lock=True)
        if row["output"] is not None:
            raise HTTPException(409, "A result was already submitted.")
        conn.execute("UPDATE runs SET output=%s WHERE id=%s", (body.output, run_id))
        for artifact in body.artifacts:
            conn.execute(
                "INSERT INTO artifacts(id,run_id,name,content,data) VALUES (%s,%s,%s,%s,%s)",
                (db.new_id(), run_id, artifact.name, "", artifact.bytes_value()),
            )
        db.event(conn, run_id, "agent.result", {"artifacts": len(body.artifacts)})
    return {"ok": True}


@app.post("/internal/runs/{run_id}/model", include_in_schema=False)
def model(run_id: str, body: ModelRequest, authorization: str = Header(default="")):
    with db.connect() as conn:
        row = runtime_run(conn, run_id, authorization, lock=True)
        spec = row["spec"]
        if spec["provider"] != "openrouter":
            raise HTTPException(403, "Demo runs cannot call the model gateway.")
        if row["model_calls"] >= spec["max_steps"]:
            raise HTTPException(429, "Model step limit reached.")
        conn.execute("UPDATE runs SET model_calls=model_calls+1 WHERE id=%s", (run_id,))
        db.event(conn, run_id, "model.started", {"model": spec["model"], "step": row["model_calls"] + 1})
    payload = {
        "model": spec["model"],
        "messages": body.messages,
        "max_tokens": 2048,
        "provider": {"require_parameters": True},
    }
    tools = definitions(spec["tool_packages"])
    if tools:
        payload["tools"] = tools
    try:
        with httpx.Client(timeout=60, follow_redirects=False) as client:
            response = client.post(
                BASE_URL + "/chat/completions",
                json=payload,
                headers={"Authorization": "Bearer " + PROVIDER_KEY},
            )
            response.raise_for_status()
            data = response.json()
        message = data["choices"][0]["message"]
        usage = data.get("usage") or {}
    except (httpx.HTTPError, ValueError, KeyError, IndexError):
        # Never echo upstream bodies, which may contain sensitive request context.
        raise HTTPException(
            502, "Model request failed. Check provider credits, model availability, and settings."
        ) from None
    with db.connect() as conn:
        # Retain billable usage even when a cancellation happened during the call.
        conn.execute(
            "UPDATE runs SET prompt_tokens=prompt_tokens+%s,completion_tokens=completion_tokens+%s,cost=cost+%s "
            "WHERE id=%s",
            (
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                usage.get("cost") or 0,
                run_id,
            ),
        )
        active = conn.execute(
            "SELECT status,cancel_requested FROM runs WHERE id=%s FOR UPDATE", (run_id,)
        ).fetchone()
        if active["status"] == "running" and not active["cancel_requested"]:
            db.event(
                conn,
                run_id,
                "model.completed",
                {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "cost": usage.get("cost"),
                },
            )
    return {"message": message}


@app.get("/v1/tools", dependencies=[Depends(admin)])
def tools_library():
    with db.connect() as conn:
        return conn.execute(
            "SELECT t.tool_id,t.version,t.name,t.sha256,t.status,t.origin,t.created_at,t.test_run_id,r.status AS test_status,t.package->'manifest' AS manifest FROM tool_versions t LEFT JOIN runs r ON r.id=t.test_run_id WHERE t.status!='deleted' ORDER BY t.tool_id,t.created_at DESC"
        ).fetchall()


@app.post("/v1/tools/import", status_code=201, dependencies=[Depends(admin)])
def import_tool(body: dict):
    with db.connect() as conn:
        return registry.register(conn, body)


@app.post("/v1/tools/reload", dependencies=[Depends(admin)])
def reload_tools():
    with db.connect() as conn:
        return [
            {"id": row["tool_id"], "version": row["version"], "sha256": row["sha256"]}
            for row in registry.bundled(conn)
        ]


@app.delete("/v1/tools/{tool_id}/{version}", dependencies=[Depends(admin)])
def delete_tool(tool_id: str, version: str):
    with db.connect() as conn:
        # Serialize with imports and agent edits so references cannot be added mid-delete.
        conn.execute("SELECT pg_advisory_xact_lock(71003)")
        row = conn.execute(
            "SELECT * FROM tool_versions WHERE tool_id=%s AND version=%s FOR UPDATE",
            (tool_id, version),
        ).fetchone()
        if not row or row["status"] == "deleted":
            raise HTTPException(404, "Tool version not found.")
        if row["origin"] == "bundled":
            raise HTTPException(
                409, "Bundled tools are managed by the repository and cannot be deleted here."
            )
        users = conn.execute(
            "SELECT slug FROM agents WHERE config->'tools' @> %s ORDER BY slug",
            (Jsonb([{"id": tool_id, "version": version}]),),
        ).fetchall()
        if users:
            raise HTTPException(
                409, "Remove this version from agent defaults first: " + ", ".join(a["slug"] for a in users)
            )
        # Keep a tombstone to preserve immutable version identity. Runs have their own snapshots.
        conn.execute(
            "UPDATE tool_versions SET status='deleted' WHERE tool_id=%s AND version=%s",
            (tool_id, version),
        )
        return {"status": "deleted", "tool_id": tool_id, "version": version}


@app.get("/v1/tools/{tool_id}/{version}/export", dependencies=[Depends(admin)])
def export_tool(tool_id: str, version: str):
    with db.connect() as conn:
        row = conn.execute(
            "SELECT package FROM tool_versions WHERE tool_id=%s AND version=%s AND status!='deleted'",
            (tool_id, version),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Tool version not found.")
    return Response(
        json.dumps(row["package"], indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{row["package"]["manifest"]["id"]}.tool.json"'
        },
    )


@app.post("/v1/tools/{tool_id}/{version}/test", status_code=202, dependencies=[Depends(admin)])
def test_tool(tool_id: str, version: str):
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM tool_versions WHERE tool_id=%s AND version=%s AND status!='deleted' FOR UPDATE",
            (tool_id, version),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Tool version not found.")
        if row["test_run_id"]:
            previous = conn.execute("SELECT status FROM runs WHERE id=%s", (row["test_run_id"],)).fetchone()
            if previous and previous["status"] not in db.TERMINAL:
                return run_links(row["test_run_id"])
        if conn.execute("SELECT count(*) AS n FROM runs WHERE status='queued'").fetchone()["n"] >= 50:
            raise HTTPException(429, "The local queue is full. Try again after some runs finish.")
        package = {**row["package"], "sha256": row["sha256"]}
        spec = {
            "provider": "demo",
            "model": "",
            "tools": [row["name"]],
            "tool_packages": [package],
            "tool_test": True,
            "max_steps": 1,
            "timeout_seconds": min(
                300, len(package["tests"]) * (package["manifest"]["limits"]["timeout_seconds"] + 2) + 10
            ),
        }
        run_id = db.new_id()
        conn.execute(
            "INSERT INTO runs(id,agent_slug,version,spec,input) VALUES (%s,'harbor-guide',1,%s,%s)",
            (run_id, Jsonb(spec), f"Test tool {tool_id}@{version}"),
        )
        conn.execute(
            "UPDATE tool_versions SET test_run_id=%s WHERE tool_id=%s AND version=%s",
            (run_id, tool_id, version),
        )
        db.event(conn, run_id, "run.queued", {"purpose": "tool_test", "sha256": row["sha256"]})
        return run_links(run_id)


@app.post("/v1/tools/{tool_id}/{version}/publish", dependencies=[Depends(admin)])
def publish_tool(tool_id: str, version: str):
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM tool_versions WHERE tool_id=%s AND version=%s AND status!='deleted' FOR UPDATE",
            (tool_id, version),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Tool version not found.")
        if row["status"] == "published":
            return {"status": "published", "sha256": row["sha256"]}
        run = conn.execute("SELECT status,spec FROM runs WHERE id=%s", (row["test_run_id"],)).fetchone()
        if (
            not run
            or run["status"] != "completed"
            or run["spec"]["tool_packages"][0]["sha256"] != row["sha256"]
        ):
            raise HTTPException(409, "Run the package fixtures successfully before publishing.")
        conn.execute(
            "UPDATE tool_versions SET status='published' WHERE tool_id=%s AND version=%s", (tool_id, version)
        )
        return {"status": "published", "sha256": row["sha256"]}


web = Path(os.getenv("WEB_DIR", "/app/web"))
if web.exists():
    app.mount("/assets", StaticFiles(directory=web / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(web / "index.html")
