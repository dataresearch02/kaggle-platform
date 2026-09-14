import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="arena-tests-")
os.environ["DATABASE_URL"] = "sqlite://"
# Practice packs are imported explicitly by test_practice_competitions.py.
os.environ["ARENA_IMPORT_PRACTICE"] = "false"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from app.db import Base, get_db, SessionLocal
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.seed import seed


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        seed(db)
        from app.competition_metadata import backfill_metadata

        backfill_metadata(db)
        from app.models import SiteSetting

        # Workflow tests predate the creation policy; policy tests set "hosts".
        db.add(SiteSetting(key="competition_creation", value='"everyone"'))
        db.commit()

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app, headers={"X-Arena-Client": "web"}) as client:
        yield client
    app.dependency_overrides.clear()
    engine.dispose()


def upload_file(client, version_id, path, content):
    """Send a file through the chunked upload API into a draft; return its file JSON."""
    import hashlib

    created = client.post(
        "/api/uploads",
        json={
            "version_id": version_id,
            "path": path,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        },
    )
    assert created.status_code == 201, created.text
    session = created.json()
    size = session["chunk_size"]
    for index in range(session["chunk_count"]):
        sent = client.put(
            f"/api/uploads/{session['id']}/chunks/{index}",
            content=content[index * size : (index + 1) * size],
        )
        assert sent.status_code == 200, sent.text
    assert client.post(f"/api/uploads/{session['id']}/complete").status_code == 202
    status = client.get(f"/api/uploads/{session['id']}").json()
    assert status["status"] == "completed", status
    return status["file"]


@pytest.fixture
def member(client):
    response = client.post(
        "/api/auth/register",
        json={"username": "learner", "password": "good-password-123"},
    )
    assert response.status_code == 201
    return client
