from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RunSpec:
    id: str
    token: str
    timeout_seconds: int = 120


class ExecutionBackend(Protocol):
    """Lifecycle contract; event/artifact transport is the run-scoped HTTP API.

    Handles identify a Docker container or a Kubernetes Job name and UID.
    Session reuse is deliberately outside this contract.
    """

    name: str

    def close(self) -> None: ...

    def cleanup_orphans(self) -> None: ...

    def submit(self, spec: RunSpec) -> str: ...
    def status(self, handle: str) -> tuple[bool, int | None]: ...
    def cancel(self, handle: str) -> None: ...
    def cleanup(self, handle: str) -> None: ...


class BackendError(RuntimeError):
    """Operator-safe execution diagnostic, without credentials or raw API payloads."""


class CleanupError(BackendError):
    """Uncertain teardown requires worker restart and reconciliation."""


def backend_name():
    import os

    name = os.getenv("EXECUTION_BACKEND", "docker")
    if name not in {"docker", "kubernetes"}:
        raise ValueError("EXECUTION_BACKEND must be docker or kubernetes.")
    return name


def create_backend():
    if backend_name() == "kubernetes":
        from agentberth.backends.kubernetes import KubernetesBackend

        return KubernetesBackend()
    from agentberth.backends.docker import DockerBackend

    return DockerBackend()
