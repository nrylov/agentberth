# Deployment roadmap and design decisions

## Support matrix

| Mode | Status | Notes |
|---|---|---|
| Docker Compose + Docker execution | Implemented local preview | Tested locally on macOS with Linux ARM64 containers; CI workflow targets Linux |
| Kubernetes platform + Job execution | Planned | No Helm chart or Kubernetes backend is shipped yet |
| Kubernetes with VM-backed RuntimeClass | Planned | Requires a supported VM runtime installed on compatible nodes |
| Direct Firecracker | Deferred | Requires Linux/KVM and a separate host lifecycle implementation |

## Milestone 1: local vertical slice

- One-command Compose setup and a no-key demo.
- Agent configuration, HTTP invocation, streamed events, and artifacts.
- One container per run and scoped gateway credentials.
- Real OpenRouter tool loop.
- Documentation, checks, and clear limitations.

## Tool registry foundation: implemented

Repository packages (`tool.json`, `handler.py`, `tests.json`), persistent immutable versions, sandbox fixtures, publication, import/export, agent defaults, and per-run overrides are implemented. Runtime tests use the same container lifecycle and do not call an LLM. LLM-assisted draft generation remains planned and will produce this format.

## Milestone 2: Kubernetes as a first-class backend

Implement a `KubernetesBackend` that creates one Job per run. The portable runtime should retain the same callback/context/model protocol. Add configuration for image, namespace, service account, node placement, and optional runtime class.

Package API, worker, database connection configuration, and network policy in a Helm chart. Use namespace-scoped RBAC for Job lifecycle and required Pod status/log access. Avoid cluster-admin. Separate the control-plane worker service account from sandbox workloads; disable automatic service account token mounting in sandbox Pods. Define seccomp, non-root execution, resource limits, read-only roots, and bounded `emptyDir` workspaces.

Credentials and secrets require an explicit transport plan. The run token is still a secret even though it is short-lived. Do not give agent Pods cluster API permissions. Restrict traffic with a CNI that actually enforces NetworkPolicy, and test API/database/metadata access denial.

Map deadlines and cancellation to Job termination, reconcile worker/Job failures, handle retries explicitly, and use TTL cleanup only as a fallback. Do not allow Kubernetes Job retries to silently replay external side effects. Replace the Docker-specific orphan sweep with backend-specific reconciliation.

Acceptance: a local cluster can deploy from the chart, run the same demo and real-provider contract tests, deny unauthorized network access, recover from worker/node failures, and remove completed/cancelled Jobs. Document image loading for local clusters and registry access for remote clusters. Database migrations, backup/restore, authentication configuration, and graceful upgrades belong in this milestone.

## Milestone 3: VM isolation on Kubernetes

Choose and validate a specific Kata/hypervisor combination on Linux hosts with the required virtualization support. Kubernetes `RuntimeClass` selects a configured runtime; creating the RuntimeClass object alone does not install or enable VM isolation. VM boundaries follow the configured Pod sandbox, not necessarily each individual container.

Acceptance: the same run package executes with verified VM isolation, correct cancellation and filesystem cleanup, and measured cold-start/resource behavior. Publish the exact tested host/runtime versions and troubleshooting steps. A local macOS Kubernetes cluster is not evidence that KVM-backed production nodes work.

Reference: [Kata architecture](https://github.com/kata-containers/kata-containers/blob/main/docs/design/architecture/README.md).

## Milestone 4: optional direct Firecracker

Build the root filesystem/kernel pipeline and a privileged host service for microVM lifecycle, networking, deadlines, cleanup, and recovery. A container image is not directly a Firecracker boot image. Add an OCI-to-guest packaging path or a guest container runtime.

Firecracker requires Linux and KVM access. Use its production jailer guidance and validate the real target host. Do not snapshot environments after injecting user secrets and reuse those snapshots across users. Defer warm pools until measured startup latency justifies them.

References: [Firecracker getting started](https://github.com/firecracker-microvm/firecracker/blob/main/docs/getting-started.md), [production host guidance](https://github.com/firecracker-microvm/firecracker/blob/main/docs/prod-host-setup.md).

## Subsequent product capabilities

- Deployment-scoped keys, user accounts, and authorization.
- Immutable agent version archive and deployment rollback.
- Sessions, durable conversation state, and optional persistent workspaces.
- Object storage for larger artifacts; bounded binary artifact transport is implemented.
- Remote tools and constrained egress.
- Tenant budgets, distributed scheduling, and workload image supply-chain controls.

These are not implied by the current UI or API. Keep “planned” labels until each mode has reproducible deployment instructions and passing integration tests.
