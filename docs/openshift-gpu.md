# The two notebook workflows and OpenShift GPU deployment

## Core workflows

1. **Personal notebook:** Create → Notebook → Add Input → select datasets, competition data or notebook outputs → run cells in the native editor → Save Version. Input versions are pinned under the notebook workspace's `input/<source-folder>/`. Saved documents, outputs and generated files survive closing the editor and restarting the personal server. Unsaved drafts expire and are discarded.
2. **Competition notebook:** Join → Code → New notebook. The draft retains the competition and attaches its public input files. Save Version → Save & Run All (Commit) now works on the first save. Arena saves a snapshot, queues it, starts a fresh isolated runtime, collects its submission CSV, scores it in the trusted backend and publishes the executed snapshot only after successful evaluation and artifact capture. A failed run leaves code private and does not create a score. Later edits do not change the published snapshot until another successful commit.

A competition needs configured local answer keys to score. The imported official Titanic competition has no private test answers; Arena deliberately does not invent a Titanic score. Use the seeded local practice competition for evaluation acceptance testing.

## Execution on OpenShift

Interactive sessions use [JupyterHub KubeSpawner](https://jupyterhub-kubespawner.readthedocs.io/en/latest/spawner.html), one persistent claim per user. The same Arena notebook API and frontend drive the kernel; no JupyterLab UI or generic file browser is exposed.

The evaluation broker supports `EVALUATION_RUNTIME=kubernetes` and creates [Kubernetes Jobs](https://kubernetes.io/docs/concepts/workloads/controllers/job/) with CPU/memory/GPU requests, a deadline, no automatic reruns, no service-account token, and only that job's working directory mounted. Scoring happens in the broker; answers and database credentials are never mounted in the execution Job. The generated NetworkPolicy denies all evaluation ingress and egress. Do not add policies that grant those pods network access: NetworkPolicy permissions are additive.

Keep **one evaluation-worker replica with Recreate rollout strategy**. It claims durable database jobs and processes competition commits serially; benchmark execution has a separate serial consumer. Startup removes its interrupted execution Jobs and marks interrupted runs failed for an explicit retry. Pending database jobs remain queued. This is not an HA scheduler, and a broker restart does not transparently resume in-progress Python execution.

## RTX 4090 and runtime images

Arena requests the standard `nvidia.com/gpu` resource. Your cluster must first advertise allocatable GPUs using a working NVIDIA driver/device-plugin setup. Check the [NVIDIA OpenShift support matrix](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/platform-support.html) for the exact operator/driver/platform combination; this implementation does not certify an RTX 4090 cluster configuration.

Use the **same CUDA runtime image for interactive notebooks and evaluation**. Build arguments permit a pinned PyTorch CUDA wheel; the build checks that PyTorch was compiled with CUDA. For example, PyTorch 2.14.0 CUDA 13.0 Python 3.12 wheels are published in the [official wheel index](https://download.pytorch.org/whl/cu130/torch/). Confirm driver compatibility before building. The GPU build also installs full `xgboost==3.4.1`; the default `xgboost-cpu` package cannot execute GPU training. XGBoost 3.4 uses CUDA 13 wheels; see [its release notes](https://xgboost.readthedocs.io/en/stable/changes/v3.4.0.html). Local Compose continues using its existing CPU image.

```bash
# Substitute your registry/repository and version tags. Push images separately.
docker build -t REGISTRY/arena-api:VERSION apps/api
docker build -t REGISTRY/arena-hub:VERSION infra/jupyterhub
docker build -t arena-web-build:VERSION apps/web
docker build -f apps/web/Dockerfile.openshift \
  --build-arg ARENA_WEB_IMAGE=arena-web-build:VERSION \
  -t REGISTRY/arena-web:VERSION apps/web
docker build -t REGISTRY/arena-runtime:VERSION \
  --build-arg PYTORCH_PACKAGE=torch==2.14.0 \
  --build-arg PYTORCH_INDEX_URL=https://download.pytorch.org/whl/cu130 \
  --build-arg XGBOOST_PACKAGE=xgboost==3.4.1 \
  --build-arg EXPECT_CUDA=true infra/singleuser
```

Images support [OpenShift-assigned UIDs](https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/html/images/creating-images). The web variant listens on port 8080. No privileged SCC or host Docker socket is requested.

## Render the deployment

Provide an existing namespace, registry pull access, an existing persistent PostgreSQL service/database, and a Secret named `arena-secrets` with `POSTGRES_PASSWORD` and a generated `JUPYTERHUB_API_TOKEN` of at least 32 characters. Store credentials through your cluster secret-management workflow, not in the manifest or Git. The renderer does not contact the cluster or generate credentials.

Storage requires:

- A **ReadWriteMany** StorageClass for shared platform data and evaluation job files. API, broker and Jobs may run on different nodes.
- A **ReadWriteOnce** StorageClass for Hub state and each user's workspace. Claims remain when personal servers stop.
- Storage supporting namespace fsGroup access and SELinux labeling. Verify the chosen CSI driver's subPath and fsGroup behavior with your cluster administrator.

```bash
python infra/openshift/render.py \
  --namespace arena \
  --hostname arena.apps.example.com \
  --api-image REGISTRY/arena-api:VERSION \
  --web-image REGISTRY/arena-web:VERSION \
  --hub-image REGISTRY/arena-hub:VERSION \
  --runtime-image REGISTRY/arena-runtime:VERSION \
  --postgres-host postgres.example.svc \
  --storage-class YOUR_RWO_CLASS \
  --shared-storage-class YOUR_RWX_CLASS \
  --notebook-gpus 0 --evaluation-gpus 1 \
  > /tmp/arena-openshift.json

# Validate against your cluster before applying.
oc apply --dry-run=server -f /tmp/arena-openshift.json
oc apply -f /tmp/arena-openshift.json
```

The example reserves the GPU for scheduled evaluation and uses CPU for interactive sessions. Set `--notebook-gpus 1` to enable interactive GPU training. **Each live interactive session holds its GPU**, even while idle. With one RTX 4090, an evaluation requesting that same GPU must wait until the interactive server releases it. Closing an editor does not stop its server. After queuing the commit, use **Run → Save and stop notebook server** to release the interactive GPU, or provide separate GPU capacity. This action stops all of your personal kernels after confirming; save any other open notebooks first. Arena does not silently terminate other notebooks to claim their GPU.

Both GPU counts default to zero. The renderer also accepts CPU, memory and timeout parameters. Default OpenShift limits are 2 CPUs, 8 GiB RAM, one hour per cell and two hours per competition Job. Quiet interactive execution sends heartbeat messages every 15 seconds to keep proxy connections alive. Node selectors/tolerations can be configured through `NOTEBOOK_NODE_SELECTOR`, `NOTEBOOK_TOLERATIONS`, `EVALUATION_NODE_SELECTOR` and `EVALUATION_TOLERATIONS` JSON environment values in `arena-config`.

The generated deployment contains API, web, Hub, broker, Services, Route, persistent claims, service accounts, RBAC and runtime NetworkPolicies. PostgreSQL, registry pull secrets, the GPU operator, storage provisioners and backups remain cluster infrastructure prerequisites. Before switching an existing local installation, migrate the PostgreSQL database and platform files together; local Hub SQLite state and bind-mounted personal workspaces must also be migrated deliberately into the new PVC layout.

## Acceptance on the target cluster

1. Confirm PVCs bind and all four platform Deployments become ready. Confirm runtime service accounts have no cluster API privileges.
2. Run the personal and competition workflows above through the HTTPS portal. Restart a test user's server and confirm saved cells, inputs and model files remain.
3. In a GPU notebook, execute:

   ```python
   import torch
   import numpy as np
   import xgboost as xgb
   assert torch.cuda.is_available()
   print(torch.cuda.get_device_name(0))
   model = torch.nn.Linear(2, 1).cuda()
   x = torch.ones((8, 2), device='cuda')
   optimizer = torch.optim.SGD(model.parameters(), lr=0.01)
   loss = model(x).square().mean()
   loss.backward()
   optimizer.step()
   xgb.XGBClassifier(tree_method='hist', device='cuda', n_estimators=2).fit(
       np.array([[0, 0], [1, 1], [0, 1], [1, 0]]), np.array([0, 1, 0, 1])
   )
   print('GPU_TRAINING_OK')
   ```

4. Commit a competition notebook containing a CUDA assertion and valid predictions. Confirm the execution Pod requests a GPU, contains no database/Hub secret environment variables, has no token mount, and cannot reach the network. Confirm score, published executed cells and outputs appear only after success.
5. Test missing predictions, Python errors, cancellation and timeout; none should publish a successful score. Stop the broker during a test run, restart it, and check the interrupted status and pending queue.

Local API, manifest-contract and browser checks do not replace this acceptance run. No OpenShift cluster or NVIDIA GPU is available in the current workspace, so cluster scheduling, GPU execution and CSI behavior have not been verified here.

## Checks completed in this workspace

- 154 API tests passed, including GPU Job request/isolation contracts, cleanup on failure/cancellation, runtime limits and rollback when output storage fails.
- The web production build passed.
- Browser acceptance passed for standalone input attachment/execution/persistence and competition join/first-save commit/failure/success/publication isolation. The existing real benchmark evaluation also passed through the shared runtime broker.
- The built Hub image accepted the KubeSpawner 7 configuration. The OpenShift web image's entrypoint and nginx configuration passed under arbitrary UID 123456 with group 0.
- The deployment renderer produced parameterized manifests locally. Server-side OpenShift validation and NVIDIA execution remain pending on the target cluster. The CUDA image build recipe is provided; that CUDA image has not been built or run here.
