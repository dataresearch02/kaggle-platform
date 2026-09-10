FROM quay.io/jupyter/scipy-notebook:2025-12-31
# Hub and single-user Hub components must use the same version.
RUN python -m pip install --no-cache-dir jupyterhub==5.3.0

COPY jupyter_server_config.py /etc/jupyter/jupyter_server_config.py

COPY overrides.json /opt/conda/share/jupyter/lab/settings/overrides.json

# Match scientific thread pools to the two-CPU notebook limit. Multiple kernels
# share the container's PID budget, so host-sized pools can prevent kernel startup.
ENV OPENBLAS_NUM_THREADS=2 \
    OMP_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    NUMEXPR_NUM_THREADS=2
