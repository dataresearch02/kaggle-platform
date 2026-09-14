# Arena disconnected installation kit

This directory is a transferable Linux **amd64/x86_64** build and deployment kit.
It contains application source, base image archives, Python wheels, an npm cache,
and application image archives built with networking disabled. The CUDA runtime
targets NVIDIA GPUs, including an RTX 4090 with a compatible host driver.

The actual payload lives here, not in Git. Copy the **whole `sources/` directory**
to the disconnected build/registry host, preserving its directory structure.

## Contents

| Directory         | Contents                                                                                                      |
| ----------------- | ------------------------------------------------------------------------------------------------------------- |
| `images/base/`    | Python, Node, nginx, JupyterHub, scientific notebook, PostgreSQL and optional NFS provisioner Docker archives |
| `images/arena/`   | Offline-built API/worker, Hub, OpenShift web and CUDA notebook/evaluation images                              |
| `python/api/`     | API dependencies and Python development tools, resolved for the API base Python                               |
| `python/hub/`     | DockerSpawner, KubeSpawner and dependencies, resolved for the Hub base Python                                 |
| `python/runtime/` | JupyterHub, CUDA PyTorch, full GPU XGBoost and their dependencies for the scientific image                    |
| `node/cache/`     | npm package tarballs and integrity metadata for frontend and repository tooling                               |
| `project/`        | Application/build source snapshot; no `.env`, live database, datasets or credentials                          |
| `dockerfiles/`    | Offline builds using only the supplied bases, wheels and npm cache                                            |
| `manifests/`      | Base image IDs/digests, Python inventories, source revision, build evidence and SHA-256 checksums             |
| `logs/`           | Local preparation/build logs; optional for transfer, excluded from checksums                                  |
| `scripts/`        | Connected preparation and disconnected load/build helpers                                                     |

NumPy, pandas, SciPy, scikit-learn, Jupyter and other existing scientific packages
are already inside the exported scientific base. Its Python inventory is in
`manifests/base-python-runtime.json`; the final inventory is `python-runtime.json`.
These packages do not need to be installed from the internet again.

Node dependencies are provided as an **npm cache**, not a host `node_modules/`
directory. The build runs `npm ci --offline` against the included lockfile in the
same Alpine environment used to collect the cache. Native dependencies for a
different OS or CPU architecture are not interchangeable.

## Load and deploy without rebuilding

On the disconnected Linux host, with Python 3.10+ and Podman already installed:

```bash
cd sources
sha256sum -c manifests/SHA256SUMS
python3 scripts/bundle.py load

# Authenticate to your internal registry using its normal login workflow first.
ARENA_REGISTRY=registry.internal.example/arena
ARENA_TAG=offline-v1
for component in api hub web runtime; do
  podman tag "localhost/arena-offline/$component:bundle" \
    "$ARENA_REGISTRY/arena-$component:$ARENA_TAG"
  podman push "$ARENA_REGISTRY/arena-$component:$ARENA_TAG"
done
```

Use these four internal image names with `project/infra/openshift/render.py`.
The API image also runs the evaluation worker. The runtime image runs both
interactive notebook kernels and scheduled competition/benchmark jobs.

```bash
python3 project/infra/openshift/render.py \
  --namespace arena \
  --hostname arena.apps.example.com \
  --api-image "$ARENA_REGISTRY/arena-api:$ARENA_TAG" \
  --web-image "$ARENA_REGISTRY/arena-web:$ARENA_TAG" \
  --hub-image "$ARENA_REGISTRY/arena-hub:$ARENA_TAG" \
  --runtime-image "$ARENA_REGISTRY/arena-runtime:$ARENA_TAG" \
  --postgres-host postgres.arena.svc.cluster.local \
  --storage-class YOUR_RWO_CLASS \
  --shared-storage-class YOUR_RWX_CLASS \
  --notebook-gpus 0 --evaluation-gpus 1 \
  > /tmp/arena-openshift.json

oc apply --dry-run=server -f /tmp/arena-openshift.json
oc apply -f /tmp/arena-openshift.json
```

Create the namespace, persistent PostgreSQL database, `arena-secrets`, and
internal registry pull credentials before deployment, as described in
`project/docs/openshift-gpu.md`. The cluster must trust your registry's TLS CA.
Link registry pull credentials to all five Arena service accounts, including
`arena-runtime`, so dynamically created notebook and evaluation pods can pull.

The included upstream `postgres:17-alpine` image matches local Compose. It is
**not** an OpenShift PostgreSQL Operator or an arbitrary-UID deployment recipe.
Use your cluster's existing persistent PostgreSQL service or an appropriately
configured PostgreSQL deployment. Do not assume this archive provisions a DB.

## Rebuild while disconnected

After loading the base archives:

```bash
python3 scripts/bundle.py build
python3 scripts/bundle.py export
python3 scripts/bundle.py checksum
```

Builds use `--network=none`, prohibit base pulls, and disable the layer cache.
Python uses `--no-index`; npm uses `--offline`. Dockerfiles require support for
`RUN --mount=type=bind` (modern Podman/Buildah or Docker BuildKit). They do not
fetch a Dockerfile frontend image. Dependency mounts keep the wheel archives
out of the final runtime layers.

Edit application files under `project/` when rebuilding on the disconnected
host. A dependency change requires a refreshed kit from a connected host.

## NFS on your OpenShift 4.20.36 cluster

Your NVIDIA GPU Operator and host drivers are already installed. This kit does
not reinstall them. If your NFS dynamic StorageClass already exists, use that
class for **both** `--storage-class` and `--shared-storage-class`; NFS supports
the requested RWO and RWX claims. No second provisioner is needed.

If only the NFS server exists, the kit includes the upstream
`nfs-subdir-external-provisioner:v4.0.2` image and `scripts/render_nfs.py`.
It creates directories on an **existing** NFS export; it does not install an
NFS server. The template uses a static root PV/PVC so its pod mounts a PVC,
runs with OpenShift's assigned UID and drops capabilities. It does not request
a privileged SCC or fixed root UID. Cluster RBAC/PV/StorageClass installation
requires a cluster administrator.

After `bundle.py load`, publish the provisioner to your internal registry:

```bash
podman tag localhost/arena-offline-base/nfs-provisioner:bundle \
  "$ARENA_REGISTRY/nfs-provisioner:v4.0.2"
podman push "$ARENA_REGISTRY/nfs-provisioner:v4.0.2"

# Create/select the arena project before applying these resources.
python3 scripts/render_nfs.py \
  --namespace arena \
  --server NFS_SERVER_ADDRESS \
  --path /YOUR/EXPORTED/ARENA/PATH \
  --image "$ARENA_REGISTRY/nfs-provisioner:v4.0.2" \
  --storage-class arena-nfs \
  > /tmp/arena-nfs.json
oc apply --dry-run=server -f /tmp/arena-nfs.json
oc apply -f /tmp/arena-nfs.json
# If authentication is needed, link your existing registry Secret:
oc secrets link arena-nfs arena-registry --for=pull -n arena
oc rollout status deployment/arena-nfs -n arena
```

Then render Arena with `--storage-class arena-nfs --shared-storage-class arena-nfs`.
The export must support NFS 4.1 and be reachable from all worker nodes. Configure
the export's ownership/ACLs on the **NFS server** so the OpenShift-assigned
provisioner identity can create directories. Preserve root squashing; do not
solve permission problems by making the provisioner privileged. Confirm API,
Hub and notebook pods can write their own claims and evaluation jobs can use
their `subPath` mounts with the namespace fsGroup. Confirm NFS locking and
durable writes work for Hub's SQLite state; keep regular backups.

The generated StorageClass uses `Retain`: deleting a claim does not erase its
underlying data. Administrators must reclaim retained volumes deliberately.
Requested capacities are metadata, **not NFS subdirectory quotas**. Monitor
server capacity. PostgreSQL requires storage meeting its durability and locking
requirements; reusing the application export is not a database backup strategy.
The NFS template has not been validated against your live cluster.

Upstream reference: https://github.com/kubernetes-sigs/nfs-subdir-external-provisioner

## Refresh on the connected preparation host

From the original repository root:

```bash
python3 sources/scripts/bundle.py all
```

The default engine is Podman. The preparation/export script uses Podman's
Docker-archive format, loadable with either Podman or Docker. It reuses existing
upstream base images and records their exact image IDs and available repository
digests rather than silently updating tags. To update a base, pull the intended
version explicitly before preparing a new kit. Keep a previous verified kit
until the replacement finishes validation.

`prepare` refreshes `project/` from tracked working-tree application files.
Commit new application files before refreshing, or deliberately add them to
the snapshot afterward and rebuild. Live storage and credentials must be
backed up/migrated separately. Dependency archives and source snapshots are
ignored by Git to avoid adding large binaries or stale source copies.

## Disconnected runtime boundaries

- Host NVIDIA driver, GPU Operator, NFD, their operand images, other storage operators,
  the OpenShift release payload and registry infrastructure are **not included**.
  Your GPU stack is already installed; mirroring future upgrades depends on the
  exact operator versions and host kernel. The optional NFS provisioner is included.
  A CUDA runtime container does not install the host driver.
- The runtime includes CUDA 13 PyTorch and GPU XGBoost. Confirm your installed
  driver is compatible. The build checks CUDA-enabled package imports; actual
  RTX 4090 execution must be tested on the target cluster.
- With one GPU, start with CPU interactive sessions and GPU evaluation jobs.
  A GPU interactive server holds the card until stopped; queue the commit then
  use **Run → Save and stop notebook server** to let its evaluation acquire it.
- Model weights, user datasets, existing notebook files and remote media are
  data, not application dependencies. Import or migrate the ones you need.
  Code that downloads a model or calls `pip install` online must instead use
  pre-staged local files/packages. No arbitrary future model is bundled.
- Public API model providers and internet links cannot work without internet
  access. Use local models or reachable internal API providers. Arena's isolated
  evaluation pods intentionally have no network access; provider requests, when
  configured, go through the trusted broker.
- Playwright's npm package is cached, but browser binaries and a browser testing
  OS image are not required to build/run Arena and are not bundled.
- All package downloads need to finish and the four offline builds need to pass
  before transfer. `manifests/offline-build.json` records a successful build;
  `manifests/SHA256SUMS` verifies the complete payload after transfer.
