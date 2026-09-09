# Kubernetes deployment

Agentberth supports two independent deployment modes: Docker Compose on a laptop, and the Helm chart with a Kubernetes Job backend. They use the same GUI/API and tools, but have separate databases, agents, imported tool versions, and run histories. Compose remains the default; no Kubernetes credentials are required for it.

The Kubernetes worker runs **inside the cluster** using its service account. It does not read your laptop kubeconfig. Your kubeconfig is only used by installation and test commands. Always select the intended context explicitly.

## Architecture and limits

- One API Deployment serves the GUI and public API. Only this component receives `LLM_API_KEY`.
- One worker Deployment holds the database advisory lock and processes one run at a time. Its namespace-scoped role manages Jobs, Pods (read-only), and run token Secrets in a dedicated sandbox namespace. It has no permission to read the control namespace's provider/database Secret.
- PostgreSQL runs in a StatefulSet with a PVC. External PostgreSQL is supported by disabling `postgres.enabled` and supplying a corresponding `DATABASE_URL`.
- Each run gets a Job, a short-lived token Secret owned by that Job, and memory-backed workspaces. Agent Pods have no service-account token, host mounts, elevated capabilities, or writable root filesystem. They run as UID 10001 with RuntimeDefault seccomp.
- Job retries are disabled (`backoffLimit: 0`, `restartPolicy: Never`); the deadline includes startup/scheduling. Kubernetes may still duplicate execution under exceptional failures; this is not an exactly-once guarantee.
- The worker deletes Jobs and waits for Pod removal before reporting completion. It removes leftover Jobs/Secrets after restart. A 10-minute TTL is a fallback; it is not normal cleanup.
- Inputs expire and credentials are revoked even if cleanup needs reconciliation. Cluster/API outages or partitioned nodes can delay confirmed teardown. Kubernetes object deletion is not proof of physical erasure on an unreachable machine.
- Runtime memory is 256 MiB, workspace 64 MiB, temporary files 16 MiB. CPU request/limit, node selectors, tolerations, and optional RuntimeClass are configurable. There is no portable per-Pod PID limit in the chart; configure node/runtime PID limits where supported. RuntimeClass requires a compatible runtime already installed on the nodes.

This is a single-worker, single-database preview, not a highly available installation. On a 4 GiB test node, keep the default resources and one active run. Check actual allocatable resources and pressure rather than assuming all node RAM is available to workloads.

## Prerequisites

Install Docker/buildx, `kubectl`, and Helm 3.19+ (or compatible Helm). For local testing install kind; for DigitalOcean install `doctl`. Supported chart API baseline is Kubernetes 1.30+, but only versions recorded in [validation](validation.md) have been tested. MicroK8s values are provided separately and must be validated on your installation.

Use a dedicated test cluster/namespace, a CNI that enforces NetworkPolicy, and a working storage class. No ingress, public load balancer, domain, or TLS certificate is needed for port-forward testing.

```bash
KUBECONFIG_PATH=/absolute/path/to/kubeconfig
KUBE_CONTEXT=your-test-context
kubectl --kubeconfig "$KUBECONFIG_PATH" --context "$KUBE_CONTEXT" get nodes
kubectl --kubeconfig "$KUBECONFIG_PATH" --context "$KUBE_CONTEXT" get storageclasses
```

The examples use release `demo`, control namespace `agentberth`, sandbox namespace `agentberth-sandbox`, and service `demo-agentberth-api`. Each installation needs its own control and sandbox namespaces. Do not reuse a sandbox namespace between releases.

## DigitalOcean: images and registry

Create your 4 GiB node cluster and a DigitalOcean Container Registry. Authenticate locally:

```bash
doctl auth init
doctl registry login
# Enable managed registry pull credentials in this dedicated cluster.
doctl kubernetes cluster registry add YOUR_CLUSTER_ID
```

No credentials should appear in Git, Helm values, screenshots, or chat. `.env`, `.kubeconfig`, and `work/` are excluded from the build context. For remote builds, audit any additional local credential paths too.

A one-repository registry plan can hold **both images under different tags**:

```bash
IMAGE_REPOSITORY=registry.digitalocean.com/YOUR_REGISTRY/agentberth-platform
IMAGE_VERSION=k8s-preview-001

docker buildx build --platform linux/amd64,linux/arm64 --target platform \
  -t "$IMAGE_REPOSITORY:platform-$IMAGE_VERSION" --push .
docker buildx build --platform linux/amd64,linux/arm64 --target runtime \
  -t "$IMAGE_REPOSITORY:runtime-$IMAGE_VERSION" --push .
```

Use a new version for each build. For reproducible releases, deploy image digest references. `images.platform` and `images.runtime` accept full OCI references, so Docker Hub/GHCR or another registry also works. Private registry pull credentials must exist in **both namespaces**. DigitalOcean integration normally provisions a Secret named after the registry in each namespace; verify it before accepting runs.

## Initial credentials

This helper creates the control namespace and a new Secret with generated admin/database credentials. It refuses to overwrite an existing Secret. It optionally reads only `LLM_API_KEY` from your local `.env`; omit `--env-file` for a no-credit demo-only installation.

```bash
python3 scripts/kubernetes_secret.py \
  --kubeconfig "$KUBECONFIG_PATH" --context "$KUBE_CONTEXT" \
  --namespace agentberth --release demo \
  --admin-key-file work/kubernetes-admin-key \
  --env-file .env
```

The key file is mode 0600 and should remain ignored by Git. The Secret has `ADMIN_KEY`, `DATABASE_URL`, `POSTGRES_PASSWORD`, and `LLM_API_KEY`. Helm references it by name; it does not store these values in chart release configuration. For an external database, create an equivalent Secret yourself and set `postgres.enabled=false`; allow worker/API database egress if you enable restrictive control-plane policies.

## Install on DigitalOcean

```bash
helm upgrade --install demo deploy/helm/agentberth \
  --kubeconfig "$KUBECONFIG_PATH" --kube-context "$KUBE_CONTEXT" \
  --namespace agentberth \
  -f deploy/kubernetes/values-digitalocean.yaml \
  --set-string images.platform="$IMAGE_REPOSITORY:platform-$IMAGE_VERSION" \
  --set-string images.runtime="$IMAGE_REPOSITORY:runtime-$IMAGE_VERSION" \
  --set 'imagePullSecrets[0].name=YOUR_REGISTRY' \
  --wait --timeout 5m
```

The default requests a 5 GiB DigitalOcean block-storage PVC. This is separate from the node's boot disk and may incur a separate charge. Use a retained storage class if desired. Do not store PostgreSQL data on a node hostPath in this environment.

Connect in a separate terminal:

```bash
kubectl --kubeconfig "$KUBECONFIG_PATH" --context "$KUBE_CONTEXT" \
  -n agentberth port-forward svc/demo-agentberth-api 8081:8080
```

A convenience wrapper is also available: `python3 scripts/kubernetes_connect.py --kubeconfig "$KUBECONFIG_PATH" --context "$KUBE_CONTEXT"`. With the repository's `.kubeconfig` and release `demo`, simply run `python3 scripts/kubernetes_connect.py` from the repository root. It selects the context from that explicit file and does not alter your default kubeconfig.

The `*.k8s.ondigitalocean.com` hostname in kubeconfig is the Kubernetes management endpoint, not the Agentberth website. Port-forwarding tunnels through it to the application's ClusterIP Service. No public load balancer or open application firewall port is required.

Open **http://localhost:8081**, enter the admin key from `work/kubernetes-admin-key`, and confirm Settings shows **Kubernetes** with an online worker. Your Compose console remains **http://localhost:8080**. Port-forward binds locally and must remain running; restart it after the API Pod is replaced.

## kind

kind runs locally inside Docker and does not require a remote registry:

```bash
kind create cluster --name agentberth-test --kubeconfig work/kind.kubeconfig
KUBECONFIG_PATH="$PWD/work/kind.kubeconfig"
KUBE_CONTEXT=kind-agentberth-test

docker compose build
kind load docker-image agentberth-platform:local agentberth-runtime:local --name agentberth-test
python3 scripts/kubernetes_secret.py \
  --kubeconfig "$KUBECONFIG_PATH" --context "$KUBE_CONTEXT" \
  --namespace agentberth --release demo --admin-key-file work/kind-admin-key
helm upgrade --install demo deploy/helm/agentberth \
  --kubeconfig "$KUBECONFIG_PATH" --kube-context "$KUBE_CONTEXT" \
  --namespace agentberth -f deploy/kubernetes/values-kind.yaml --wait --timeout 5m
```

Use the same port-forward command, or local port 8082 when DigitalOcean already uses 8081. Pin the kind/node versions for CI. NetworkPolicy support depends on the selected kind/CNI version: run the isolation probe below; do not assume that creating NetworkPolicy objects proves enforcement. Install a compatible enforcing CNI if the probe fails.

Loading a changed image under the same local tag does not restart Pods. Prefer new tags; for a local iteration reload images and restart API/worker Deployments after active runs finish.

## MicroK8s

On your MicroK8s host, enable DNS and a suitable storage provisioner. For a single-node test:

```bash
microk8s enable dns hostpath-storage
```

Export a kubeconfig using `microk8s config`, protect that file, and use its actual context name. Use the same registry images and credential setup, then install with `-f deploy/kubernetes/values-microk8s.yaml`. Create pull Secrets in both namespaces for private registries. Alternatively, import compatible images into MicroK8s containerd using the distribution's image import workflow.

`microk8s-hostpath` is node-local storage and does not make PostgreSQL resilient to node loss. Use an appropriate shared/durable CSI storage class for multi-node deployments. Check the CNI, DNS labels, node architecture, and policy enforcement with the same probe before enabling untrusted tools. This guide does not claim MicroK8s runtime verification until it is recorded in validation.

## Verify GUI/API parity and isolation

Read the administration key into the environment without placing it in command arguments:

```bash
export AGENTBERTH_ADMIN_KEY="$(cat work/kubernetes-admin-key)"
python3 scripts/smoke.py --base-url http://127.0.0.1:8081
python3 scripts/smoke_tools.py --base-url http://127.0.0.1:8081
AGENTBERTH_BASE_URL=http://127.0.0.1:8081 python3 scripts/smoke_files.py
```

These use no model credits and verify the same public API used by the GUI: tasks, tools, files, archives, streaming, idempotency, and downloads. `scripts/run_files.py --base-url ...` also works unchanged; see [file examples](files.md).

On a **dedicated test installation with no valuable active runs**, run the Kubernetes-specific probe. It creates a temporary network-check Pod, suspends test Jobs, and deliberately kills the worker Pod to verify recovery:

```bash
python3 scripts/smoke_kubernetes.py \
  --kubeconfig "$KUBECONFIG_PATH" --context "$KUBE_CONTEXT" \
  --namespace agentberth --sandbox-namespace agentberth-sandbox \
  --release demo --base-url http://127.0.0.1:8081
```

The probe verifies API access, denied database/cluster-API/metadata/internet connections, absent service-account credentials, Job security, cancellation, timeout, orphan cleanup, run-token Secret removal, and input expiry. The negative network checks are representative endpoints, not a proof against every network escape. Do not use Docker's `scripts/resilience.py` against Kubernetes.

Optional `scripts/smoke.py --live --base-url ...` spends model credits through the configured provider.

## Network policy scope

Sandbox namespace ingress is denied. Egress permits only the API Pod on port 8080 and CoreDNS Pods (`k8s-app=kube-dns`) on TCP/UDP 53. The database permits only the API and worker in its own namespace. Service-account/RBAC protection remains in place in addition to networking.

The trusted control-plane API and worker retain general egress by default. The worker needs database/DNS and Kubernetes API access; DigitalOcean's control-plane proxy path may require Cilium-specific `toEntities: kube-apiserver` rather than standard API IP allowlists. The optional `networkPolicy.workerEgressRestricted` and `kubernetesApiCIDRs` are for distributions where that route has been verified. Node-local DNS may require a distribution-specific policy adjustment. Never disable sandbox policy simply to make a failed test pass.

The chart currently exposes only a ClusterIP Service. To expose it publicly, configure HTTPS ingress and access controls explicitly; the single workspace administration key is still the authentication model.

## Upgrade, backup, and uninstall

Build new versioned images, stop submitting work, wait for active runs, and use `helm upgrade` with the same namespaces, Secret, and new image references. API/worker use Recreate updates to fit small nodes and avoid overlapping workers; expect brief downtime. Startup applies additive database migrations; a Helm rollback does not roll back schema or data. Back up first, and check compatibility before rolling application images back.

Example database backup (keep it private; it includes outputs, configuration, and any active staged inputs):

```bash
kubectl --kubeconfig "$KUBECONFIG_PATH" --context "$KUBE_CONTEXT" \
  -n agentberth exec demo-agentberth-postgres-0 -- \
  pg_dump -U agentberth -d agentberth -Fc > work/agentberth-backup.dump
```

For restore, stop API/worker Deployments, restore into an intentionally selected empty database using `pg_restore`, then restart the application. Test restore on a disposable installation before relying on a backup. The generated database password and PVC must stay paired; changing the Secret alone does not rotate the password stored inside PostgreSQL.

`helm uninstall demo --namespace agentberth ...` removes application workloads and policies but retains PostgreSQL PVCs and the sandbox namespace. First stop submissions and wait for/clean up active Jobs; the normal worker is responsible for teardown. Retained PVCs can continue to incur storage charges. Explicitly delete retained Jobs, Secrets, PVCs, or namespaces only when their data is no longer needed. Deleting a kind cluster destroys its local storage. Cloud node failure can delay cleanup; inspect Pods, Jobs, and events before force-deleting objects.

## Troubleshooting

| Symptom | Check |
|---|---|
| API restarts during initial install | PostgreSQL readiness, PVC binding, Secret keys/DB URL; startup retries through Kubernetes restart policy |
| Worker offline | Logs, DB advisory lock (one worker), RBAC in sandbox namespace, Kubernetes API connectivity |
| Job pending | Node allocatable resources, taints/selectors, image architecture, pull Secret in sandbox namespace |
| ImagePullBackOff | Fully qualified image reference, registry login/integration, namespace-local pull Secret |
| Run times out during startup | Deadline includes image pulls/scheduling; preload images or increase task timeout |
| Sandbox cannot reach API | Service endpoints, DNS labels/CNI policy, namespace selectors |
| Network isolation probe fails | Enforcing CNI/version; inspect actual policies before running untrusted code |
| Helm upgrade fails on storage | PVC storage class is not mutable; perform a deliberate migration instead |
| Port-forward stops | API Pod changed; restart the port-forward command |
| Worker cleanup fails | Inspect Job/Pod finalizers and node readiness; token/input access is revoked while reconciliation retries |

Inspect workload status and events without printing raw Secrets:

```bash
kubectl --kubeconfig "$KUBECONFIG_PATH" --context "$KUBE_CONTEXT" -n agentberth get pods,pvc
kubectl --kubeconfig "$KUBECONFIG_PATH" --context "$KUBE_CONTEXT" -n agentberth-sandbox get jobs,pods
kubectl --kubeconfig "$KUBECONFIG_PATH" --context "$KUBE_CONTEXT" -n agentberth logs deployment/demo-agentberth-worker --tail=50
```

References: [Kubernetes Jobs](https://kubernetes.io/docs/concepts/workloads/controllers/job/), [kind quick start](https://kind.sigs.k8s.io/docs/user/quick-start/), [DOKS limits](https://docs.digitalocean.com/products/kubernetes/details/limits/), [MicroK8s hostpath storage](https://canonical.com/microk8s/docs/addon-hostpath-storage).
