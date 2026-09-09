"""Prepare, migrate and back up local persistent storage without deleting sources.

Run plan first. migrate/backup stop only this project's containers for a consistent
filesystem copy. Restart explicitly with python scripts/containers.py up after completion.
"""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = {
    "postgres": (70, 70),
    "platform": (10001, 0),
    "hub": (10001, 0),
    "notebooks": (0, 0),
    "backups": (0, 0),
    "legacy-notebooks": (1000, 100),
    "recovered-notebooks": (0, 0),
}
HELPER_IMAGE = "python:3.12-slim"


def run(runtime, *args, capture=False):
    return subprocess.run(
        [runtime, *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    ).stdout


def volume_targets(names, project, user_ids=()):
    mapping = {
        f"{project}_postgres-data": "postgres",
        f"{project}_app-data": "platform",
        f"{project}_hub-data": "hub",
        f"{project}_notebook-data": "legacy-notebooks",
    }
    for name in names:
        match = re.fullmatch(r"arena-notebook-data-arena-(?:2d)?(\d+)", name)
        if match:
            folder = (
                "notebooks"
                if int(match.group(1)) in user_ids
                else "recovered-notebooks"
            )
            mapping[name] = f"{folder}/arena-{match.group(1)}"
    return {name: dest for name, dest in mapping.items() if name in names}


def project_containers(names, project):
    return [
        n
        for n in names
        if n.startswith((project + "_", project + "-"))
        or re.fullmatch(r"arena-notebook-arena-(?:2d)?\d+", n)
    ]


def helper(runtime, data_root, code, mounts=(), args=()):
    run(
        runtime,
        "run",
        "--rm",
        "--user",
        "0:0",
        "--security-opt",
        "label=disable",
        "-v",
        f"{data_root}:/target",
        *mounts,
        HELPER_IMAGE,
        "python",
        "-c",
        code,
        *args,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "init", "migrate", "backup"])
    parser.add_argument("--runtime", default="docker")
    parser.add_argument("--project", default="arena", choices=["arena"])
    configured_root = os.getenv("DATA_ROOT")
    if not configured_root and (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text().splitlines():
            if line.startswith("DATA_ROOT="):
                configured_root = line.split("=", 1)[1].strip().strip("\"'")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(configured_root) if configured_root else ROOT / "data",
    )
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    runtime = args.runtime
    names = run(
        runtime, "volume", "ls", "--format", "{{.Name}}", capture=True
    ).splitlines()
    user_ids = set()
    if args.action in ("plan", "migrate") and f"{args.project}_postgres-data" in names:
        candidates = run(
            runtime, "ps", "--format", "{{.Names}}", capture=True
        ).splitlines()
        database_container = next(
            (
                name
                for name in candidates
                if name in (f"{args.project}_db_1", f"{args.project}-db-1")
            ),
            f"{args.project}_db_1",
        )
        try:
            mounts = json.loads(
                run(
                    runtime,
                    "inspect",
                    database_container,
                    "--format",
                    "{{json .Mounts}}",
                    capture=True,
                )
            )
            if not any(
                mount.get("Name") == f"{args.project}_postgres-data" for mount in mounts
            ):
                raise ValueError("The running database is not using the legacy volume")
            ids = run(
                runtime,
                "exec",
                database_container,
                "psql",
                "-U",
                "arena",
                "-d",
                "arena",
                "-At",
                "-c",
                "SELECT id FROM users",
                capture=True,
            )
            user_ids = {int(value) for value in ids.splitlines()}
        except (subprocess.CalledProcessError, ValueError):
            print(
                "Account IDs could not be verified; notebook volumes will be preserved as recovered data.",
                file=sys.stderr,
            )
    targets = volume_targets(names, args.project, user_ids)
    if args.action == "plan":
        print(
            json.dumps(
                {"data_root": str(data_root), "legacy_volumes": targets}, indent=2
            )
        )
        return
    if args.action == "init" and targets:
        raise SystemExit(
            "Existing Arena volumes detected. Run storage.py migrate to preserve their data before initialization."
        )
    data_root.mkdir(parents=True, exist_ok=True)
    if args.action == "migrate":
        if not targets:
            raise SystemExit(
                "No legacy Arena volumes found. Use init for a new installation."
            )
        # Inspect via a root helper because PostgreSQL correctly uses mode 0700.
        helper(
            runtime,
            data_root,
            """
import json, pathlib, sys
for dest in json.loads(sys.argv[1]).values():
    path = pathlib.Path('/target') / dest
    if path.exists() and (path.is_symlink() or any(path.iterdir())):
        raise SystemExit(f'Refusing to overwrite nonempty destination: {dest}')
""",
            args=(json.dumps(targets),),
        )
    if args.action in ("migrate", "backup"):
        containers = project_containers(
            run(runtime, "ps", "--format", "{{.Names}}", capture=True).splitlines(),
            args.project,
        )
        if containers:
            print(
                "Stopping Arena services and notebook kernels for a consistent copy.",
                flush=True,
            )
            run(runtime, "stop", "--time", "60", *containers)
    if args.action == "backup":
        name = (
            "arena-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".tar.gz"
        )
        helper(
            runtime,
            data_root,
            """
import os, pathlib, sys, tarfile
root = pathlib.Path('/target')
if not (root / 'postgres' / 'PG_VERSION').exists():
    raise SystemExit('No initialized PostgreSQL data found to back up')
(root / 'backups').mkdir(exist_ok=True)
path = root / 'backups' / sys.argv[1]
with path.open('xb') as out:
    os.chmod(path, 0o600)
    with tarfile.open(fileobj=out, mode='w:gz', dereference=False) as archive:
        for folder in root.iterdir():
            if folder.name != 'backups': archive.add(folder, arcname='data/' + folder.name)
        archive.add('/config/.env', arcname='secrets/.env')
print('Backup created: backups/' + path.name)
""",
            mounts=("-v", f"{ROOT}:/config:ro"),
            args=(name,),
        )
        print("Services remain stopped. Restart with python scripts/containers.py up.")
        return
    if args.action == "migrate":
        for volume, destination in targets.items():
            print(f"Copying {volume} -> data/{destination}", flush=True)
            helper(
                runtime,
                data_root,
                """
import hashlib, pathlib, shutil, sys
path = pathlib.Path('/target') / sys.argv[1]
if path.exists(): path.rmdir()  # preflight proved it empty; never removes data
shutil.copytree('/source', path, symlinks=True)
for source in pathlib.Path('/source').rglob('*'):
    target = path / source.relative_to('/source')
    if source.is_symlink():
        if source.readlink() != target.readlink(): raise SystemExit('Symlink verification failed')
    elif source.is_file():
        with source.open('rb') as left, target.open('rb') as right:
            if hashlib.file_digest(left, 'sha256').digest() != hashlib.file_digest(right, 'sha256').digest():
                raise SystemExit('Copy verification failed')
print('Verified copied file contents.')
""",
                mounts=("-v", f"{volume}:/source:ro"),
                args=(destination,),
            )
    helper(
        runtime,
        data_root,
        """
import json, os, pathlib, sys
root = pathlib.Path('/target')
for name, (uid, gid) in json.loads(sys.argv[1]).items():
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    paths = [path]
    if name != 'notebooks': paths += list(path.rglob('*'))
    for entry in paths:
        os.chown(entry, uid, gid, follow_symlinks=False)
    os.chmod(path, 0o700 if name in ('postgres', 'backups') else 0o770)
for path in (root / 'notebooks').iterdir():
    if not path.is_dir() or path.is_symlink(): continue
    for entry in [path, *path.rglob('*')]: os.chown(entry, 1000, 100, follow_symlinks=False)
    os.chmod(path, 0o700)
""",
        args=(json.dumps(DIRECTORIES),),
    )
    helper(
        runtime,
        data_root,
        """
import json, os, pathlib, sys
path = pathlib.Path('/target/.arena-storage.json')
path.write_text(json.dumps({'schema_version': 1, 'migrated_volumes': json.loads(sys.argv[1])}, indent=2) + '\\n')
os.chmod(path, 0o600)
""",
        args=(json.dumps(targets if args.action == "migrate" else {}),),
    )
    print("Persistent storage prepared. Original named volumes were retained.")
    print("Start the bind-mounted stack with python scripts/containers.py up --build.")


if __name__ == "__main__":
    main()
