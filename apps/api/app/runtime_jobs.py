"""Trusted broker for disposable Docker containers or Kubernetes Jobs.

Only a single evaluation directory is exposed to untrusted code. The database,
answer keys, service account credentials and other users' data stay in the broker.
"""

import asyncio
import contextlib
import json
import os
import re
from pathlib import Path

import httpx


def integer(name, default, minimum=1, maximum=86400):
    value = int(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def kubernetes():
    value = os.getenv("EVALUATION_RUNTIME", "docker")
    if value not in ("docker", "kubernetes"):
        raise ValueError("EVALUATION_RUNTIME must be docker or kubernetes")
    return value == "kubernetes"


def resources():
    return {
        "cpu": str(integer("EVALUATION_CPUS", 2, maximum=256)),
        "memory": f"{integer('EVALUATION_MEMORY_MB', 2048, maximum=1048576)}Mi",
    }


def prepare_permissions(work):
    for path in [work, *work.rglob("*")]:
        if kubernetes():
            # OpenShift assigns UIDs and the namespace's shared fsGroup. Do not chown.
            path.chmod(0o2770 if path.is_dir() else 0o660)
        elif os.geteuid() == 0:
            os.chown(path, 10001, 10001)


def job_manifest(name, directory, env, timeout):
    if not re.fullmatch(r"(?:job|benchmark)-\d+-[0-9a-f]+", directory):
        raise ValueError("Invalid evaluation directory")
    limits = resources()
    gpu = integer("EVALUATION_GPUS", 0, minimum=0, maximum=8)
    if gpu:
        limits[os.getenv("GPU_RESOURCE_NAME", "nvidia.com/gpu")] = str(gpu)
    labels = {
        "arena.evaluation": "true",
        "arena.installation": os.getenv("ARENA_INSTALLATION", "arena"),
    }
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": name, "labels": labels},
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": timeout,
            "ttlSecondsAfterFinished": 3600,
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "serviceAccountName": os.getenv(
                        "EVALUATION_SERVICE_ACCOUNT", "arena-runtime"
                    ),
                    "securityContext": {
                        "runAsNonRoot": True,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "nodeSelector": json.loads(
                        os.getenv("EVALUATION_NODE_SELECTOR", "{}")
                    ),
                    "tolerations": json.loads(
                        os.getenv("EVALUATION_TOLERATIONS", "[]")
                    ),
                    "containers": [
                        {
                            "name": "notebook",
                            "image": os.environ["EVALUATION_IMAGE"],
                            "command": ["python", "/work/runner.py"],
                            "workingDir": "/work",
                            "env": [
                                {"name": key, "value": value}
                                for key, value in env.items()
                            ],
                            "resources": {"requests": limits.copy(), "limits": limits},
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "volumeMounts": [
                                {
                                    "name": "work",
                                    "mountPath": "/work",
                                    "subPath": f"evaluations/{directory}",
                                },
                                {"name": "tmp", "mountPath": "/tmp"},
                                {"name": "shm", "mountPath": "/dev/shm"},
                            ],
                        }
                    ],
                    "volumes": [
                        {
                            "name": "work",
                            "persistentVolumeClaim": {
                                "claimName": os.environ["EVALUATION_PVC"]
                            },
                        },
                        {"name": "tmp", "emptyDir": {"sizeLimit": "1Gi"}},
                        {
                            "name": "shm",
                            "emptyDir": {"medium": "Memory", "sizeLimit": "256Mi"},
                        },
                    ],
                },
            },
        },
    }


def cluster_client():
    root = Path(
        os.getenv(
            "KUBERNETES_SERVICEACCOUNT_PATH",
            "/var/run/secrets/kubernetes.io/serviceaccount",
        )
    )
    namespace = os.getenv("POD_NAMESPACE") or (root / "namespace").read_text().strip()
    client = httpx.AsyncClient(
        base_url=f"https://{os.environ['KUBERNETES_SERVICE_HOST']}:{os.getenv('KUBERNETES_SERVICE_PORT', '443')}",
        verify=str(root / "ca.crt"),
        timeout=30,
        # Token rotation is handled by refreshing this header before every request.
    )
    return client, root, f"/apis/batch/v1/namespaces/{namespace}/jobs"


async def cluster_request(client, root, method, path, **kwargs):
    return await client.request(
        method,
        path,
        headers={"Authorization": "Bearer " + (root / "token").read_text().strip()},
        **kwargs,
    )


async def run_kubernetes(name, work, env, timeout, active):
    client, root, base = cluster_client()
    created = False
    async with client:
        try:
            result = await cluster_request(
                client,
                root,
                "POST",
                base,
                json=job_manifest(name, work.name, env, timeout),
            )
            result.raise_for_status()
            created = True
            while True:
                if not active():
                    raise ValueError("Evaluation cancelled")
                result = await cluster_request(client, root, "GET", f"{base}/{name}")
                result.raise_for_status()
                status = result.json().get("status", {})
                if status.get("succeeded"):
                    return
                failed = next(
                    (
                        item
                        for item in status.get("conditions", [])
                        if item["type"] == "Failed" and item["status"] == "True"
                    ),
                    None,
                )
                if failed:
                    raise ValueError(
                        f"Evaluation Job failed: {failed.get('reason', 'Execution error')}. Check runtime logs and resource limits."
                    )
                await asyncio.sleep(1)
        finally:
            if created:
                with contextlib.suppress(Exception):
                    await cluster_request(
                        client,
                        root,
                        "DELETE",
                        f"{base}/{name}",
                        json={
                            "propagationPolicy": "Foreground",
                            "gracePeriodSeconds": 0,
                        },
                    )


async def run_docker(name, work, env, timeout, active):
    host = Path(os.environ["EVALUATION_HOST_PATH"])
    if not host.is_absolute():
        raise ValueError("EVALUATION_HOST_PATH must be absolute")
    if integer("EVALUATION_GPUS", 0, minimum=0, maximum=8):
        raise ValueError("GPU evaluation requires EVALUATION_RUNTIME=kubernetes")
    transport = httpx.AsyncHTTPTransport(
        uds=os.getenv("DOCKER_SOCKET_PATH", "/var/run/docker.sock")
    )
    async with httpx.AsyncClient(
        transport=transport, base_url="http://docker", timeout=30
    ) as docker:
        created = False
        try:
            response = await docker.post(
                "/containers/create",
                params={"name": name},
                json={
                    "Image": os.getenv(
                        "EVALUATION_IMAGE", "arena-singleuser:cpu-2026.09.1"
                    ),
                    "User": "10001:10001",
                    "WorkingDir": "/work",
                    "Entrypoint": ["python"],
                    "Cmd": ["/work/runner.py"],
                    "Env": [f"{key}={value}" for key, value in env.items()],
                    "Labels": {"arena.evaluation": "true"},
                    "HostConfig": {
                        "NetworkMode": "none",
                        "ReadonlyRootfs": True,
                        "Binds": [f"{host / work.name}:/work:rw,z"],
                        "Tmpfs": {"/tmp": "rw,nosuid,nodev,size=268435456"},
                        "Memory": integer("EVALUATION_MEMORY_MB", 2048, maximum=1048576)
                        * 1024
                        * 1024,
                        "NanoCpus": integer("EVALUATION_CPUS", 2, maximum=256)
                        * 1000000000,
                        "PidsLimit": 256,
                        "CapDrop": ["ALL"],
                        "SecurityOpt": ["no-new-privileges:true"],
                        "LogConfig": {
                            "Type": "json-file",
                            "Config": {"max-size": "1m", "max-file": "1"},
                        },
                    },
                },
            )
            response.raise_for_status()
            created = True
            (await docker.post(f"/containers/{name}/start")).raise_for_status()
            while True:
                if not active():
                    raise ValueError("Evaluation cancelled")
                response = await docker.get(f"/containers/{name}/json")
                response.raise_for_status()
                state = response.json()["State"]
                if not state["Running"]:
                    if state.get("OOMKilled"):
                        raise ValueError("Evaluation exceeded its memory limit")
                    if state.get("ExitCode") != 0:
                        raise ValueError(
                            "Notebook execution failed. Run the notebook interactively to inspect Python errors."
                        )
                    return
                await asyncio.sleep(1)
        finally:
            if created:
                with contextlib.suppress(Exception):
                    await docker.delete(f"/containers/{name}", params={"force": "true"})


async def run(name, work, env, timeout, active):
    prepare_permissions(work)
    defaults = {
        "HOME": "/tmp",
        "USER": "arena",
        "JUPYTER_RUNTIME_DIR": "/tmp/jupyter",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": str(integer("EVALUATION_CPUS", 2, maximum=256)),
        "OPENBLAS_NUM_THREADS": str(integer("EVALUATION_CPUS", 2, maximum=256)),
    }
    await asyncio.wait_for(
        (run_kubernetes if kubernetes() else run_docker)(
            name, work, {**defaults, **env}, timeout, active
        ),
        timeout=timeout,
    )


async def cleanup():
    """Single-consumer startup recovery; never scale this broker above one replica."""
    if kubernetes():
        client, root, base = cluster_client()
        async with client:
            selector = f"arena.evaluation=true,arena.installation={os.getenv('ARENA_INSTALLATION', 'arena')}"
            response = await cluster_request(
                client, root, "GET", base, params={"labelSelector": selector}
            )
            response.raise_for_status()
            for job in response.json()["items"]:
                deleted = await cluster_request(
                    client,
                    root,
                    "DELETE",
                    f"{base}/{job['metadata']['name']}",
                    json={"propagationPolicy": "Foreground", "gracePeriodSeconds": 0},
                )
                if deleted.status_code != 404:
                    deleted.raise_for_status()
    else:
        transport = httpx.AsyncHTTPTransport(
            uds=os.getenv("DOCKER_SOCKET_PATH", "/var/run/docker.sock")
        )
        async with httpx.AsyncClient(
            transport=transport, base_url="http://docker", timeout=30
        ) as docker:
            response = await docker.get(
                "/containers/json",
                params={
                    "all": "true",
                    "filters": '{"label":["arena.evaluation=true"]}',
                },
            )
            response.raise_for_status()
            for container in response.json():
                (
                    await docker.delete(
                        f"/containers/{container['Id']}", params={"force": "true"}
                    )
                ).raise_for_status()
