"""Fail startup if DATA_ROOT points at unprepared or accidentally empty storage."""

import json
from pathlib import Path


def check(root):
    marker = root / ".arena-storage.json"
    if (
        not marker.is_file()
        or json.loads(marker.read_text()).get("schema_version") != 1
    ):
        raise SystemExit(
            "Storage is not initialized. Run scripts/storage.py init (new install) or migrate (existing volumes)."
        )
    for name in ("postgres", "platform", "hub", "notebooks"):
        path = root / name
        if not path.is_dir() or path.is_symlink():
            raise SystemExit(f"Missing or invalid persistent data directory: {name}")
    version_file = root / "postgres" / "PG_VERSION"
    if version_file.exists() and version_file.read_text().strip() != "17":
        raise SystemExit(
            "This Compose configuration requires PostgreSQL 17 data. Use a logical dump/restore for major-version upgrades."
        )
    print("Persistent storage layout verified.")


if __name__ == "__main__":
    check(Path("/storage"))
