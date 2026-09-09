import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


storage = load_module("local_storage", ROOT / "scripts/storage.py")
hub_storage = load_module("hub_storage", ROOT / "infra/jupyterhub/storage.py")


def test_legacy_volume_mapping():
    names = [
        "arena_postgres-data",
        "arena_app-data",
        "arena_hub-data",
        "arena-notebook-data-arena-2d2",
        "arena-notebook-data-arena-2d23",
        "arena-notebook-data-arena-99",
        "other_database",
        "arena-notebook-data-unsafe",
    ]
    assert storage.volume_targets(names, "arena", {2, 23, 99}) == {
        "arena_postgres-data": "postgres",
        "arena_app-data": "platform",
        "arena_hub-data": "hub",
        "arena-notebook-data-arena-2d2": "notebooks/arena-2",
        "arena-notebook-data-arena-2d23": "notebooks/arena-23",
        "arena-notebook-data-arena-99": "notebooks/arena-99",
    }


def test_maintenance_does_not_stop_other_projects():
    assert storage.project_containers(
        [
            "arena_db_1",
            "arena-db-1",
            "arena_jupyterhub_1",
            "arena-notebook-arena-2d2",
            "other_db",
            "my-arena_db_1",
        ],
        "arena",
    ) == ["arena_db_1", "arena-db-1", "arena_jupyterhub_1", "arena-notebook-arena-2d2"]


def test_workspace_rejects_path_traversal(monkeypatch):
    monkeypatch.setenv("NOTEBOOKS_HOST_PATH", "/data/notebooks")
    for name in ["../escape", "arena-1/../../etc", "other", "arena-1/child"]:
        with pytest.raises(ValueError):
            hub_storage.prepare_workspace(
                SimpleNamespace(user=SimpleNamespace(name=name))
            )


def test_workspace_requires_absolute_host_path(monkeypatch):
    monkeypatch.setenv("NOTEBOOKS_HOST_PATH", "relative/notebooks")
    with pytest.raises(ValueError, match="absolute"):
        hub_storage.prepare_workspace(
            SimpleNamespace(user=SimpleNamespace(name="arena-1"))
        )


def test_unmatched_notebooks_are_preserved_without_assigning_them_to_new_users():
    assert storage.volume_targets(["arena-notebook-data-arena-2d2"], "arena", {1}) == {
        "arena-notebook-data-arena-2d2": "recovered-notebooks/arena-2"
    }


storage_check = load_module("storage_check", ROOT / "scripts/check_storage.py")


def test_startup_rejects_missing_storage(tmp_path):
    with pytest.raises(SystemExit, match="not initialized"):
        storage_check.check(tmp_path)


def test_startup_rejects_wrong_postgres_major(tmp_path):
    (tmp_path / ".arena-storage.json").write_text('{"schema_version": 1}')
    for name in ("postgres", "platform", "hub", "notebooks"):
        (tmp_path / name).mkdir()
    (tmp_path / "postgres" / "PG_VERSION").write_text("16")
    with pytest.raises(SystemExit, match="PostgreSQL 17"):
        storage_check.check(tmp_path)
    (tmp_path / "postgres" / "PG_VERSION").write_text("17")
    storage_check.check(tmp_path)


@pytest.mark.parametrize(
    "dependencies,needs_repair", [([], False), (["old-init-id"], True)]
)
def test_podman_repair_only_recreates_stacks_with_native_dependencies(
    monkeypatch, dependencies, needs_repair
):
    import json

    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    containers = load_module("container_startup", ROOT / "scripts/containers.py")
    stopped = []

    def fake_run(*args, capture=False):
        if args[0] == "ps":
            assert "label=com.docker.compose.project=arena" in args
            return "hub-id\n"
        assert args == ("inspect", "hub-id")
        return json.dumps([{"Dependencies": dependencies}])

    monkeypatch.setattr(containers, "run", fake_run)
    monkeypatch.setattr(containers, "stop_stack", lambda: stopped.append(True))
    containers.repair_podman_dependencies()
    assert bool(stopped) is needs_repair
