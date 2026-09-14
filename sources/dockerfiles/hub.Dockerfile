FROM localhost/arena-offline-base/hub:bundle
RUN --mount=type=bind,source=python/hub,target=/wheels \
    python3 -m pip install --no-index --find-links=/wheels --no-cache-dir \
    dockerspawner==14.0.0 jupyterhub-kubespawner==7.0.0 && python3 -m pip check
WORKDIR /srv/jupyterhub
COPY project/infra/jupyterhub/arena_auth.py project/infra/jupyterhub/jupyterhub_config.py project/infra/jupyterhub/storage.py ./
RUN mkdir -p /data && chgrp -R 0 /data /srv/jupyterhub && chmod -R g=u /data /srv/jupyterhub
CMD ["jupyterhub", "-f", "/srv/jupyterhub/jupyterhub_config.py"]
