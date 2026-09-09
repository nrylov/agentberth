from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

ToolName = Literal["python", "read_file", "write_file"]


class AgentConfig(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    instructions: str = Field(min_length=1, max_length=12000)
    provider: Literal["demo", "openrouter"] = "demo"
    model: str = Field(default="", max_length=150)
    tools: list[ToolName] = Field(default_factory=lambda: ["python", "write_file", "read_file"], max_length=3)
    max_steps: int = Field(default=6, ge=1, le=12)
    timeout_seconds: int = Field(default=120, ge=10, le=300)


class CreateAgent(AgentConfig):
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{1,47}$")


class RunInput(BaseModel):
    input: str = Field(min_length=1, max_length=8000)


class RuntimeEvent(BaseModel):
    kind: Literal["tool.started", "tool.completed", "agent.message"]
    data: dict


class Artifact(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_./-]{1,150}$")
    content: str = Field(max_length=64000)


class RunResult(BaseModel):
    output: str = Field(max_length=30000)
    artifacts: list[Artifact] = Field(default_factory=list, max_length=8)


class ModelRequest(BaseModel):
    messages: list[dict] = Field(min_length=1, max_length=100)


class AgentRecord(BaseModel):
    slug: str
    name: str
    version: int
    config: AgentConfig
    updated_at: datetime


class RunLinks(BaseModel):
    id: str
    status_url: str
    events_url: str


class RunSummary(BaseModel):
    id: str
    agent_slug: str
    version: int
    input: str
    status: Literal["queued", "running", "completed", "failed", "cancelled", "timed_out"]
    output: str | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested: bool
    model_calls: int
    prompt_tokens: int
    completion_tokens: int
    cost: Decimal


class ArtifactMetadata(BaseModel):
    id: str
    name: str
    size: int


class RunDetail(RunSummary):
    artifacts: list[ArtifactMetadata]


class ProviderStatus(BaseModel):
    base_url: str
    model: str
    configured: bool


class WorkspaceSettings(BaseModel):
    provider: ProviderStatus
    backend: str
    worker_online: bool
    auth_mode: str
    demo_key: bool
