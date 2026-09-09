from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from runtime.packages import reference
from runtime.files import MAX_BASE64, decode_file, validate_name, validate_collection


class ToolRef(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,47}$")
    version: str = Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class AgentConfig(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    instructions: str = Field(min_length=1, max_length=12000)
    provider: Literal["demo", "openrouter"] = "demo"
    model: str = Field(default="", max_length=150)
    tools: list[ToolRef] = Field(
        default_factory=lambda: [ToolRef(**reference(n)) for n in ["python", "write_file", "read_file"]],
        max_length=12,
    )

    @field_validator("tools", mode="before")
    @classmethod
    def legacy_tools(cls, values):
        if not isinstance(values, list):
            raise ValueError("Tools must be an array of explicit version references.")
        return [reference(v) for v in values]

    max_steps: int = Field(default=6, ge=1, le=12)
    timeout_seconds: int = Field(default=120, ge=10, le=300)


class CreateAgent(AgentConfig):
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{1,47}$")


class FilePayload(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    content_base64: str = Field(
        max_length=MAX_BASE64, description="Base64-encoded bytes; at most 1 MiB decoded."
    )

    @field_validator("name")
    @classmethod
    def safe_name(cls, value):
        return validate_name(value)

    @field_validator("content_base64")
    @classmethod
    def valid_bytes(cls, value):
        if value is not None:
            decode_file(value)
        return value

    def bytes_value(self):
        return decode_file(self.content_base64)


class RunInput(BaseModel):
    input: str = Field(min_length=1, max_length=8000)
    files: list[FilePayload] = Field(
        default_factory=list, max_length=8, description="Files staged under inputs/. At most 4 MiB total."
    )

    @field_validator("files")
    @classmethod
    def bounded_files(cls, value):
        return validate_collection(value)

    additional_tools: list[ToolRef] = Field(default_factory=list, max_length=12)
    disabled_tools: list[str] = Field(default_factory=list, max_length=12)


class RuntimeEvent(BaseModel):
    kind: Literal["tool.started", "tool.completed", "agent.message"]
    data: dict


class Artifact(FilePayload):
    # Compatibility with runtimes that still return UTF-8 content.
    content_base64: str | None = Field(default=None, max_length=MAX_BASE64)
    content: str | None = Field(default=None, max_length=64000)

    @model_validator(mode="after")
    def one_encoding(self):
        if (self.content is None) == (self.content_base64 is None):
            raise ValueError("Provide exactly one of content or content_base64.")
        return self

    def bytes_value(self):
        return self.content.encode("utf-8") if self.content is not None else decode_file(self.content_base64)


class RunResult(BaseModel):
    output: str = Field(max_length=30000)
    artifacts: list[Artifact] = Field(default_factory=list, max_length=8)

    @field_validator("artifacts")
    @classmethod
    def bounded_artifacts(cls, value):
        return validate_collection(value)


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
    schedule_id: str | None = None
    scheduled_for: datetime | None = None
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


class InputFileMetadata(BaseModel):
    name: str
    size: int
    workspace_path: str
    download_url: str | None


class RunDetail(RunSummary):
    artifacts_archive_url: str | None = None
    files: list[InputFileMetadata] = Field(default_factory=list)
    artifacts: list[ArtifactMetadata]
    resolved_tools: list[dict] = Field(default_factory=list)


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


class ScheduleInput(BaseModel):
    # Files are deliberately unsupported: uploads belong to exactly one run.
    model_config = {"extra": "forbid"}
    name: str = Field(min_length=1, max_length=80)
    agent_slug: str = Field(pattern=r"^[a-z][a-z0-9-]{1,47}$")
    input: str = Field(min_length=1, max_length=8000)
    start_at: datetime
    interval_seconds: int | None = Field(default=None, ge=60, le=31536000)
    additional_tools: list[ToolRef] = Field(default_factory=list, max_length=12)
    disabled_tools: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("start_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("start_at must include a timezone offset or Z.")
        return value


class ScheduleState(BaseModel):
    model_config = {"extra": "forbid"}
    enabled: bool


class ScheduleRecord(BaseModel):
    id: str
    name: str
    agent_slug: str
    version: int
    input: str
    interval_seconds: int | None
    next_run_at: datetime | None
    enabled: bool
    last_run_id: str | None
    created_at: datetime


class QueueStatus(BaseModel):
    queued: int
    running: int
    capacity: int
