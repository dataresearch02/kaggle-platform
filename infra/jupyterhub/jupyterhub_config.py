import os
import json
import sys

sys.path.insert(0, "/srv/jupyterhub")
from arena_auth import ArenaAuthenticator
from storage import prepare_workspace

c = get_config()  # noqa: F821 - provided by JupyterHub
c.JupyterHub.bind_url = "http://:8000/jupyter/"
c.JupyterHub.hub_ip = "0.0.0.0"
c.JupyterHub.hub_connect_ip = os.getenv("HUB_CONNECT_HOST", "jupyterhub")
c.JupyterHub.db_url = "sqlite:////data/jupyterhub.sqlite"
c.JupyterHub.cookie_secret_file = "/data/jupyterhub_cookie_secret"
c.JupyterHub.authenticator_class = ArenaAuthenticator
c.JupyterHub.spawner_class = "dockerspawner.DockerSpawner"
c.JupyterHub.tornado_settings = {
    "headers": {"Content-Security-Policy": "frame-ancestors 'self'"}
}
c.JupyterHub.redirect_to_server = False
c.JupyterHub.shutdown_on_logout = False
c.JupyterHub.cleanup_servers = os.getenv("NOTEBOOK_SPAWNER") != "kubernetes"
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

if os.getenv("NOTEBOOK_SPAWNER", "docker") == "kubernetes":
    c.JupyterHub.spawner_class = "kubespawner.KubeSpawner"
    c.KubeSpawner.namespace = os.environ["POD_NAMESPACE"]
    c.KubeSpawner.image = os.environ["NOTEBOOK_IMAGE"]
    c.KubeSpawner.image_pull_policy = "IfNotPresent"
    c.KubeSpawner.uid = None
    c.KubeSpawner.gid = None
    c.KubeSpawner.fs_gid = None
    c.KubeSpawner.service_account = "arena-runtime"
    c.KubeSpawner.automount_service_account_token = False
    c.KubeSpawner.storage_pvc_ensure = True
    c.KubeSpawner.storage_class = os.environ["NOTEBOOK_STORAGE_CLASS"]
    c.KubeSpawner.storage_capacity = os.getenv("NOTEBOOK_STORAGE_CAPACITY", "20Gi")
    c.KubeSpawner.storage_access_modes = ["ReadWriteOnce"]
    c.KubeSpawner.pvc_name_template = "arena-work-{username}"
    c.KubeSpawner.delete_pvc = False
    c.KubeSpawner.notebook_dir = "/home/jovyan/work"
    c.KubeSpawner.volumes = [
        {
            "name": "work",
            "persistentVolumeClaim": {"claimName": "arena-work-{username}"},
        }
    ]
    c.KubeSpawner.volume_mounts = [{"name": "work", "mountPath": "/home/jovyan/work"}]
    c.KubeSpawner.cpu_limit = float(os.getenv("NOTEBOOK_CPUS", "2"))
    c.KubeSpawner.cpu_guarantee = c.KubeSpawner.cpu_limit
    c.KubeSpawner.mem_limit = os.getenv("NOTEBOOK_MEMORY", "8G")
    c.KubeSpawner.mem_guarantee = c.KubeSpawner.mem_limit
    c.KubeSpawner.extra_labels = {"arena.notebook": "true"}
    c.KubeSpawner.extra_pod_config = {
        "securityContext": {
            "runAsNonRoot": True,
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "automountServiceAccountToken": False,
    }
    c.KubeSpawner.container_security_context = {
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
    }
    c.KubeSpawner.node_selector = json.loads(os.getenv("NOTEBOOK_NODE_SELECTOR", "{}"))
    c.KubeSpawner.tolerations = json.loads(os.getenv("NOTEBOOK_TOLERATIONS", "[]"))
    gpu_count = int(os.getenv("NOTEBOOK_GPUS", "0"))
    if not 0 <= gpu_count <= 8:
        raise ValueError("NOTEBOOK_GPUS must be between 0 and 8")
    if gpu_count:
        gpu = {os.getenv("GPU_RESOURCE_NAME", "nvidia.com/gpu"): str(gpu_count)}
        c.KubeSpawner.extra_resource_limits = gpu
        c.KubeSpawner.extra_resource_guarantees = gpu
else:
    c.DockerSpawner.image = os.environ.get(
        "NOTEBOOK_IMAGE", "arena-singleuser:cpu-2026.09.1"
    )
    c.DockerSpawner.pull_policy = "never"  # built by Compose before user sessions start
    c.DockerSpawner.network_name = os.environ.get(
        "DOCKER_NETWORK_NAME", "arena-notebooks"
    )
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
c.Spawner.cmd = (
    ["jupyterhub-singleuser"]
    if os.getenv("NOTEBOOK_SPAWNER") == "kubernetes"
    else ["start-singleuser.py"]
)
c.Spawner.start_timeout = 180
c.Spawner.http_timeout = 60

if os.getenv("NOTEBOOK_SPAWNER") == "kubernetes":
    c.Spawner.environment.update(
        {
            "HOME": "/home/jovyan/work",
            "USER": "jovyan",
            "JUPYTER_RUNTIME_DIR": "/tmp/jupyter",
        }
    )
