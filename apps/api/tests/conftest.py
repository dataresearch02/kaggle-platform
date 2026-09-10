import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="arena-tests-")
os.environ["DATABASE_URL"] = "sqlite://"

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

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app, headers={"X-Arena-Client": "web"}) as client:
        yield client
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def member(client):
    response = client.post(
        "/api/auth/register",
        json={"username": "learner", "password": "good-password-123"},
    )
    assert response.status_code == 201
    return client
