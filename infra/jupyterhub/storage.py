"""Per-user bind directories for the local DockerSpawner deployment."""

import os
from pathlib import Path
import re


def prepare_workspace(spawner):
    name = spawner.user.name
    if not re.fullmatch(r"arena-\d+", name):
        raise ValueError("Unexpected Arena Hub username")
    host_root = Path(os.environ["NOTEBOOKS_HOST_PATH"])
    if not host_root.is_absolute():
        raise ValueError("NOTEBOOKS_HOST_PATH must be an absolute host path")
    local = Path("/notebooks") / name
    if local.is_symlink():
        raise ValueError("Notebook workspace must not be a symlink")
    local.mkdir(mode=0o700, exist_ok=True)
    os.chown(local, 1000, 100)
    spawner.volumes = {
        str(host_root / name): {"bind": "/home/jovyan/work", "mode": "rw,z"}
    }
