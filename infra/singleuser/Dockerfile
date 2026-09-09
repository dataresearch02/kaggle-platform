FROM quay.io/jupyter/scipy-notebook:2025-12-31
# Hub and single-user Hub components must use the same version.
RUN python -m pip install --no-cache-dir jupyterhub==5.3.0

COPY jupyter_server_config.py /etc/jupyter/jupyter_server_config.py

COPY overrides.json /opt/conda/share/jupyter/lab/settings/overrides.json
