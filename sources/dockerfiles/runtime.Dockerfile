FROM localhost/arena-offline-base/runtime:bundle
COPY project/infra/singleuser/requirements-training.txt /tmp/requirements-training.txt
RUN --mount=type=bind,source=python/runtime,target=/wheels \
    python -m pip install --no-index --find-links=/wheels --no-cache-dir \
    jupyterhub==5.3.0 torch==2.14.0+cu130 xgboost==3.4.1 -r /tmp/requirements-training.txt \
    && python -m pip check \
    && python -c "import torch, xgboost; assert torch.version.cuda; assert xgboost.build_info().get('USE_CUDA'); print(torch.__version__, torch.version.cuda, xgboost.__version__)"
COPY project/infra/singleuser/examples /opt/arena/examples
COPY project/infra/singleuser/jupyter_server_config.py /etc/jupyter/jupyter_server_config.py
COPY project/infra/singleuser/overrides.json /opt/conda/share/jupyter/lab/settings/overrides.json
ENV OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2
USER root
RUN chgrp -R 0 /home/jovyan && chmod -R g=u /home/jovyan
USER 1000
