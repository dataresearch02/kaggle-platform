"""Render an OpenShift deployment without contacting a cluster or embedding secrets."""

import argparse
import json


def render(args):
    ns = args.namespace
    objects = []

    def add(kind, name, spec=None, api="v1", **extra):
        item = {
            "apiVersion": api,
            "kind": kind,
            "metadata": {"name": name, "namespace": ns},
            **extra,
        }
        if spec is not None:
            item["spec"] = spec
        objects.append(item)
        return item

    for name in [
        "arena-api",
        "arena-hub",
        "arena-worker",
        "arena-runtime",
        "arena-web",
    ]:
        add("ServiceAccount", name, automountServiceAccountToken=False)
    for name, modes, size, storage in [
        (
            "arena-platform",
            ["ReadWriteMany"],
            args.platform_size,
            args.shared_storage_class,
        ),
        ("arena-hub", ["ReadWriteOnce"], "5Gi", args.storage_class),
    ]:
        add(
            "PersistentVolumeClaim",
            name,
            {
                "accessModes": modes,
                "storageClassName": storage,
                "resources": {"requests": {"storage": size}},
            },
        )
    config = {
        "DATA_DIR": "/data",
        "POSTGRES_HOST": args.postgres_host,
        "POSTGRES_USER": args.postgres_user,
        "POSTGRES_DB": args.postgres_db,
        "COOKIE_SECURE": "true",
        "ALLOWED_ORIGINS": f"https://{args.hostname}",
        "EVALUATION_BACKEND": "isolated",
        "EVALUATION_RUNTIME": "kubernetes",
        "EVALUATION_IMAGE": args.runtime_image,
        "EVALUATION_PVC": "arena-platform",
        "EVALUATION_GPUS": str(args.evaluation_gpus),
        "NOTEBOOK_GPUS": str(args.notebook_gpus),
        "GPU_RESOURCE_NAME": args.gpu_resource,
        "NOTEBOOK_IMAGE": args.runtime_image,
        "NOTEBOOK_SPAWNER": "kubernetes",
        "NOTEBOOK_STORAGE_CLASS": args.storage_class,
        "NOTEBOOK_STORAGE_CAPACITY": args.notebook_size,
        "NOTEBOOK_CPUS": str(args.cpus),
        "EVALUATION_CPUS": str(args.cpus),
        "NOTEBOOK_MEMORY": f"{args.memory_mb}M",
        "EVALUATION_MEMORY_MB": str(args.memory_mb),
        "NOTEBOOK_CELL_TIMEOUT_SECONDS": str(args.cell_timeout),
        "EVALUATION_TIMEOUT_SECONDS": str(args.job_timeout),
        "JUPYTERHUB_API_URL": "http://jupyterhub:8081/jupyter/hub/api",
        "JUPYTERHUB_PROXY_URL": "http://jupyterhub:8000/jupyter",
        "ARENA_API_URL": "http://api:8000/api",
        "HUB_CONNECT_HOST": "jupyterhub",
    }
    add("ConfigMap", "arena-config", data=config)
    security = {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}}

    def deployment(
        name,
        image,
        account,
        mounts=None,
        volumes=None,
        command=None,
        secrets=False,
        token=False,
        port=None,
        path=None,
    ):
        container = {
            "name": name,
            "image": image,
            "securityContext": security,
            "envFrom": [{"configMapRef": {"name": "arena-config"}}],
            "env": [
                {
                    "name": "POD_NAMESPACE",
                    "valueFrom": {"fieldRef": {"fieldPath": "metadata.namespace"}},
                }
            ],
            "resources": {
                "requests": {"cpu": "100m", "memory": "256Mi"},
                "limits": {"cpu": "2", "memory": "2Gi"},
            },
        }
        if secrets:
            container["envFrom"].append({"secretRef": {"name": args.secret}})
        if command:
            container["command"] = command
        if mounts:
            container["volumeMounts"] = mounts
        if port:
            container["ports"] = [{"containerPort": port}]
            container["readinessProbe"] = {
                "httpGet": {"path": path, "port": port},
                "initialDelaySeconds": 10,
                "periodSeconds": 5,
            }
        pod = {
            "serviceAccountName": account,
            "automountServiceAccountToken": token,
            "securityContext": {
                "runAsNonRoot": True,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "containers": [container],
            "terminationGracePeriodSeconds": 45,
        }
        if volumes:
            pod["volumes"] = volumes
        add(
            "Deployment",
            name,
            {
                "replicas": 1,
                "strategy": {"type": "Recreate"},
                "selector": {"matchLabels": {"app": name}},
                "template": {"metadata": {"labels": {"app": name}}, "spec": pod},
            },
            api="apps/v1",
        )

    platform_mount = [{"name": "platform", "mountPath": "/data"}]
    platform_volume = [
        {"name": "platform", "persistentVolumeClaim": {"claimName": "arena-platform"}}
    ]
    deployment(
        "api",
        args.api_image,
        "arena-api",
        platform_mount,
        platform_volume,
        secrets=True,
        port=8000,
        path="/api/health",
    )
    deployment(
        "evaluation-worker",
        args.api_image,
        "arena-worker",
        platform_mount,
        platform_volume,
        command=["python", "-m", "app.evaluation_worker"],
        secrets=True,
        token=True,
    )
    deployment(
        "jupyterhub",
        args.hub_image,
        "arena-hub",
        [{"name": "hub", "mountPath": "/data"}],
        [{"name": "hub", "persistentVolumeClaim": {"claimName": "arena-hub"}}],
        secrets=True,
        token=True,
        port=8081,
        path="/jupyter/hub/health",
    )
    deployment("web", args.web_image, "arena-web", port=8080, path="/")
    for name, ports in [("api", [8000]), ("jupyterhub", [8000, 8081]), ("web", [8080])]:
        add(
            "Service",
            name,
            {
                "selector": {"app": name},
                "ports": [
                    {"name": f"http-{p}", "port": p, "targetPort": p} for p in ports
                ],
            },
        )
    route = add(
        "Route",
        "arena",
        {
            "host": args.hostname,
            "to": {"kind": "Service", "name": "web"},
            "port": {"targetPort": "http-8080"},
            "tls": {"termination": "edge", "insecureEdgeTerminationPolicy": "Redirect"},
        },
        api="route.openshift.io/v1",
    )
    route["metadata"]["annotations"] = {"haproxy.router.openshift.io/timeout": "24h"}
    for name, rules in [
        (
            "arena-hub",
            [
                {
                    "apiGroups": [""],
                    "resources": ["pods", "persistentvolumeclaims", "services"],
                    "verbs": ["get", "list", "watch", "create", "delete", "patch"],
                },
                {
                    "apiGroups": [""],
                    "resources": ["events"],
                    "verbs": ["get", "list", "watch"],
                },
            ],
        ),
        (
            "arena-worker",
            [
                {
                    "apiGroups": ["batch"],
                    "resources": ["jobs"],
                    "verbs": ["get", "list", "create", "delete"],
                }
            ],
        ),
    ]:
        add("Role", name, api="rbac.authorization.k8s.io/v1", rules=rules)
        add(
            "RoleBinding",
            name,
            api="rbac.authorization.k8s.io/v1",
            roleRef={
                "apiGroup": "rbac.authorization.k8s.io",
                "kind": "Role",
                "name": name,
            },
            subjects=[{"kind": "ServiceAccount", "name": name, "namespace": ns}],
        )
    add(
        "NetworkPolicy",
        "arena-evaluations-isolated",
        {
            "podSelector": {"matchLabels": {"arena.evaluation": "true"}},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [],
            "egress": [],
        },
        api="networking.k8s.io/v1",
    )
    add(
        "NetworkPolicy",
        "arena-notebook-boundary",
        {
            "podSelector": {"matchLabels": {"arena.notebook": "true"}},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [
                {
                    "from": [
                        {"podSelector": {"matchLabels": {"app": name}}}
                        for name in ("api", "jupyterhub")
                    ],
                    "ports": [{"port": 8888, "protocol": "TCP"}],
                }
            ],
            "egress": [
                {
                    "to": [{"podSelector": {"matchLabels": {"app": "jupyterhub"}}}],
                    "ports": [{"port": 8081, "protocol": "TCP"}],
                },
                {
                    "to": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": "openshift-dns"
                                }
                            }
                        }
                    ],
                    "ports": [
                        {"port": port, "protocol": protocol}
                        for port in (53, 5353)
                        for protocol in ("UDP", "TCP")
                    ],
                },
            ],
        },
        api="networking.k8s.io/v1",
    )
    # Install runtime isolation and RBAC before any consumer can launch user code.
    order = {
        "ServiceAccount": 0,
        "Role": 1,
        "RoleBinding": 2,
        "NetworkPolicy": 3,
        "PersistentVolumeClaim": 4,
        "ConfigMap": 5,
        "Service": 6,
        "Deployment": 7,
        "Route": 8,
    }
    return {
        "apiVersion": "v1",
        "kind": "List",
        "items": sorted(objects, key=lambda item: order[item["kind"]]),
    }


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for key in (
        "namespace",
        "hostname",
        "api-image",
        "web-image",
        "hub-image",
        "runtime-image",
        "postgres-host",
        "storage-class",
        "shared-storage-class",
    ):
        p.add_argument(f"--{key}", required=True)
    for key, default in {
        "postgres-user": "arena",
        "postgres-db": "arena",
        "secret": "arena-secrets",
        "platform-size": "100Gi",
        "notebook-size": "20Gi",
        "gpu-resource": "nvidia.com/gpu",
    }.items():
        p.add_argument(f"--{key}", default=default)
    for key, default in {
        "notebook-gpus": 0,
        "evaluation-gpus": 0,
        "cpus": 2,
        "memory-mb": 8192,
        "cell-timeout": 3600,
        "job-timeout": 7200,
    }.items():
        p.add_argument(f"--{key}", type=int, default=default)
    return p


if __name__ == "__main__":
    arguments = parser().parse_args()
    if not (
        0 <= arguments.notebook_gpus <= 8
        and 0 <= arguments.evaluation_gpus <= 8
        and 1 <= arguments.cpus <= 256
        and 128 <= arguments.memory_mb <= 1048576
        and 1 <= arguments.cell_timeout <= arguments.job_timeout <= 86400
    ):
        raise SystemExit("Invalid GPU, CPU, memory, or timeout limits")
    print(json.dumps(render(arguments), indent=2))
