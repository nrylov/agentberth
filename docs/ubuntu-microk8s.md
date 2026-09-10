# Ubuntu VM installation with MicroK8s

This guide provisions a fresh Ubuntu Server 24.04 VM with one attached 10 GB data volume. It uses one MicroK8s node, separate control and task namespaces, three concurrent task pods, and PostgreSQL on the attached volume. The existing Docker installation on your Mac stays independent. These instructions are a setup recipe; record actual VM validation separately in [validation](validation.md).

## 1. SSH access from your Mac

Use the SSH key you selected when creating the Droplet. Add an entry to `~/.ssh/config`, substituting your VM IP, login user, and existing private-key path:

```sshconfig
Host agentberth-vm
    HostName YOUR_VM_IP
    User root
    IdentityFile ~/.ssh/YOUR_EXISTING_KEY
    IdentitiesOnly yes
```

`root` is the usual initial DigitalOcean Ubuntu login; use your configured sudo user if different. Connect with `ssh agentberth-vm` and verify the host fingerprint against the Droplet console before accepting it. If the key has a passphrase, load it into your local SSH agent with `ssh-add ~/.ssh/YOUR_EXISTING_KEY`.

Codex can use this locally configured SSH connection once you provide the host alias and authorize setup. Do not paste a private key, root password, provider API key, or kubeconfig contents into chat. No additional remote-control agent is needed. Setup requires root or sudo privileges; an interactive sudo password can be entered by you in your terminal if needed.

In the DigitalOcean Cloud Firewall, initially permit inbound SSH (TCP 22) only from your current public IP. Leave Kubernetes API ports, PostgreSQL, and node-to-node ports closed to the public internet. Outbound connectivity is needed for package/image downloads and LLM access. Do not blindly enable a second host firewall: any existing host firewall must also allow MicroK8s pod forwarding and internal networking.

## 2. Prepare Ubuntu and inspect the volume

On the VM, use a root shell for the remaining VM commands (`sudo -i` if logged in as a sudo user):

```bash
apt-get update
apt-get upgrade -y
apt-get install -y snapd git python3 ca-certificates
lsblk -o NAME,SIZE,FSTYPE,UUID,MOUNTPOINTS
findmnt
```

Reboot if `/var/run/reboot-required` exists, then reconnect. Check `uname -m`: the image-build commands below assume `x86_64`.

DigitalOcean may have already formatted and mounted your volume under `/mnt/volume_...`. If so, retain that filesystem and mount point. Do not reformat it. Set this variable to its actual mount point:

```bash
VOLUME_MOUNT=/mnt/YOUR_ACTUAL_VOLUME_MOUNT
mountpoint "$VOLUME_MOUNT"
df -h "$VOLUME_MOUNT"
```

If the volume is unformatted or unmounted, identify the attached 10 GB device by size and `/dev/disk/by-id/` before proceeding. Use DigitalOcean's [volume mounting instructions](https://docs.digitalocean.com/products/volumes/how-to/mount-unmount/). For a **confirmed empty attached volume only**, create an ext4 filesystem on that device; never format the boot disk or a volume that already contains data. Mount it at a stable path such as `/mnt/agentberth-data`.

Ensure the volume has a persistent boot-time mount. DigitalOcean may provide an enabled systemd `.mount` unit instead of an `/etc/fstab` entry. Check `systemctl list-units --type=mount` and inspect the matching unit with `systemctl cat` and `systemctl is-enabled`; retain a correctly configured existing unit. Do not add a duplicate fstab mount.

If no persistent mount exists, add an `/etc/fstab` entry using the filesystem UUID and correct filesystem type, for example:

```text
UUID=YOUR_VOLUME_FILESYSTEM_UUID /mnt/agentberth-data ext4 defaults,nosuid,nodev 0 2
```

Use the actual existing mount point if different, and edit an existing entry rather than adding a duplicate. Run `mount -a` and verify `mountpoint "$VOLUME_MOUNT"` succeeds. All later storage commands assume this variable names the mounted volume, not an ordinary directory on the boot disk.

## 3. Install Kubernetes

MicroK8s includes its own container runtime; Docker is not required on the VM. The channel below follows Canonical's documented stable 1.35 release line; use the same selected minor release for reproducibility rather than an unpinned `latest` channel.

```bash
snap install microk8s --classic --channel=1.35/stable
microk8s status --wait-ready
microk8s enable dns
microk8s enable rbac
microk8s enable hostpath-storage
microk8s enable helm3
microk8s kubectl -n kube-system rollout status deployment/hostpath-provisioner --timeout=120s
snap alias microk8s.kubectl kubectl
microk8s kubectl get nodes -o wide
```

Enable addons individually and verify the storage provisioner before installing the chart. A StorageClass alone cannot provision storage: if the PostgreSQL PVC remains Pending and `hostpath-provisioner` is absent, run `microk8s enable hostpath-storage` and wait for its rollout. The existing claim will be retried automatically. RBAC must also be enabled for the chart’s service-account permissions to be enforced.

Keep MicroK8s dependent on the data mount so it cannot silently create replacement database directories on the boot disk if the volume is unavailable:

```bash
mountpoint "$VOLUME_MOUNT"
for unit in snap.microk8s.daemon-kubelite.service snap.microk8s.daemon-containerd.service; do
    mkdir -p "/etc/systemd/system/$unit.d"
    cat > "/etc/systemd/system/$unit.d/data-volume.conf" <<UNIT
[Unit]
RequiresMountsFor=$VOLUME_MOUNT
UNIT
done
systemctl daemon-reload
```

These dependencies take effect on subsequent service starts. Before storing valuable data, reboot once and verify the volume is mounted and the node becomes Ready again.

## 4. Create storage on the attached volume

Create a dedicated StorageClass before installing Agentberth:

```bash
mountpoint "$VOLUME_MOUNT"
mkdir -p "$VOLUME_MOUNT/agentberth"
microk8s kubectl apply -f - <<YAML
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: agentberth-volume
provisioner: microk8s.io/hostpath
reclaimPolicy: Retain
volumeBindingMode: WaitForFirstConsumer
parameters:
  pvDir: $VOLUME_MOUNT/agentberth
YAML
```

The `Retain` policy preserves storage after a claim is deleted; it does not automatically reattach a database to a new cluster. Recovery after rebuilding Kubernetes needs deliberate PV restoration or a database restore. Keep backups outside this VM/volume.

The database claim below requests 5 GiB, leaving headroom on the 10 GB volume. **Hostpath storage does not enforce the requested size as a quota.** Monitor `df -h "$VOLUME_MOUNT"`; outputs and run history currently accumulate. Input files remain task-scoped and expire on completion. Images and runtime files stay on the boot disk.

## 5. Obtain the source and transfer images

On the VM, clone your repository (replace the URL with your actual repository URL):

```bash
git clone YOUR_AGENTBERTH_REPOSITORY_URL /opt/agentberth
cd /opt/agentberth
mkdir -p work
chmod 700 work
```

Use the same code revision for the chart and image builds. Push/commit your intended application changes before cloning, or transfer your intended source checkout explicitly.

On your **Mac**, in the Agentberth repository with Docker Desktop running:

```bash
mkdir -p work
docker buildx build --platform linux/amd64 --target platform \
  -t agentberth-platform:vm-001 --load .
docker buildx build --platform linux/amd64 --target runtime \
  -t agentberth-runtime:vm-001 --load .
docker image save -o work/agentberth-vm-001.tar \
  agentberth-platform:vm-001 agentberth-runtime:vm-001
scp work/agentberth-vm-001.tar agentberth-vm:agentberth-vm-001.tar
```

On the **VM**, import the archive from the SSH user's home directory. The example assumes the root SSH login above:

```bash
microk8s images import < /root/agentberth-vm-001.tar
microk8s ctr images ls | grep agentberth
```

This avoids requiring a private registry. If using a non-root SSH login, adjust the archive path accordingly. For an ARM64 VM, build `linux/arm64` instead. Use fresh image tags for subsequent updates. Verify the images imported successfully before optionally removing the transfer archive to free boot-disk space.

## 6. Create application credentials

On the VM:

```bash
cd /opt/agentberth
umask 077
microk8s config > work/microk8s.kubeconfig
KUBE_CONTEXT=$(kubectl --kubeconfig work/microk8s.kubeconfig config current-context)
```

For OpenRouter, enter the API key at a hidden prompt, not as a literal shell command. Omit these two lines for demo-only usage:

```bash
read -r -s -p 'OpenRouter API key: ' LLM_API_KEY
export LLM_API_KEY
```

Then create the Secret and save the generated admin key privately:

```bash
python3 scripts/kubernetes_secret.py \
  --kubeconfig work/microk8s.kubeconfig --context "$KUBE_CONTEXT" \
  --namespace agentberth --release demo \
  --admin-key-file work/microk8s-admin-key
unset LLM_API_KEY
```

The helper generates database credentials and refuses to overwrite an existing application Secret or admin-key file. Reuse them on upgrades. An old managed-cluster admin key is not the new deployment's key.

## 7. Install Agentberth

On the VM, create `work/vm-values.yaml`:

```bash
cat > work/vm-values.yaml <<'YAML'
images:
  platform: docker.io/library/agentberth-platform:vm-001
  runtime: docker.io/library/agentberth-runtime:vm-001
  pullPolicy: IfNotPresent
postgres:
  storageClass: agentberth-volume
  storageSize: 5Gi
execution:
  maxConcurrentRuns: 3
  maxQueuedRuns: 50
publicAccess:
  enabled: false
YAML
microk8s helm3 upgrade --install demo deploy/helm/agentberth \
  --namespace agentberth -f work/vm-values.yaml --wait --timeout 5m
microk8s kubectl -n agentberth get pods,pvc
microk8s kubectl get pv
```

Use this values file instead of the previous DigitalOcean managed-cluster overrides: those reference `do-block-storage`, the old registry, and potentially the deleted load balancer. No cloud load balancer or DigitalOcean Kubernetes integration is required here.

## 8. Access the console without a tunnel

For initial private testing, create a separate NodePort Service. It routes port 31089 on the VM to port 8080 on the API pod:

```bash
microk8s kubectl apply -f - <<'YAML'
apiVersion: v1
kind: Service
metadata:
  name: agentberth-test-access
  namespace: agentberth
spec:
  type: NodePort
  selector:
    app: demo-agentberth-api
  ports:
    - name: http
      port: 80
      targetPort: 8080
      nodePort: 31089
YAML
```

In the **DigitalOcean Cloud Firewall**, permit TCP 31089 only from your current public IP. Open `http://YOUR_VM_IP:31089/`. Read `/opt/agentberth/work/microk8s-admin-key` in your private terminal and enter it in the console. HTTP does not encrypt the administration key or task data; use a domain and HTTPS ingress/reverse proxy before sending sensitive data. A domain-specific TLS setup can replace this temporary Service later. A Kubernetes `LoadBalancer` Service alone will not obtain a public IP on this self-managed VM.

## 9. Verify functionality and persistence

On the VM:

```bash
cd /opt/agentberth
export AGENTBERTH_ADMIN_KEY="$(cat work/microk8s-admin-key)"
python3 scripts/smoke.py --base-url http://127.0.0.1:31089
python3 scripts/example_concurrency.py --base-url http://127.0.0.1:31089
unset AGENTBERTH_ADMIN_KEY
```

If the node does not serve NodePort on loopback, use its private node IP shown by `microk8s kubectl get nodes -o wide`. These checks use no LLM credits. Expect three running tasks and two queued in the batch example. To watch the temporary task pods from another SSH terminal:

```bash
sudo microk8s kubectl -n agentberth-sandbox get pods --watch
```

Follow the [Kubernetes backend/isolation checks](kubernetes.md#verify-guiapi-parity-and-isolation) as well; do not assume a NetworkPolicy object proves enforcement. Check the PostgreSQL PV's host path points beneath your mounted volume. Once tasks have finished, reboot and verify that the volume mounts, MicroK8s returns to Ready, the console retains run history, and another demo succeeds. This VM setup has not been validated until those checks pass on your host.

For future configuration changes, edit `work/vm-values.yaml` and repeat the Helm command after active tasks finish. Use `execution.maxConcurrentRuns: 4` or `6` to change the limit; keep one coordinator worker. Follow [scheduling](scheduling.md#configuring-concurrency) for shutdown and queue semantics.

## References

- [Canonical MicroK8s installation](https://canonical.com/microk8s/docs/getting-started)
- [Canonical hostpath storage and custom storage paths](https://canonical.com/microk8s/docs/addon-hostpath-storage)
- [Canonical image side-loading](https://canonical.com/microk8s/docs/sideload)
- [DigitalOcean volume mounting](https://docs.digitalocean.com/products/volumes/how-to/mount-unmount/)
