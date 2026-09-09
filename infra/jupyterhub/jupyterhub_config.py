import os
import sys

sys.path.insert(0, "/srv/jupyterhub")
from arena_auth import ArenaAuthenticator
from storage import prepare_workspace

c = get_config()  # noqa: F821 - provided by JupyterHub
c.JupyterHub.bind_url = "http://:8000/jupyter/"
c.JupyterHub.hub_ip = "0.0.0.0"
c.JupyterHub.hub_connect_ip = "jupyterhub"
c.JupyterHub.db_url = "sqlite:////data/jupyterhub.sqlite"
c.JupyterHub.cookie_secret_file = "/data/jupyterhub_cookie_secret"
c.JupyterHub.authenticator_class = ArenaAuthenticator
c.JupyterHub.spawner_class = "dockerspawner.DockerSpawner"
c.JupyterHub.tornado_settings = {
    "headers": {"Content-Security-Policy": "frame-ancestors 'self'"}
}
c.JupyterHub.redirect_to_server = False
c.JupyterHub.shutdown_on_logout = False
c.JupyterHub.cleanup_servers = True
c.JupyterHub.concurrent_spawn_limit = 5
c.JupyterHub.active_server_limit = 20

service_token = os.environ["JUPYTERHUB_API_TOKEN"]
if len(service_token) < 32:
    raise ValueError(
        "Generate JUPYTERHUB_API_TOKEN with scripts/configure_notebooks.py"
    )
c.JupyterHub.services = [{"name": "arena-api", "api_token": service_token}]
c.JupyterHub.load_roles = [
    {
        "name": "arena-notebook-manager",
        "services": ["arena-api"],
        "scopes": ["admin:users", "admin:servers", "access:servers"],
    }
]

c.DockerSpawner.image = os.environ.get("NOTEBOOK_IMAGE", "arena-singleuser:5.3.0")
c.DockerSpawner.pull_policy = "never"  # built by Compose before user sessions start
c.DockerSpawner.network_name = os.environ.get("DOCKER_NETWORK_NAME", "arena-notebooks")
c.DockerSpawner.use_internal_ip = True
c.DockerSpawner.remove = True
c.DockerSpawner.name_template = "arena-notebook-{username}"
c.DockerSpawner.notebook_dir = "/home/jovyan/work"
c.Spawner.pre_spawn_hook = prepare_workspace
c.DockerSpawner.mem_limit = "2G"
c.DockerSpawner.cpu_limit = 2
c.DockerSpawner.extra_host_config = {
    "pids_limit": 256,
    "cap_drop": ["ALL"],
    "security_opt": ["no-new-privileges:true"],
}
c.Spawner.environment = {
    "JUPYTERLAB_SETTINGS_DIR": "/home/jovyan/work/.jupyter/lab/user-settings",
    "JUPYTERLAB_WORKSPACES_DIR": "/home/jovyan/work/.jupyter/lab/workspaces",
    "IPYTHONDIR": "/home/jovyan/work/.ipython",
}
c.Spawner.default_url = "/lab"
c.Spawner.cmd = ["start-singleuser.py"]
c.Spawner.start_timeout = 180
c.Spawner.http_timeout = 60
