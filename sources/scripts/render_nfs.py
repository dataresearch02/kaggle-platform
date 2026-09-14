#!/usr/bin/env python3
"""Render an optional NFS provisioner using an internal image and a root PVC."""

import argparse
import json


def render(args):
    ns = args.namespace
    name = f"{ns}-nfs"
    objects = []

    def add(kind, object_name, spec=None, api="v1", namespaced=True, **fields):
        metadata = {"name": object_name}
        if namespaced:
            metadata["namespace"] = ns
        item = {"apiVersion": api, "kind": kind, "metadata": metadata, **fields}
        if spec is not None:
            item["spec"] = spec
        objects.append(item)

    add("ServiceAccount", name)
    add(
        "PersistentVolume",
        f"{name}-root",
        {
            "capacity": {"storage": args.capacity},
            "accessModes": ["ReadWriteMany"],
            "persistentVolumeReclaimPolicy": "Retain",
            "storageClassName": "",
            "mountOptions": ["nfsvers=4.1"],
            "claimRef": {"namespace": ns, "name": f"{name}-root"},
            "nfs": {"server": args.server, "path": args.path},
        },
        namespaced=False,
    )
    add(
        "PersistentVolumeClaim",
        f"{name}-root",
        {
            "accessModes": ["ReadWriteMany"],
            "storageClassName": "",
            "volumeName": f"{name}-root",
            "resources": {"requests": {"storage": args.capacity}},
        },
    )
    rbac = "rbac.authorization.k8s.io/v1"
    add(
        "ClusterRole",
        name,
        api=rbac,
        namespaced=False,
        rules=[
            {
                "apiGroups": [""],
                "resources": ["nodes"],
                "verbs": ["get", "list", "watch"],
            },
            {
                "apiGroups": [""],
                "resources": ["persistentvolumes"],
                "verbs": ["get", "list", "watch", "create", "delete"],
            },
            {
                "apiGroups": [""],
                "resources": ["persistentvolumeclaims"],
                "verbs": ["get", "list", "watch", "update"],
            },
            {
                "apiGroups": ["storage.k8s.io"],
                "resources": ["storageclasses"],
                "verbs": ["get", "list", "watch"],
            },
            {
                "apiGroups": [""],
                "resources": ["events"],
                "verbs": ["create", "update", "patch"],
            },
        ],
    )
    subject = [{"kind": "ServiceAccount", "name": name, "namespace": ns}]
    add(
        "ClusterRoleBinding",
        name,
        api=rbac,
        namespaced=False,
        subjects=subject,
        roleRef={
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "ClusterRole",
            "name": name,
        },
    )
    add(
        "Role",
        name,
        api=rbac,
        rules=[
            {
                "apiGroups": [""],
                "resources": ["endpoints"],
                "verbs": ["get", "list", "watch", "create", "update", "patch"],
            }
        ],
    )
    add(
        "RoleBinding",
        name,
        api=rbac,
        subjects=subject,
        roleRef={"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": name},
    )
    provisioner = f"arena.internal/{name}"
    add(
        "StorageClass",
        args.storage_class,
        api="storage.k8s.io/v1",
        namespaced=False,
        provisioner=provisioner,
        reclaimPolicy="Retain",
        volumeBindingMode="Immediate",
        mountOptions=["nfsvers=4.1"],
        parameters={"archiveOnDelete": "true"},
    )
    add(
        "Deployment",
        name,
        {
            "replicas": 1,
            "strategy": {"type": "Recreate"},
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {"labels": {"app": name}},
                "spec": {
                    "serviceAccountName": name,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "provisioner",
                            "image": args.image,
                            "imagePullPolicy": "IfNotPresent",
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "resources": {
                                "requests": {"cpu": "50m", "memory": "64Mi"},
                                "limits": {"cpu": "500m", "memory": "256Mi"},
                            },
                            "env": [
                                {"name": "PROVISIONER_NAME", "value": provisioner},
                                {"name": "NFS_SERVER", "value": args.server},
                                {"name": "NFS_PATH", "value": args.path},
                            ],
                            "volumeMounts": [
                                {"name": "root", "mountPath": "/persistentvolumes"}
                            ],
                        }
                    ],
                    # PVC, not a direct Pod NFS volume; compatible with restricted SCC volume types.
                    "volumes": [
                        {
                            "name": "root",
                            "persistentVolumeClaim": {"claimName": f"{name}-root"},
                        }
                    ],
                },
            },
        },
        api="apps/v1",
    )
    return {"apiVersion": "v1", "kind": "List", "items": objects}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="arena")
    parser.add_argument("--server", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--storage-class", default="arena-nfs")
    parser.add_argument("--capacity", default="1Ti")
    args = parser.parse_args()
    if not args.path.startswith("/"):
        parser.error("--path must be an absolute NFS export path")
    print(json.dumps(render(args), indent=2))
