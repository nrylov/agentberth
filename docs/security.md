# Security model

Agentberth v0.1 is for one trusted administrator running a local development stack. It is **not production multi-tenant isolation**, and it has not undergone an independent security audit.

## Credentials and authentication

- `.env` and `.env.*` are ignored by Git and excluded from Docker build contexts. `.env.example` contains placeholders only.
- Only the API receives the LLM key. The worker and runtime do not receive it.
- API responses never return provider secrets. Upstream error bodies are not reflected to clients.
- A random token authorizes one active run's context, events, result submission, and model gateway. PostgreSQL stores its hash. Terminal transitions revoke it; cancellation blocks further runtime work immediately.
- A run token does not grant administration access or access to another run.
- Python subprocess environments omit runtime tokens, but this is defense in depth only: code running as the same user can potentially inspect the parent process. Treat everything inside one sandbox as the same trust domain.
- The administration key controls all local agents and runs. The default key is public and intended only for loopback development. A manually entered console key is saved in tab-scoped session storage.

## Docker privileges

The worker has the Docker socket mounted and runs as root to access it across local setups. Docker socket access effectively grants control over the Docker host. The read-only container filesystem and `cap_drop` settings do not make the worker unprivileged.

Agent containers have no Docker socket, no host bind mounts, a read-only root filesystem, UID 10001, all Linux capabilities dropped, and `no-new-privileges`. CPU, memory, swap, process count, temporary storage, log size, and execution duration are bounded. Built-in file tools reject path traversal and symlink escapes. Python is intentionally arbitrary code inside the container; file-tool path checks do not constrain Python's access to its own container filesystem.

On macOS, containers execute in Docker Desktop's Linux VM. The Docker backend does not provide a separate microVM per run.

## Network boundaries

The database network and sandbox network are separate internal Docker networks. The API joins both and also has an outbound network. The worker joins only the database network. Run containers join only the sandbox network, so they have no direct external internet route. They can reach the API, whose runtime routes require their run token and whose administration routes require the admin key.

The gateway accepts only platform-selected model settings and tool schemas. It does not accept arbitrary destinations, authorization headers, or unbounded generation parameters from the sandbox. This release only supports the fixed OpenRouter base URL.

Docker network topology is not a complete hostile-code egress firewall. Host reachability, Docker daemon configuration, other network participants, and platform vulnerabilities remain relevant. Production deployment requires a reviewed threat model, network policy and/or egress proxy, secure node configuration, and workload identity. Do not expose the current API publicly or run untrusted customer workloads on it.

## Data and model behavior

Input, tool arguments, tool output, final results, and artifacts are persisted in PostgreSQL. There is no automatic retention or encryption layer beyond your host/storage setup. Model prompts and tool results are sent to OpenRouter and the selected upstream provider. Review their data policies for your intended workload.

The gateway enforces a maximum number of model requests and completion tokens per request. This is not a dollar-denominated budget. In-flight model calls can still be billed after cancellation. There are no automatic provider retries, so transient errors fail the run rather than create hidden extra spend.

Prompt injection can change an agent's behavior within its permitted tools. The demo is deterministic; real model outputs and artifacts are untrusted data. The UI renders them as text and downloads artifacts as attachments rather than executing HTML.

## Before production

Add tenant authorization, per-deployment credentials, encrypted secret storage/rotation, migrations/backups/retention, image pinning/signing/scanning, explicit egress enforcement, distributed worker fencing, quotas, durable external side-effect handling, and tested recovery on the target infrastructure. VM isolation is an additional boundary, not a substitute for these controls.


## Custom tool packages

Registry import and reload are administration-only actions. Imports never execute handler code in the control plane. Packages have bounded sizes, fixed file/entrypoint conventions, explicit schemas without remote references, and content hashes. Only published versions can be attached to ordinary runs. Imported drafts require a successful sandbox fixture run before publication.

Publication and tests are functional checks, not a certification of code safety. All tools in one run share the container trust boundary; arbitrary Python may bypass workspace helpers or inspect other same-user processes. Run-only selection does not create per-tool network/credential permissions. Tool test fixtures supplied by an author can be incomplete or misleading, and hostile code may interfere with its own sandbox. Review code and fixtures before publishing.

No arbitrary dependency installation, host-side imports, remote tool fetching, or autonomous LLM publication is implemented. LLM-generated source will eventually enter the same draft workflow.
