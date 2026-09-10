import os

import docker
from docker.errors import NotFound
from docker.types import LogConfig

from agentberth.backends import RunSpec


class DockerBackend:
    name = "docker"

    def __init__(self):
        self.client = docker.from_env(timeout=10)

    def close(self):
        self.client.close()

    def submit(self, spec: RunSpec) -> str:
        container = self.client.containers.create(
            os.getenv("RUNTIME_IMAGE", "agentberth-runtime:local"),
            name=f"agentberth-run-{spec.id}",
            labels={"agentberth.managed": "true", "agentberth.run": spec.id},
            environment={
                "RUN_ID": spec.id,
                "RUN_TOKEN": spec.token,
                "API_URL": os.getenv("INTERNAL_API_URL", "http://api:8080"),
            },
            network=os.getenv("SANDBOX_NETWORK", "agentberth_sandbox"),
            user="10001:10001",
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            tmpfs={
                "/workspace": "rw,nosuid,nodev,size=64m,uid=10001,gid=10001,mode=700",
                "/tmp": "rw,nosuid,nodev,size=16m,uid=10001,gid=10001,mode=700",
            },
            mem_limit="256m",
            memswap_limit="256m",
            nano_cpus=1_000_000_000,
            pids_limit=64,
            log_config=LogConfig(type="json-file", config={"max-size": "1m", "max-file": "1"}),
            detach=True,
        )
        try:
            container.start()
        except Exception:
            container.remove(force=True)
            raise
        return container.id

    def status(self, handle):
        c = self.client.containers.get(handle)
        state = c.attrs["State"]
        return state["Running"], state.get("ExitCode")

    def cancel(self, handle):
        try:
            c = self.client.containers.get(handle)
            if c.status == "running":
                c.kill()
        except NotFound:
            pass

    def cleanup(self, handle):
        try:
            self.client.containers.get(handle).remove(force=True)
        except NotFound:
            pass

    def cleanup_orphans(self):
        # Called only while holding the single-worker database advisory lock.
        for c in self.client.containers.list(all=True, filters={"label": "agentberth.managed=true"}):
            c.remove(force=True)
