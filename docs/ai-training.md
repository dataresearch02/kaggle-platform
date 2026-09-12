# CPU model training

Arena's shared training image includes pinned **PyTorch 2.14.0+cpu** and **XGBoost 3.4.1** (`xgboost-cpu`, imported as `xgboost`), alongside the existing NumPy, pandas, SciPy, scikit-learn and Jupyter packages. PyTorch comes from its [official CPU wheel index](https://pytorch.org/get-started/locally/); XGBoost uses its [documented CPU distribution](https://xgboost.readthedocs.io/en/stable/install.html).

The same `ARENA_RUNTIME_IMAGE` is used by JupyterHub and isolated evaluation jobs. Defaults are in Compose and `.env.example`. Framework versions are pinned in `infra/singleuser/Dockerfile` and `requirements-training.txt`; the build checks their imports and Python dependency compatibility.

## Use from a notebook

Run either example in a notebook code cell:

```python
%run /opt/arena/examples/pytorch_training.py --output-dir models/pytorch
%run /opt/arena/examples/xgboost_training.py --output-dir models/xgboost
```

The examples deliberately use generated binary classification data, with a separate validation split; their metrics are not Titanic competition scores.

Equivalent commands:

```python
%run /opt/arena/examples/pytorch_training.py --output-dir models/pytorch
%run /opt/arena/examples/xgboost_training.py --output-dir models/xgboost
```

Each example trains a real model, measures validation accuracy, saves a model and metrics, reloads the model, and checks that its predictions match. The PyTorch example also saves optimizer state and preprocessing statistics. Read and adapt the complete source in `infra/singleuser/examples/` for your own dataset.

Artifacts are saved under the current notebook working directory:

```text
models/
  pytorch/
    model.pt
    metrics.json
    validation_predictions.csv
  xgboost/
    model.ubj
    metrics.json
    validation_predictions.csv
```

In an interactive notebook, this directory is in the user's persistent workspace (`data/notebooks/arena-<user-id>/`). Kernel restart or container recreation preserves these files, but Python variables and unsaved editor changes do not persist. Saving a notebook stores its cells and outputs; model files persist separately in the workspace. Running examples again with the same output directory replaces their previous example artifacts; use a different `--output-dir` for another experiment.

## Install or upgrade

```bash
python scripts/containers.py up --build
```

The startup helper includes the evaluation worker on Podman as well as the application services. An existing notebook server keeps the image it was created with. Use **Run → Save and restart notebook server** to save the current notebook and receive a new image. Confirm only after saving other open notebooks: this stops all kernels in your workspace. Restarting only the Python kernel does not update installed packages.

## Current limits

This configuration remains CPU-only: 2 CPUs and 2 GiB RAM per interactive server and per isolated job. Interactive cell execution and isolated notebook cells have a 120-second limit; evaluation jobs also have an overall timeout. Keep training within these limits and checkpoint longer experiments in smaller steps. Isolated jobs run without network access and receive their input files before execution.

PyTorch and XGBoost enable model training and inference, with the local CPU configuration. For Kubernetes GPU scheduling, see [OpenShift GPU deployment](openshift-gpu.md). Distributed training, experiment tracking, and model-serving endpoints remain separate work. Titanic local scoring remains disabled because its official hidden answers were not imported. Competition scores and local training validation metrics remain separate.

## Verified workflows

The production image passed its dependency and import checks. Both examples trained and reloaded models in an offline, read-only container with 2 CPUs and 2 GiB RAM. The live browser test verified menu insertion, training, persisted model reload after server recreation, and isolated competition commits using both libraries. The CPU worker cancellation/isolation test and 20 targeted notebook/runtime API tests also passed.

For the current local rollout, the running Hub’s `arena-singleuser:5.3.0` compatibility tag points to the new CPU image; the old image remains tagged `arena-singleuser:legacy-5.3.0`. Existing server containers were left running. Future Compose startups use the explicitly versioned `ARENA_RUNTIME_IMAGE` setting.
