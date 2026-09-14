import os
import json
import sys

sys.path.insert(0, "/srv/jupyterhub")
from arena_auth import ArenaAuthenticator
from storage import prepare_workspace

GPU_RESOURCE = os.getenv("GPU_RESOURCE_NAME", "nvidia.com/gpu")


def json_env(name, default, kind):
    value = json.loads(os.getenv(name) or default)
    if not isinstance(value, kind):
        raise ValueError(f"{name} must be a JSON {kind.__name__}")
    return value


def notebook_gpu_count():
    """GPUs for one GPU session (NOTEBOOK_GPU_COUNT, default 1)."""
    count = int(os.getenv("NOTEBOOK_GPU_COUNT", "1"))
    if not 1 <= count <= 8:
        raise ValueError("NOTEBOOK_GPU_COUNT must be between 1 and 8")
    return count


def cpu_tolerations():
    """NOTEBOOK_TOLERATIONS without GPU tolerations: CPU sessions avoid GPU nodes."""
    return [
        item
        for item in json_env("NOTEBOOK_TOLERATIONS", "[]", list)
        if item.get("key") != GPU_RESOURCE
    ]


def gpu_tolerations():
    default = [{"key": GPU_RESOURCE, "operator": "Exists", "effect": "NoSchedule"}]
    return json_env("NOTEBOOK_GPU_TOLERATIONS", json.dumps(default), list)


def accelerator_option(user_options):
    """Validate user_options: only {"accelerator": "cpu" | "gpu"} is accepted.

    The Arena API is the only client allowed to start servers, but user_options
    arrive over the REST API and are validated here regardless.
    """
    options = user_options or {}
    if not isinstance(options, dict) or set(options) - {"accelerator"}:
        raise ValueError("Unsupported notebook server options")
    accelerator = options.get("accelerator", "cpu")
    if accelerator not in ("cpu", "gpu"):
        raise ValueError("accelerator must be cpu or gpu")
    return accelerator


def apply_kubernetes_options(spawner, user_options):
    """Request GPUs and tolerate the GPU taint only for GPU sessions.

    Every value is reset on each spawn because a user's spawner object is reused.
    """
    accelerator = accelerator_option(user_options)
    node_selector = json_env("NOTEBOOK_NODE_SELECTOR", "{}", dict)
    tolerations = cpu_tolerations()
    gpus = {}
    if accelerator == "gpu":
        node_selector.update(json_env("NOTEBOOK_GPU_NODE_SELECTOR", "{}", dict))
        tolerations += gpu_tolerations()
        gpus = {GPU_RESOURCE: str(notebook_gpu_count())}
    spawner.node_selector = node_selector
    spawner.tolerations = tolerations
    spawner.extra_resource_limits = gpus
    spawner.extra_resource_guarantees = dict(gpus)
    spawner.extra_labels = {"arena.notebook": "true", "arena.accelerator": accelerator}


def apply_docker_options(spawner, user_options):
    if accelerator_option(user_options) == "gpu":
        raise ValueError("GPU sessions require NOTEBOOK_SPAWNER=kubernetes")


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
    # Sessions default to CPU. GPUs are requested per session from the accelerator
    # user option; NOTEBOOK_GPUS no longer gives every session a GPU.
    c.KubeSpawner.node_selector = json_env("NOTEBOOK_NODE_SELECTOR", "{}", dict)
    c.KubeSpawner.tolerations = cpu_tolerations()
    gpu_tolerations()
    notebook_gpu_count()  # Fail at startup on invalid GPU settings.
    c.KubeSpawner.apply_user_options = apply_kubernetes_options
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
    c.DockerSpawner.apply_user_options = apply_docker_options
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
