#!/usr/bin/env python3
"""Apply the ocp4.lab.local fixes and extras to render.py output (stdin -> stdout)."""

import hashlib
import json
import sys

GPU_TOLERATIONS = [{"key": "nvidia.com/gpu", "operator": "Exists", "effect": "NoSchedule"}]

# The image's config proxies to "api", but nginx resolves upstream names with its
# own resolver, which ignores resolv.conf search domains. Use the service FQDN.
WEB_SITE = """map $http_upgrade $connection_upgrade {
    default upgrade;
    '' close;
}

server {
    listen 8080;
    server_name _;
    root /usr/share/nginx/html;
    client_max_body_size 11m;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options SAMEORIGIN always;

    location /api/ {
        set $arena_api api.%(namespace)s.svc.cluster.local:8000;
        proxy_pass http://$arena_api;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 180;
        proxy_buffering off;
    }

    # Notebook files and kernel traffic go through notebook-scoped Arena APIs.
    # Do not expose JupyterLab or its generic file browser to website users.
    location /jupyter { return 404; }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
"""


def find(items, kind, name):
    return next(i for i in items if i["kind"] == kind and i["metadata"]["name"] == name)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]


def restart_on_change(deployment, value):
    template = deployment["spec"]["template"]["metadata"]
    template.setdefault("annotations", {})["arena.config-hash"] = digest(value)


def main():
    doc = json.load(sys.stdin)
    items = doc["items"]
    namespace = items[0]["metadata"]["namespace"]

    config = find(items, "ConfigMap", "arena-config")["data"]
    # Service "postgres" makes Kubernetes inject POSTGRES_PORT=tcp://IP:5432,
    # which the API parses as an integer. Explicit env overrides service links.
    config["POSTGRES_PORT"] = "5432"
    # The only GPU node (worker1) carries an nvidia.com/gpu NoSchedule taint.
    config["EVALUATION_TOLERATIONS"] = json.dumps(GPU_TOLERATIONS)

    # KubeSpawner labels every user notebook pod app=jupyterhub, so selecting the
    # Hub by that label puts notebook pods behind the jupyterhub Service and lets
    # notebooks reach each other on 8888. Select the Hub by a label of its own.
    hub = find(items, "Deployment", "jupyterhub")
    hub["spec"]["template"]["metadata"]["labels"]["arena.hub"] = "true"
    find(items, "Service", "jupyterhub")["spec"]["selector"] = {
        "app": "jupyterhub",
        "arena.hub": "true",
    }
    boundary = find(items, "NetworkPolicy", "arena-notebook-boundary")["spec"]
    for rule in boundary["ingress"] + boundary["egress"]:
        for peer in rule.get("from", []) + rule.get("to", []):
            labels = peer.get("podSelector", {}).get("matchLabels", {})
            if labels.get("app") == "jupyterhub":
                labels["arena.hub"] = "true"

    # The API server drops empty rule lists, so applying them again always shows a
    # change. With policyTypes set, an absent list still denies all traffic.
    for policy in (i for i in items if i["kind"] == "NetworkPolicy"):
        for direction in ("ingress", "egress"):
            if policy["spec"].get(direction) == []:
                del policy["spec"][direction]

    site = WEB_SITE % {"namespace": namespace}
    web = find(items, "Deployment", "web")
    pod = web["spec"]["template"]["spec"]
    pod["volumes"] = [{"name": "nginx-site", "configMap": {"name": "arena-web-nginx"}}]
    pod["containers"][0]["volumeMounts"] = [
        {
            "name": "nginx-site",
            "mountPath": "/etc/nginx/conf.d/default.conf",
            "subPath": "default.conf",
            "readOnly": True,
        }
    ]
    kinds = [i["kind"] for i in items]
    items.insert(
        kinds.index("ConfigMap") + 1,
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "arena-web-nginx", "namespace": namespace},
            "data": {"default.conf": site},
        },
    )

    # envFrom/ConfigMap changes do not restart pods on their own.
    for name in ("api", "evaluation-worker", "jupyterhub"):
        restart_on_change(find(items, "Deployment", name), config)
    restart_on_change(web, site)

    # Keep the multi-GB runtime image cached on every node so notebook spawns do
    # not exceed JupyterHub's 180 s start timeout.
    items.insert(
        len(items) - 1 if items[-1]["kind"] == "Route" else len(items),
        {
            "apiVersion": "apps/v1",
            "kind": "DaemonSet",
            "metadata": {"name": "arena-runtime-prepull", "namespace": namespace},
            "spec": {
                "selector": {"matchLabels": {"app": "arena-runtime-prepull"}},
                "updateStrategy": {
                    "type": "RollingUpdate",
                    "rollingUpdate": {"maxUnavailable": "100%"},
                },
                "template": {
                    "metadata": {"labels": {"app": "arena-runtime-prepull"}},
                    "spec": {
                        "serviceAccountName": "arena-runtime",
                        "automountServiceAccountToken": False,
                        "securityContext": {
                            "runAsNonRoot": True,
                            "seccompProfile": {"type": "RuntimeDefault"},
                        },
                        "tolerations": GPU_TOLERATIONS,
                        "containers": [
                            {
                                "name": "prepull",
                                "image": config["NOTEBOOK_IMAGE"],
                                "imagePullPolicy": "IfNotPresent",
                                "command": ["sleep", "infinity"],
                                "resources": {
                                    "requests": {"cpu": "1m", "memory": "16Mi"},
                                    "limits": {"cpu": "10m", "memory": "32Mi"},
                                },
                                "securityContext": {
                                    "allowPrivilegeEscalation": False,
                                    "capabilities": {"drop": ["ALL"]},
                                },
                            }
                        ],
                    },
                },
            },
        },
    )
    json.dump(doc, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
