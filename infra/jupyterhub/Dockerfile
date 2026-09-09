FROM quay.io/jupyterhub/jupyterhub:5.3.0
RUN python3 -m pip install --no-cache-dir dockerspawner==14.0.0

WORKDIR /srv/jupyterhub

COPY arena_auth.py jupyterhub_config.py storage.py ./

CMD ["jupyterhub", "-f", "/srv/jupyterhub/jupyterhub_config.py"]
