import asyncio
import json
from pathlib import Path
import importlib.util

import httpx
import pytest

from app import runtime_jobs


@pytest.fixture
def cluster(monkeypatch, tmp_path):
    (tmp_path / "token").write_text("test-service-account-token")
    monkeypatch.setenv("EVALUATION_IMAGE", "registry.example/arena-runtime:cuda")
    monkeypatch.setenv("EVALUATION_PVC", "arena-platform")
    return tmp_path


def test_job_isolates_work_and_requests_gpu_without_credentials(cluster, monkeypatch):
    monkeypatch.setenv("EVALUATION_GPUS", "1")
    monkeypatch.setenv("EVALUATION_CPUS", "4")
    manifest = runtime_jobs.job_manifest(
        "arena-evaluation-1", "job-1-abcd", {"HOME": "/tmp"}, 7200
    )
    spec = manifest["spec"]
    pod = spec["template"]["spec"]
    container = pod["containers"][0]
    assert pod["automountServiceAccountToken"] is False
    assert "runAsUser" not in pod["securityContext"]
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert container["resources"]["limits"]["nvidia.com/gpu"] == "1"
    assert container["resources"]["requests"] == container["resources"]["limits"]
    assert container["volumeMounts"][0]["subPath"] == "evaluations/job-1-abcd"
    assert [m["mountPath"] for m in container["volumeMounts"]] == [
        "/work",
        "/tmp",
        "/dev/shm",
    ]
    assert all("hostPath" not in v for v in pod["volumes"])
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert spec["activeDeadlineSeconds"] == 7200
    assert spec["backoffLimit"] == 0
    assert "test-service-account-token" not in json.dumps(manifest)
    with pytest.raises(ValueError):
        runtime_jobs.job_manifest("invalid", "../other-user", {}, 30)


@pytest.mark.parametrize(
    "outcome", ["succeeded", "failed", "cancelled", "transport-error"]
)
def test_job_completion_and_failure_always_delete_job(cluster, monkeypatch, outcome):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer test-service-account-token"
        if request.method == "POST":
            return httpx.Response(201, json={})
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        if outcome == "transport-error":
            return httpx.Response(500)
        status = (
            {"succeeded": 1}
            if outcome == "succeeded"
            else {
                "conditions": [
                    {"type": "Failed", "status": "True", "reason": "DeadlineExceeded"}
                ]
            }
        )
        return httpx.Response(200, json={"status": status})

    monkeypatch.setattr(
        runtime_jobs,
        "cluster_client",
        lambda: (
            httpx.AsyncClient(
                transport=httpx.MockTransport(handler), base_url="https://cluster"
            ),
            cluster,
            "/jobs",
        ),
    )
    action = runtime_jobs.run_kubernetes(
        "arena-evaluation-1", Path("job-1-abcd"), {}, 60, lambda: outcome != "cancelled"
    )
    if outcome == "succeeded":
        asyncio.run(action)
    else:
        with pytest.raises((ValueError, httpx.HTTPStatusError)):
            asyncio.run(action)
    assert requests[-1].method == "DELETE"
    assert json.loads(requests[-1].content)["propagationPolicy"] == "Foreground"


def test_openshift_renderer_has_persistent_storage_and_runtime_network_boundaries():
    path = Path(__file__).resolve().parents[3] / "infra/openshift/render.py"
    spec = importlib.util.spec_from_file_location("openshift_render", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = module.parser().parse_args(
        [
            "--namespace",
            "arena",
            "--hostname",
            "arena.example.com",
            "--api-image",
            "registry/api:test",
            "--web-image",
            "registry/web:test",
            "--hub-image",
            "registry/hub:test",
            "--runtime-image",
            "registry/runtime:test",
            "--postgres-host",
            "postgres.example.com",
            "--storage-class",
            "rwo",
            "--shared-storage-class",
            "rwx",
            "--notebook-gpus",
            "1",
            "--evaluation-gpus",
            "1",
        ]
    )
    objects = module.render(args)["items"]
    policy = next(
        row
        for row in objects
        if row["metadata"]["name"] == "arena-evaluations-isolated"
    )
    assert policy["spec"]["ingress"] == policy["spec"]["egress"] == []
    assert set(policy["spec"]["policyTypes"]) == {"Ingress", "Egress"}
    worker = next(
        row
        for row in objects
        if row["kind"] == "Deployment"
        and row["metadata"]["name"] == "evaluation-worker"
    )
    assert worker["spec"]["replicas"] == 1
    assert worker["spec"]["strategy"]["type"] == "Recreate"
    assert "hostPath" not in json.dumps(objects)
    assert not any(row["kind"] == "Secret" for row in objects)
