FROM quay.io/jupyter/scipy-notebook:2025-12-31
# Hub and single-user Hub components must use the same version.
RUN python -m pip install --no-cache-dir jupyterhub==5.3.0

# Use one scientific image for interactive notebooks and isolated evaluation.
# GPU builds set a compatible pinned torch package and CUDA wheel index.
ARG PYTORCH_PACKAGE=torch==2.14.0+cpu
ARG PYTORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG EXPECT_CUDA=false
ARG XGBOOST_PACKAGE=xgboost-cpu==3.4.1
COPY requirements-training.txt /tmp/requirements-training.txt
RUN python -m pip install --no-cache-dir "${PYTORCH_PACKAGE}" --index-url "${PYTORCH_INDEX_URL}" \
    && python -m pip install --no-cache-dir -r /tmp/requirements-training.txt "${XGBOOST_PACKAGE}" \
    && python -m pip check \
    && python -c "import torch, xgboost; assert bool(torch.version.cuda) == ('${EXPECT_CUDA}' == 'true'); assert '${EXPECT_CUDA}' != 'true' or xgboost.build_info().get('USE_CUDA'); print('PyTorch', torch.__version__, 'XGBoost', xgboost.__version__)"

COPY examples /opt/arena/examples

COPY jupyter_server_config.py /etc/jupyter/jupyter_server_config.py

COPY overrides.json /opt/conda/share/jupyter/lab/settings/overrides.json

# Match scientific thread pools to the two-CPU notebook limit. Multiple kernels
# share the container's PID budget, so host-sized pools can prevent kernel startup.
ENV OPENBLAS_NUM_THREADS=2 \
    OMP_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    NUMEXPR_NUM_THREADS=2

# OpenShift supplies a namespace UID; writable image directories belong to group 0.
USER root
RUN chgrp -R 0 /home/jovyan && chmod -R g=u /home/jovyan
USER 1000
