from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RunSpec:
    id: str
    token: str


class ExecutionBackend(Protocol):
    """Lifecycle contract; event/artifact transport is the run-scoped HTTP API.

    A future Kubernetes backend maps a handle to a Job UID. This release only
    implements Docker. Session reuse is deliberately outside this contract.
    """

    def submit(self, spec: RunSpec) -> str: ...
    def status(self, handle: str) -> tuple[bool, int | None]: ...
    def cancel(self, handle: str) -> None: ...
    def cleanup(self, handle: str) -> None: ...
