#!/usr/bin/env python3
"""Prepare and verify an Arena offline kit without copying deployment secrets."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone

SOURCES = Path(__file__).resolve().parents[1]
ROOT = SOURCES.parent
BASES = {
    "python": "docker.io/library/python:3.12-slim",
    "hub": "quay.io/jupyterhub/jupyterhub:5.3.0",
    "runtime": "quay.io/jupyter/scipy-notebook:2025-12-31",
    "node": "docker.io/library/node:22-alpine",
    "nginx": "docker.io/library/nginx:1.28-alpine",
    "postgres": "docker.io/library/postgres:17-alpine",
    "nfs-provisioner": "registry.k8s.io/sig-storage/nfs-subdir-external-provisioner:v4.0.2",
}
COMPONENTS = ("api", "hub", "web", "runtime")
ENGINE = os.environ.get("CONTAINER_ENGINE", "podman")


def run(*args, capture=False):
    print("+", " ".join(str(arg) for arg in args), flush=True)
    result = subprocess.run(
        [str(arg) for arg in args],
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout if capture else None


def base(name):
    return f"localhost/arena-offline-base/{name}:bundle"


def app(name):
    return f"localhost/arena-offline/{name}:bundle"


def write_json(name, value):
    path = SOURCES / "manifests" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def snapshot():
    # Only repository-controlled application/build files, never working data or env.
    files = run("git", "-C", ROOT, "ls-files", "-z", capture=True).split("\0")
    destination = SOURCES / "project"
    if destination.exists():
        shutil.rmtree(destination)
    allowed = ("apps/", "infra/", "scripts/", "docs/")
    for name in files:
        if not name or not (
            name.startswith(allowed)
            or name
            in (
                "README.md",
                "package.json",
                "package-lock.json",
                "compose.yaml",
                "Makefile",
            )
        ):
            continue
        source = ROOT / name
        if source.is_symlink() or not source.is_file():
            continue
        if any(
            part.startswith(".env") or part in ("node_modules", "data", ".git")
            for part in Path(name).parts
        ):
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    write_json(
        "source.json",
        {
            "git_commit": run(
                "git", "-C", ROOT, "rev-parse", "HEAD", capture=True
            ).strip(),
            "note": "Snapshot of tracked working-tree files; may include uncommitted edits. No live data or credentials.",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def save_image(image, path):
    temporary = path.with_suffix(".partial")
    run(ENGINE, "save", "--format", "docker-archive", "-o", temporary, image)
    temporary.replace(path)


def bases():
    images = SOURCES / "images" / "base"
    images.mkdir(parents=True, exist_ok=True)
    inventory = []
    for name, reference in BASES.items():
        try:
            metadata = json.loads(
                run(ENGINE, "image", "inspect", reference, capture=True)
            )[0]
        except subprocess.CalledProcessError:
            run(ENGINE, "pull", "--platform", "linux/amd64", reference)
            metadata = json.loads(
                run(ENGINE, "image", "inspect", reference, capture=True)
            )[0]
        if metadata["Architecture"] != "amd64" or metadata["Os"] != "linux":
            raise RuntimeError(
                f"Wrong architecture for {reference}; linux/amd64 required"
            )
        run(ENGINE, "tag", metadata["Id"], base(name))
        archive = images / f"{name}.tar"
        record = {
            "name": name,
            "upstream": reference,
            "offline_tag": base(name),
            "image_id": metadata["Id"],
            "repo_digests": metadata.get("RepoDigests", []),
        }
        # Never reuse an archive if its source image has changed.
        marker = images / f"{name}.json"
        if (
            not archive.exists()
            or not marker.exists()
            or json.loads(marker.read_text())["image_id"] != record["image_id"]
        ):
            save_image(base(name), archive)
            marker.write_text(json.dumps(record, indent=2) + "\n")
        inventory.append(record)
    write_json("base-images.json", inventory)


def prepare():
    snapshot()
    bases()
    requirements = {
        "api": ["-r", "/bundle/project/apps/api/requirements-dev.txt"],
        "hub": ["dockerspawner==14.0.0", "jupyterhub-kubespawner==7.0.0"],
        "runtime": [
            "jupyterhub==5.3.0",
            "torch==2.14.0+cu130",
            "xgboost==3.4.1",
            "-r",
            "/bundle/project/infra/singleuser/requirements-training.txt",
            "--extra-index-url",
            "https://download.pytorch.org/whl/cu130",
        ],
    }
    for name, packages in requirements.items():
        wheelhouse = SOURCES / "python" / name
        wheelhouse.mkdir(parents=True, exist_ok=True)
        image = base("python" if name == "api" else name)
        run(
            ENGINE,
            "run",
            "--rm",
            "--user",
            "0:0",
            "--entrypoint",
            "python3",
            "-v",
            f"{SOURCES}:/bundle:rw",
            image,
            "-m",
            "pip",
            "download",
            "--only-binary=:all:",
            "--disable-pip-version-check",
            "--dest",
            f"/bundle/python/{name}",
            *packages,
        )
        installed = run(
            ENGINE,
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "python3",
            image,
            "-m",
            "pip",
            "list",
            "--format=json",
            capture=True,
        )
        write_json(f"base-python-{name}.json", json.loads(installed))

    (SOURCES / "node" / "cache").mkdir(parents=True, exist_ok=True)
    # Install inside Alpine, not on the host: Vite/Rollup/esbuild have platform binaries.
    run(
        ENGINE,
        "run",
        "--rm",
        "--user",
        "0:0",
        "--entrypoint",
        "sh",
        "-v",
        f"{SOURCES}:/bundle:rw",
        base("node"),
        "-ec",
        """
        mkdir -p /tmp/web /tmp/root
        cp /bundle/project/apps/web/package*.json /tmp/web/
        cd /tmp/web
        npm ci --cache /bundle/node/cache --no-audit --no-fund
        cp /bundle/project/package*.json /tmp/root/
        cd /tmp/root
        npm ci --cache /bundle/node/cache --no-audit --no-fund
        npm cache verify --cache /bundle/node/cache
        """,
    )
    # npm debug logs can contain network configuration; they are not part of the kit.
    shutil.rmtree(SOURCES / "node/cache/_logs", ignore_errors=True)
    write_json(
        "preparation.json",
        {
            "platform": "linux/amd64",
            "cuda": "13.0",
            "prepared_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def build():
    for name in COMPONENTS:
        command = [ENGINE, "build", "--network=none", "--no-cache"]
        command += (
            ["--pull=never"] if "podman" in Path(ENGINE).name else ["--pull=false"]
        )
        run(
            *command,
            "-f",
            SOURCES / "dockerfiles" / f"{name}.Dockerfile",
            "-t",
            app(name),
            SOURCES,
        )
        installed = None
        if name != "web":
            installed = json.loads(
                run(
                    ENGINE,
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--entrypoint",
                    "python3",
                    app(name),
                    "-m",
                    "pip",
                    "list",
                    "--format=json",
                    capture=True,
                )
            )
            write_json(f"python-{name}.json", installed)
        metadata = json.loads(run(ENGINE, "image", "inspect", app(name), capture=True))[
            0
        ]
        write_json(
            f"image-{name}.json",
            {
                "tag": app(name),
                "image_id": metadata["Id"],
                "architecture": metadata["Architecture"],
            },
        )
    write_json(
        "offline-build.json",
        {
            "network": "none",
            "cache": False,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "components": COMPONENTS,
            "gpu_hardware_tested": False,
        },
    )


def export():
    directory = SOURCES / "images" / "arena"
    directory.mkdir(parents=True, exist_ok=True)
    for name in COMPONENTS:
        save_image(app(name), directory / f"{name}.tar")


def checksum():
    lines = []
    for path in sorted(SOURCES.rglob("*")):
        relative = path.relative_to(SOURCES)
        if (
            not path.is_file()
            or path.is_symlink()
            or relative.parts[0] in ("logs", "__pycache__")
        ):
            continue
        if path.name in ("SHA256SUMS",) or path.suffix in (".partial", ".pyc"):
            continue
        digest_state = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
                digest_state.update(chunk)
        digest = digest_state.hexdigest()
        lines.append(f"{digest}  {relative.as_posix()}\n")
    (SOURCES / "manifests").mkdir(exist_ok=True)
    (SOURCES / "manifests/SHA256SUMS").write_text("".join(lines))
    print(
        f"Checksummed {len(lines)} files. Verify from sources/: sha256sum -c manifests/SHA256SUMS"
    )


def load():
    for directory in ("base", "arena"):
        for archive in sorted((SOURCES / "images" / directory).glob("*.tar")):
            run(ENGINE, "load", "-i", archive)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("prepare", "bases", "build", "export", "checksum", "load", "all"),
    )
    args = parser.parse_args()
    actions = (
        (prepare, build, export, checksum)
        if args.action == "all"
        else (globals()[args.action],)
    )
    for action in actions:
        action()


if __name__ == "__main__":
    main()
