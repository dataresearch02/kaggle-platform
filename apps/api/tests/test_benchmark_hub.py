import json
import pytest
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db import get_db
from app.models import BenchmarkRun
from app import benchmark_worker
from app.benchmark_runner import evaluate

BASE = "/api/benchmark-hub"
TASK = 'def evaluate(model, case):\n    return model.prompt(case["prompt"]) == case["expected"]\n'
MODEL = "def predict(prompt):\n    return prompt\n"


def asset(
    client, kind, title="Test asset", visibility="private", source=None, cases=None
):
    response = client.post(
        f"{BASE}/assets/{kind}",
        json={
            "title": title,
            "visibility": visibility,
            "source": source or (TASK if kind == "task" else MODEL),
            "cases": (
                cases
                if cases is not None
                else (
                    [
                        {"prompt": "yes", "expected": "yes"},
                        {"prompt": "no", "expected": "yes"},
                    ]
                    if kind == "task"
                    else []
                )
            ),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def collection(client, tasks, models, visibility="private"):
    response = client.post(
        f"{BASE}/collections",
        json={
            "title": "Evaluation collection",
            "visibility": visibility,
            "tasks": [r["version_id"] for r in tasks],
            "models": [r["version_id"] for r in models],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def worker_db(monkeypatch):
    with next(app.dependency_overrides[get_db]()) as db:
        factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(benchmark_worker, "SessionLocal", factory)
    return factory


def complete(client, db_factory, bid):
    response = client.post(f"{BASE}/collections/{bid}/runs")
    assert response.status_code == 202, response.text
    rid = response.json()["id"]
    with db_factory() as db:
        row = db.get(BenchmarkRun, rid)
        row.status = "running"
        snapshot = json.loads(row.snapshot)
        db.commit()
    benchmark_worker.finish(rid, evaluate(snapshot))
    return rid


def test_versioned_matrix_scores_outputs_exports_and_history(member, worker_db):
    task = asset(member, "task")
    model = asset(member, "model")
    b = collection(member, [task], [model])
    rid = complete(member, worker_db, b["id"])
    result = member.get(f"{BASE}/runs/{rid}").json()
    assert result["status"] == "succeeded"
    assert result["results"][0]["score"] == 0.5
    assert result["results"][0]["cases"][0]["outputs"][0]["output"] == "yes"
    board = member.get(f'{BASE}/collections/{b["id"]}/leaderboard').json()["items"]
    assert board[0]["score"] == 0.5 and board[0]["rank"] == 1
    catalog = member.get(BASE + "/collections?visibility=private").json()["items"]
    assert catalog[0]["top_models"][0]["score"] == 0.5
    assert catalog[0]["owner"] == "learner"
    assert member.get(BASE + "/collections?visibility=public").json()["items"] == []

    assert (
        "0.5" in member.get(f'{BASE}/collections/{b["id"]}/leaderboard?format=csv').text
    )
    updated = member.put(
        f'{BASE}/assets/{task["id"]}',
        json={
            "title": "Updated task",
            "source": TASK,
            "cases": [{"prompt": "yes", "expected": "yes"}],
        },
    ).json()
    assert updated["version_id"] != task["version_id"]
    assert member.get(f'{BASE}/collections/{b["id"]}').json()["tasks"] == [
        task["version_id"]
    ]
    assert len(member.get(f'{BASE}/assets/{task["id"]}').json()["versions"]) == 2
    member.put(
        f'{BASE}/collections/{b["id"]}',
        json={
            "title": b["title"],
            "tasks": [updated["version_id"]],
            "models": [model["version_id"]],
        },
    )
    assert member.get(f'{BASE}/collections/{b["id"]}/leaderboard').json()["items"] == []
    assert member.get(f"{BASE}/runs/{rid}").json()["results"][0]["score"] == 0.5


def test_permissions_public_reuse_and_private_history(member, worker_db):
    private = asset(member, "task")
    public = asset(member, "model", visibility="public")
    b = collection(member, [private], [public])
    rid = complete(member, worker_db, b["id"])
    assert (
        member.post(
            f"{BASE}/collections",
            json={
                "title": "Invalid public",
                "visibility": "public",
                "tasks": [private["version_id"]],
                "models": [public["version_id"]],
            },
        ).status_code
        == 422
    )
    shared = asset(member, "task", visibility="public")
    member.put(
        f'{BASE}/collections/{b["id"]}',
        json={
            "title": b["title"],
            "visibility": "public",
            "tasks": [shared["version_id"]],
            "models": [public["version_id"]],
        },
    )
    assert (
        member.put(
            f'{BASE}/assets/{public["id"]}',
            json={"title": "Hide model", "source": MODEL, "visibility": "private"},
        ).status_code
        == 409
    )
    member.post("/api/auth/logout")
    assert member.get(f'{BASE}/assets/{private["id"]}').status_code == 404
    assert member.get(f"{BASE}/runs/{rid}").status_code == 404
    assert member.get(f'{BASE}/collections/{b["id"]}').status_code == 200
    assert member.post(f'{BASE}/collections/{b["id"]}/runs').status_code == 401
    member.post(
        "/api/auth/register",
        json={"username": "benchmark_other", "password": "other-password-123"},
    )
    assert member.post(f'{BASE}/collections/{b["id"]}/runs').status_code == 403
    assert (
        member.put(
            f'{BASE}/assets/{shared["id"]}',
            json={"title": "Steal task", "source": TASK, "cases": [{}]},
        ).status_code
        == 403
    )
    assert collection(member, [shared], [public])["id"] != b["id"]


def test_queue_cancellation_failure_and_recovery(member, worker_db):
    task = asset(member, "task")
    bad = asset(
        member,
        "model",
        source='def predict(prompt):\n    raise RuntimeError("broken model")\n',
    )
    b = collection(member, [task], [bad])
    first = member.post(f'{BASE}/collections/{b["id"]}/runs').json()
    assert member.post(f'{BASE}/collections/{b["id"]}/runs').status_code == 409
    assert (
        member.post(f'{BASE}/runs/{first["id"]}/cancel').json()["status"] == "cancelled"
    )
    rid = complete(member, worker_db, b["id"])
    board = member.get(f'{BASE}/collections/{b["id"]}/leaderboard').json()["items"][0]
    assert board["rank"] is None and board["score"] is None
    assert "broken model" in member.get(f"{BASE}/runs/{rid}").text
    row = member.post(f'{BASE}/collections/{b["id"]}/runs').json()
    with worker_db() as db:
        db.get(BenchmarkRun, row["id"]).status = "running"
        db.commit()
        benchmark_worker.recover(db)
    assert member.get(f'{BASE}/runs/{row["id"]}').json()["status"] == "failed"


def test_validation_limits_and_task_errors(member):
    assert (
        member.post(
            f"{BASE}/assets/task", json={"title": "Bad syntax", "source": "def nope("}
        ).status_code
        == 422
    )
    assert (
        member.post(
            f"{BASE}/assets/task",
            json={"title": "No entrypoint", "source": "x=1", "cases": [{}]},
        ).status_code
        == 422
    )
    assert (
        member.post(
            f"{BASE}/assets/task",
            json={"title": "Empty cases", "source": TASK, "cases": []},
        ).status_code
        == 422
    )
    t = asset(member, "task")
    m = asset(member, "model")
    assert (
        member.post(
            f"{BASE}/collections",
            json={
                "title": "Duplicate task",
                "tasks": [t["version_id"], t["version_id"]],
            },
        ).status_code
        == 422
    )
    assert (
        member.post(
            f"{BASE}/collections",
            json={"title": "Wrong kind", "tasks": [m["version_id"]]},
        ).status_code
        == 422
    )
    b = collection(member, [], [])
    assert member.post(f'{BASE}/collections/{b["id"]}/runs').status_code == 422
    base = {
        "models": [{"title": "model", "version_id": 1, "source": MODEL}],
        "tasks": [
            {
                "title": "task",
                "version_id": 2,
                "source": 'def evaluate(model, case):\n    return float("nan")',
                "cases": [{}],
            }
        ],
    }
    assert evaluate(base)["results"][0]["status"] == "failed"
    base["tasks"][0][
        "source"
    ] = 'def evaluate(model, case):\n    assert False, "wrong answer"'
    assert evaluate(base)["results"][0]["score"] == 0


def test_provider_registration_pins_configuration_without_exposing_keys(
    member, monkeypatch
):
    config = [
        {
            "id": "test-provider",
            "label": "Test provider",
            "model": "small-model",
            "url": "http://model.invalid/v1/chat/completions",
            "key_env": "TEST_BENCHMARK_KEY",
        }
    ]
    monkeypatch.setenv("BENCHMARK_PROVIDERS_JSON", json.dumps(config))
    monkeypatch.setenv("TEST_BENCHMARK_KEY", "not-a-real-key")
    response = member.get(BASE + "/providers")
    assert response.json()[0]["available"] is True
    assert (
        "not-a-real-key" not in response.text and "model.invalid" not in response.text
    )
    model = member.post(
        BASE + "/assets/model",
        json={"title": "Remote model", "provider_id": "test-provider"},
    ).json()
    task = asset(member, "task")
    b = collection(member, [task], [model])
    first = member.post(f'{BASE}/collections/{b["id"]}/runs')
    assert first.status_code == 202
    assert "not-a-real-key" not in member.get(f'{BASE}/runs/{first.json()["id"]}').text
    member.post(f'{BASE}/runs/{first.json()["id"]}/cancel')
    config[0]["model"] = "changed-model"
    monkeypatch.setenv("BENCHMARK_PROVIDERS_JSON", json.dumps(config))
    assert member.post(f'{BASE}/collections/{b["id"]}/runs').status_code == 409


def test_inference_adapter_and_limits(monkeypatch):
    import asyncio
    import httpx
    from app import benchmark_providers

    monkeypatch.setenv(
        "BENCHMARK_PROVIDERS_JSON",
        json.dumps(
            [
                {
                    "id": "local",
                    "url": "http://model.invalid/v1/chat/completions",
                    "model": "test",
                }
            ]
        ),
    )
    original = httpx.AsyncClient
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "42"}}]})

    monkeypatch.setattr(
        benchmark_providers.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    assert asyncio.run(benchmark_providers.infer("local", "Answer?")) == "42"
    assert requests[0]["messages"] == [{"role": "user", "content": "Answer?"}]
    with pytest.raises(ValueError):
        asyncio.run(benchmark_providers.infer("unknown", "hello"))
    with pytest.raises(ValueError):
        asyncio.run(benchmark_providers.infer("local", "x" * 20001))


def test_inference_broker_serves_only_selected_models(tmp_path, monkeypatch):
    import asyncio
    import os
    from app import benchmark_providers

    monkeypatch.setenv(
        "BENCHMARK_PROVIDERS_JSON",
        json.dumps(
            [
                {
                    "id": "local",
                    "url": "http://model.invalid/v1/chat/completions",
                    "model": "test",
                }
            ]
        ),
    )
    called = []

    async def infer(provider, prompt):
        called.append((provider, prompt))
        return "answer"

    monkeypatch.setattr(benchmark_providers, "infer", infer)

    async def check():
        fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
        task = asyncio.create_task(
            benchmark_providers.broker(
                fd,
                [
                    {
                        "version_id": 7,
                        "provider_id": "local",
                        "provider_revision": benchmark_providers.signature("local"),
                    }
                ],
            )
        )
        try:
            for token, version in [("a" * 32, 7), ("b" * 32, 999)]:
                (tmp_path / f"{token}.request.json").write_text(
                    json.dumps({"model_version_id": version, "prompt": "question"})
                )
            for _ in range(30):
                if (tmp_path / f'{"b"*32}.response.json').exists():
                    break
                await asyncio.sleep(0.05)
            assert json.loads((tmp_path / f'{"a"*32}.response.json').read_text()) == {
                "output": "answer"
            }
            assert (
                "not included"
                in json.loads((tmp_path / f'{"b"*32}.response.json').read_text())[
                    "error"
                ]
            )
            assert called == [("local", "question")]
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            os.close(fd)

    asyncio.run(check())


def test_collections_appear_in_your_work_without_legacy_id_collision(member):
    b = collection(member, [], [])
    work = member.get("/api/work").json()
    matches = [r for r in work if r.get("work_resource") == "benchmark-collections"]
    assert matches[0]["id"] == b["id"] and matches[0]["work_kind"] == "benchmarks"
    assert member.get("/api/work/status").json()["has_work"] is True
    assert (
        member.patch(
            f'/api/work/benchmark-collections/{b["id"]}',
            json={"title": "Renamed benchmark", "description": "Updated description"},
        ).status_code
        == 200
    )
    assert (
        member.get(f'{BASE}/collections/{b["id"]}').json()["title"]
        == "Renamed benchmark"
    )
    assert (
        member.delete(f'/api/work/benchmark-collections/{b["id"]}').status_code == 204
    )
    assert member.get(f'{BASE}/collections/{b["id"]}').status_code == 404
