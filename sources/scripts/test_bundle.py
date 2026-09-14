"""Offline packaging and storage contracts; no cluster or container engine needed."""

import argparse
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bundle
import render_nfs


class BundleTests(unittest.TestCase):
    def test_checksums_cover_payload_but_exclude_logs_and_partial_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "images").mkdir()
            (root / "images/base.tar").write_bytes(b"image archive")
            (root / "images/base.partial").write_bytes(b"unfinished")
            (root / "logs").mkdir()
            (root / "logs/build.log").write_text("local log")
            with patch.object(bundle, "SOURCES", root):
                bundle.checksum()
                first = (root / "manifests/SHA256SUMS").read_text()
                bundle.checksum()
                self.assertEqual(first, (root / "manifests/SHA256SUMS").read_text())
            expected = hashlib.sha256(b"image archive").hexdigest()
            self.assertEqual(first, f"{expected}  images/base.tar\n")

    def nfs_objects(self):
        args = argparse.Namespace(
            namespace="arena-test",
            server="192.0.2.1",
            path="/export/arena",
            capacity="1Ti",
            image="registry.internal/nfs:v4.0.2",
            storage_class="test-nfs",
        )
        return {item["kind"]: item for item in render_nfs.render(args)["items"]}

    def test_nfs_provisioner_uses_bound_pvc_and_restricted_container(self):
        objects = self.nfs_objects()
        pod = objects["Deployment"]["spec"]["template"]["spec"]
        self.assertTrue(pod["securityContext"]["runAsNonRoot"])
        self.assertNotIn("runAsUser", pod["securityContext"])
        container = pod["containers"][0]
        self.assertEqual(container["image"], "registry.internal/nfs:v4.0.2")
        self.assertFalse(container["securityContext"]["allowPrivilegeEscalation"])
        self.assertEqual(container["securityContext"]["capabilities"]["drop"], ["ALL"])
        self.assertEqual(
            pod["volumes"][0]["persistentVolumeClaim"]["claimName"],
            objects["PersistentVolumeClaim"]["metadata"]["name"],
        )
        self.assertNotIn("nfs", pod["volumes"][0])
        self.assertEqual(
            objects["PersistentVolumeClaim"]["spec"]["storageClassName"], ""
        )

    def test_nfs_identity_retention_and_namespace_binding(self):
        objects = self.nfs_objects()
        storage = objects["StorageClass"]
        self.assertEqual(storage["reclaimPolicy"], "Retain")
        self.assertNotIn("namespace", storage["metadata"])
        env = {
            item["name"]: item["value"]
            for item in objects["Deployment"]["spec"]["template"]["spec"]["containers"][
                0
            ]["env"]
        }
        self.assertEqual(env["PROVISIONER_NAME"], storage["provisioner"])
        self.assertEqual(
            objects["PersistentVolume"]["spec"]["claimRef"]["namespace"], "arena-test"
        )
        self.assertEqual(
            objects["ClusterRoleBinding"]["subjects"][0]["namespace"], "arena-test"
        )


if __name__ == "__main__":
    unittest.main()
