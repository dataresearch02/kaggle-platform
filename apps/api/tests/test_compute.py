import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import compute_worker, runtime_jobs
from app.compute import week_start
from app.db import get_db
from app.main import app
from app.models import GpuUsage, SiteSetting, User
from app.notebook_runtime import get_hub
from test_notebook_runtime import FakeHub

PASSWORD = "good-password-123"


class UserHub(FakeHub):
    """Hub double with a separate server state per user."""

    def __init__(self):
        super().__init__()
        self.states = {}

    async def status(self, user):
        return {"state": self.states.get(user.id, "stopped")}

    async def request(self, method, path, **kwargs):
        response = await super().request(method, path, **kwargs)
        if path.endswith("/server"):
            user_id = int(path.split("/users/arena-")[1].split("/")[0])
            self.states[user_id] = "starting" if method == "POST" else "stopped"
        return response


@pytest.fixture
def hub():
    hub = UserHub()
    app.dependency_overrides[get_hub] = lambda: hub
    yield hub
    app.dependency_overrides.pop(get_hub, None)


@pytest.fixture
def gpu_site(monkeypatch):
    monkeypatch.setenv("NOTEBOOK_SPAWNER", "kubernetes")
    monkeypatch.setenv("EVALUATION_RUNTIME", "kubernetes")


def database():
    return next(app.dependency_overrides[get_db]())


def become(client, username, role="user"):
    client.post("/api/auth/logout")
    if (
        client.post(
            "/api/auth/login", json={"username": username, "password": PASSWORD}
        ).status_code
        != 200
    ):
        client.post(
            "/api/auth/register", json={"username": username, "password": PASSWORD}
        )
    if role != "user":
        with database() as db:
            db.scalar(select(User).where(User.username == username)).role = role
            db.commit()


def server_options(hub):
    return [call[2]["json"] for call in hub.calls if call[1].endswith("/server")][-1]


def test_gpu_sessions_pass_accelerator_and_track_usage(member, hub, gpu_site):
    usage = member.get("/api/compute/usage").json()
    assert usage["internet"] is False and usage["gpu_available"]["session"] is True
    assert (usage["quota_hours"], usage["remaining_hours"], usage["capacity"]) == (
        30,
        30,
        1,
    )
    assert (
        member.post("/api/notebook-session", json={"accelerator": "tpu"}).status_code
        == 422
    )
    assert member.post("/api/notebook-session", json={"accelerator": "gpu"}).json() == {
        "state": "starting"
    }
    assert server_options(hub) == {"user_options": {"accelerator": "gpu"}}
    usage = member.get("/api/compute/usage").json()
    assert usage["in_use"] == 1 and usage["session_accelerator"] == "gpu"
    hub.states[2] = "ready"
    assert (
        member.post("/api/notebook-session", json={"accelerator": "cpu"}).status_code
        == 409
    )
    assert member.post("/api/notebook-session").json() == {"state": "ready"}

    become(member, "second")
    refused = member.post("/api/notebook-session", json={"accelerator": "gpu"})
    assert (
        refused.status_code == 409 and "All GPUs are in use" in refused.json()["detail"]
    )
    assert (
        member.post("/api/notebook-session", json={"accelerator": "cpu"}).status_code
        == 200
    )
    assert server_options(hub) == {"user_options": {"accelerator": "cpu"}}

    become(member, "learner")
    assert member.delete("/api/notebook-session").json() == {"state": "stopped"}
    assert member.get("/api/compute/usage").json()["in_use"] == 0

    # The Hub stops a GPU server (for example an idle culler): the record closes.
    member.post("/api/notebook-session", json={"accelerator": "gpu"})
    with database() as db:
        row = db.scalar(select(GpuUsage).where(GpuUsage.ended_at.is_(None)))
        row.started_at, row.last_seen_at = time.time() - 7200, time.time() - 3600
        db.commit()
        seen = row.last_seen_at
    hub.states[2] = "stopped"
    assert member.get("/api/notebook-session").json() == {"state": "stopped"}
    with database() as db:
        row = db.scalar(select(GpuUsage).order_by(GpuUsage.id.desc()))
        # Unobserved for an hour: charged until the last time it was seen running.
        assert row.ended_at == pytest.approx(seen)
    assert member.get("/api/compute/usage").json()["used_hours"] >= 0.99


def test_quota_capacity_and_availability_refusals_keep_cpu_available(
    member, hub, gpu_site, monkeypatch
):
    id = member.post(
        "/api/notebooks", json={"title": "GPU", "code": "print(1)"}
    ).json()["id"]
    moment = time.time()
    with database() as db:
        db.merge(SiteSetting(key="gpu_weekly_hours", value="0"))
        db.add(
            GpuUsage(
                user_id=2,
                kind="run",
                gpus=1,
                started_at=max(week_start(moment), moment - 3600),
                ended_at=moment,
            )
        )
        db.commit()
    for path, body in (
        ("/api/notebook-session", {"accelerator": "gpu"}),
        (f"/api/code/{id}/runs", {"accelerator": "gpu"}),
        ("/api/exercises/1/attempts", {"code": "x = 1", "accelerator": "gpu"}),
    ):
        refused = member.post(path, json=body)
        assert (
            refused.status_code == 409
            and "weekly GPU quota" in refused.json()["detail"]
        )
    usage = member.get("/api/compute/usage").json()
    assert usage["remaining_hours"] == 0 and usage["quota_hours"] == 0
    assert (
        member.post(f"/api/code/{id}/runs", json={"accelerator": "cpu"}).status_code
        == 202
    )
    assert member.post("/api/notebook-session").json() == {"state": "starting"}

    assert member.get("/api/admin/compute/usage").status_code == 403
    become(member, "operator", "admin")
    assert (
        member.put("/api/admin/settings", json={"gpu_weekly_hours": 40}).json()[
            "gpu_weekly_hours"
        ]
        == 40
    )
    report = member.get("/api/admin/compute/usage").json()
    assert [row["username"] for row in report["users"]] == ["learner"]
    assert report["users"][0]["remaining_hours"] > 38
    assert (
        member.put("/api/admin/settings", json={"gpu_capacity": 17}).status_code == 422
    )

    become(member, "learner")
    member.post(f"/api/code/{id}/runs/1/cancel")
    queued = member.post(f"/api/code/{id}/runs", json={"accelerator": "gpu"})
    assert queued.status_code == 202, queued.text
    member.post(f"/api/code/{id}/runs/{queued.json()['id']}/cancel")
    monkeypatch.setenv("EVALUATION_RUNTIME", "docker")
    refused = member.post(f"/api/code/{id}/runs", json={"accelerator": "gpu"})
    assert refused.status_code == 409 and "not available" in refused.json()["detail"]
    with database() as db:
        db.merge(SiteSetting(key="gpu_capacity", value="0"))
        db.commit()
    assert (
        member.post(
            f"/api/code/{id}/schedules",
            json={"frequency": "daily", "accelerator": "gpu"},
        ).status_code
        == 409
    )


def test_worker_waits_for_a_free_gpu_and_charges_actual_duration(
    member, gpu_site, monkeypatch
):
    with database() as db:
        factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(compute_worker, "SessionLocal", factory)
    first = member.post(
        "/api/notebooks", json={"title": "GPU run", "code": "1"}
    ).json()["id"]
    second = member.post(
        "/api/notebooks", json={"title": "CPU run", "code": "2"}
    ).json()["id"]
    gpu = member.post(f"/api/code/{first}/runs", json={"accelerator": "gpu"}).json()[
        "id"
    ]
    cpu = member.post(f"/api/code/{second}/runs").json()["id"]
    with factory() as db:
        session = GpuUsage(user_id=1, kind="session", gpus=1, started_at=time.time())
        db.add(session)
        db.commit()
        assert compute_worker.claim(db) == ("run", cpu)
        db.get(GpuUsage, session.id).ended_at = time.time()
        db.commit()
        assert compute_worker.claim(db) == ("run", gpu)
        assert (
            db.scalar(select(GpuUsage).where(GpuUsage.kind == "run")).ended_at is None
        )

    async def fake_run(name, work, env, timeout, active, gpus=None):
        assert gpus == 1
        (work / "executed.ipynb").write_text((work / "source.ipynb").read_text())
        (work / "result.json").write_text('{"status": "succeeded"}')

    monkeypatch.setattr(runtime_jobs, "run", fake_run)
    asyncio.run(compute_worker.execute_run(gpu))
    with factory() as db:
        row = db.scalar(select(GpuUsage).where(GpuUsage.kind == "run"))
        assert row.ended_at is not None and row.ref_id == gpu


def test_jobs_request_gpus_and_gpu_tolerations_only_when_selected(monkeypatch):
    monkeypatch.setenv("EVALUATION_IMAGE", "registry/runtime:test")
    monkeypatch.setenv("EVALUATION_PVC", "arena-platform")
    monkeypatch.setenv("EVALUATION_GPUS", "1")
    gpu_toleration = {
        "key": "nvidia.com/gpu",
        "operator": "Exists",
        "effect": "NoSchedule",
    }
    other = {"key": "dedicated", "operator": "Exists"}
    monkeypatch.setenv("EVALUATION_TOLERATIONS", json.dumps([gpu_toleration, other]))

    def pod(manifest):
        return manifest["spec"]["template"]["spec"]

    cpu = pod(runtime_jobs.job_manifest("arena-run-1-ab", "run-1-abcd", {}, 60, gpus=0))
    assert "nvidia.com/gpu" not in cpu["containers"][0]["resources"]["limits"]
    assert cpu["tolerations"] == [other]
    gpu = pod(
        runtime_jobs.job_manifest("arena-attempt-2-ab", "attempt-2-abcd", {}, 60, 1)
    )
    assert gpu["containers"][0]["resources"]["limits"]["nvidia.com/gpu"] == "1"
    assert gpu_toleration in gpu["tolerations"]
    # Competition commits keep EVALUATION_GPUS.
    commit = pod(runtime_jobs.job_manifest("arena-evaluation-3", "job-3-abcd", {}, 60))
    assert commit["containers"][0]["resources"]["limits"]["nvidia.com/gpu"] == "1"
    for directory in ("run-x-abcd", "../attempt-1-abcd", "attempt-1-ABCD"):
        with pytest.raises(ValueError):
            runtime_jobs.job_manifest("arena-run-1", directory, {}, 60, 0)


class Config:
    """Stand-in for the traitlets config object used by jupyterhub_config.py."""

    def __getattr__(self, name):
        section = SimpleNamespace()
        setattr(self, name, section)
        return section


def hub_config(monkeypatch, **env):
    path = Path(__file__).resolve().parents[3] / "infra/jupyterhub/jupyterhub_config.py"
    values = {
        "JUPYTERHUB_API_TOKEN": "t" * 40,
        "NOTEBOOK_SPAWNER": "kubernetes",
        "POD_NAMESPACE": "arena",
        "NOTEBOOK_IMAGE": "registry/runtime:test",
        "NOTEBOOK_STORAGE_CLASS": "rwo",
        **env,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setitem(
        sys.modules, "arena_auth", SimpleNamespace(ArenaAuthenticator=object)
    )
    monkeypatch.setitem(sys.modules, "storage", SimpleNamespace(prepare_workspace=None))
    config = Config()
    exec(compile(path.read_text(), str(path), "exec"), {"get_config": lambda: config})
    return config


def test_hub_applies_gpu_settings_only_to_validated_gpu_sessions(monkeypatch):
    gpu_toleration = {
        "key": "nvidia.com/gpu",
        "operator": "Exists",
        "effect": "NoSchedule",
    }
    other = {"key": "dedicated", "operator": "Exists"}
    config = hub_config(
        monkeypatch,
        NOTEBOOK_TOLERATIONS=json.dumps([gpu_toleration, other]),
        NOTEBOOK_GPU_NODE_SELECTOR='{"nvidia.com/gpu.present": "true"}',
    )
    assert config.KubeSpawner.tolerations == [other]
    assert "extra_resource_limits" not in vars(config.KubeSpawner)
    apply = config.KubeSpawner.apply_user_options
    spawner = SimpleNamespace()
    apply(spawner, {"accelerator": "gpu"})
    assert spawner.extra_resource_limits == {"nvidia.com/gpu": "1"}
    assert spawner.extra_resource_guarantees == {"nvidia.com/gpu": "1"}
    assert gpu_toleration in spawner.tolerations
    assert spawner.node_selector == {"nvidia.com/gpu.present": "true"}
    assert spawner.extra_labels["arena.accelerator"] == "gpu"
    for options in ({"accelerator": "cpu"}, {}, None):
        apply(spawner, options)  # The same spawner is reused for the next session.
        assert (
            spawner.extra_resource_limits == {}
            and spawner.extra_resource_guarantees == {}
        )
        assert spawner.tolerations == [other] and spawner.node_selector == {}
    for options in (
        {"accelerator": "tpu"},
        {"accelerator": "gpu", "image": "x"},
        ["gpu"],
    ):
        with pytest.raises(ValueError):
            apply(spawner, options)
    with pytest.raises(ValueError):
        hub_config(monkeypatch, NOTEBOOK_GPU_COUNT="9")
    docker = hub_config(monkeypatch, NOTEBOOK_SPAWNER="docker")
    docker.DockerSpawner.apply_user_options(spawner, {"accelerator": "cpu"})
    with pytest.raises(ValueError):
        docker.DockerSpawner.apply_user_options(spawner, {"accelerator": "gpu"})
