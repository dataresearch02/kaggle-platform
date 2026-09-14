import hashlib
import json
import time

from sqlalchemy import func, select

from app import uploads
from app.db import get_db
from app.main import app
from app.models import AuditLog, SiteSetting, StoredFile, UploadSession, User
from conftest import upload_file

PASSWORD = "good-password-123"


def database():
    return next(app.dependency_overrides[get_db]())


def new_draft(client, title="Chunked data"):
    response = client.post(
        "/api/datasets/drafts", json={"title": title, "description": "Large files"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def start(client, version_id, content, path="big.bin", sha256=None):
    response = client.post(
        "/api/uploads",
        json={
            "version_id": version_id,
            "path": path,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest() if sha256 is None else sha256,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_chunked_upload_resume_verification_and_abort(member, monkeypatch):
    monkeypatch.setenv("UPLOAD_CHUNK_BYTES", "1024")
    dataset = new_draft(member)
    version_id = dataset["draft_version"]["id"]
    content = bytes(index % 251 for index in range(2500))
    session = start(member, version_id, content)
    assert (session["chunk_size"], session["chunk_count"]) == (1024, 3)
    chunk = f"/api/uploads/{session['id']}/chunks"
    assert member.put(f"{chunk}/2", content=content[2048:]).status_code == 200
    assert member.put(f"{chunk}/0", content=content[:1024]).status_code == 200
    # A reloaded browser learns which chunks to send.
    status = member.get(f"/api/uploads/{session['id']}").json()
    assert (status["received"], status["received_bytes"]) == ([0, 2], 1476)
    missing = member.post(f"/api/uploads/{session['id']}/complete")
    assert missing.status_code == 409 and "chunk 1" in missing.json()["detail"]
    assert member.put(f"{chunk}/1", content=content[1024:2000]).status_code == 422
    assert member.put(f"{chunk}/1", content=content[1024:2049]).status_code == 413
    assert member.put(f"{chunk}/3", content=b"x").status_code == 422
    corrupted = member.put(
        f"{chunk}/1", content=content[1024:2048], headers={"X-Chunk-Sha256": "0" * 64}
    )
    assert corrupted.status_code == 422
    assert (
        member.post(
            f"/api/datasets/{dataset['id']}/versions/draft/publish", json={"note": "x"}
        ).status_code
        == 409
    )
    digest = hashlib.sha256(content[1024:2048]).hexdigest()
    assert (
        member.put(
            f"{chunk}/1", content=content[1024:2048], headers={"X-Chunk-Sha256": digest}
        ).status_code
        == 200
    )
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/register", json={"username": "stranger", "password": PASSWORD}
    )
    assert member.get(f"/api/uploads/{session['id']}").status_code == 404
    assert member.put(f"{chunk}/1", content=content[1024:2048]).status_code == 404
    member.post("/api/auth/logout")
    member.post("/api/auth/login", json={"username": "learner", "password": PASSWORD})
    assert member.post(f"/api/uploads/{session['id']}/complete").status_code == 202
    status = member.get(f"/api/uploads/{session['id']}").json()
    assert status["status"] == "completed" and status["file"]["path"] == "big.bin"
    assert status["file"]["sha256"] == hashlib.sha256(content).hexdigest()
    assert not uploads.session_dir(session["id"]).exists()
    base = f"/api/datasets/{dataset['id']}"
    assert (
        member.get(f"{base}/files/{status['file']['id']}/download").content == content
    )
    assert member.put(f"{chunk}/0", content=content[:1024]).status_code == 409

    # The declared digest is verified against the assembled bytes.
    with database() as db:
        stored = db.scalar(select(func.count()).select_from(StoredFile))
    wrong = start(member, version_id, content, "wrong.bin", sha256="a" * 64)
    for index in range(3):
        member.put(
            f"/api/uploads/{wrong['id']}/chunks/{index}",
            content=content[index * 1024 : (index + 1) * 1024],
        )
    assert member.post(f"/api/uploads/{wrong['id']}/complete").status_code == 202
    failed = member.get(f"/api/uploads/{wrong['id']}").json()
    assert failed["status"] == "failed" and "SHA-256 mismatch" in failed["error"]
    assert not uploads.session_dir(wrong["id"]).exists()
    with database() as db:
        assert db.scalar(select(func.count()).select_from(StoredFile)) == stored

    cancelled = start(member, version_id, content, "cancel.bin")
    member.put(f"/api/uploads/{cancelled['id']}/chunks/0", content=content[:1024])
    assert uploads.session_dir(cancelled["id"]).is_dir()
    assert member.delete(f"/api/uploads/{cancelled['id']}").status_code == 204
    assert member.get(f"/api/uploads/{cancelled['id']}").status_code == 404
    assert not uploads.session_dir(cancelled["id"]).exists()

    # Replacing a path in a draft keeps one file; the draft publishes both paths.
    upload_file(member, version_id, "big.bin", b"replacement")
    published = member.post(f"{base}/versions/draft/publish", json={"note": "Chunked"})
    assert published.status_code == 200, published.text
    assert published.json()["file_count"] == 1
    # Uploads into a published version are refused.
    late = member.post(
        "/api/uploads", json={"version_id": version_id, "path": "late.bin", "size": 3}
    )
    assert late.status_code == 404


def test_upload_limits_expiry_and_interrupted_assembly(member, monkeypatch):
    monkeypatch.setenv("UPLOAD_CHUNK_BYTES", "1024")
    monkeypatch.setenv("UPLOAD_MAX_ACTIVE_SESSIONS", "2")
    version_id = new_draft(member)["draft_version"]["id"]
    first = start(member, version_id, b"a" * 2000, "a.bin")
    start(member, version_id, b"b" * 10, "b.bin")
    limited = member.post(
        "/api/uploads", json={"version_id": version_id, "path": "c.bin", "size": 10}
    )
    assert limited.status_code == 429
    monkeypatch.setenv("UPLOAD_MAX_FILE_BYTES", "100")
    too_big = member.post(
        "/api/uploads", json={"version_id": version_id, "path": "c.bin", "size": 101}
    )
    assert too_big.status_code in (413, 429)
    member.put(f"/api/uploads/{first['id']}/chunks/0", content=b"a" * 1024)
    assert uploads.session_dir(first["id"]).is_dir()
    with database() as db:
        stale = db.get(UploadSession, first["id"])
        stale.status, stale.updated_at = "assembling", time.time() - 3600
        db.commit()
        assert uploads.expire_uploads(db) == []
        assert db.get(UploadSession, first["id"]).status == "uploading"
        removed = uploads.expire_uploads(db, at=time.time() + 25 * 3600)
        assert first["id"] in removed and len(removed) == 2
    assert not uploads.session_dir(first["id"]).exists()
    assert member.get(f"/api/uploads/{first['id']}").status_code == 404


def test_storage_quota_enforced_counted_once_and_freed(member):
    me = member.get("/api/auth/me").json()
    with database() as db:
        db.merge(SiteSetting(key="storage_quota_gib", value=json.dumps(3000 / 1024**3)))
        db.commit()
    dataset = new_draft(member, "Quota data")
    base = f"/api/datasets/{dataset['id']}"
    version_id = dataset["draft_version"]["id"]
    held = start(member, version_id, b"q" * 2000, "held.bin")
    # Unfinished uploads hold their declared size.
    refused = member.post(
        "/api/uploads",
        json={"version_id": version_id, "path": "more.bin", "size": 2000},
    )
    assert refused.status_code == 413 and "quota" in refused.json()["detail"]
    assert member.delete(f"/api/uploads/{held['id']}").status_code == 204
    upload_file(member, version_id, "one.bin", b"1" * 1000)
    assert (
        member.post(f"{base}/versions/draft/publish", json={"note": "v1"}).status_code
        == 200
    )
    version = member.post(f"{base}/versions", json={"carry_over": True}).json()
    upload_file(member, version["id"], "two.bin", b"2" * 500)
    assert (
        member.post(f"{base}/versions/draft/publish", json={"note": "v2"}).status_code
        == 200
    )
    usage = member.get("/api/storage/usage").json()
    # one.bin is shared by both versions and counted once.
    assert (usage["stored_bytes"], usage["upload_bytes"]) == (1500, 0)
    assert usage["quota_bytes"] in (2999, 3000) and not usage["custom_quota"]
    legacy = member.post(
        "/api/datasets",
        data={"title": "Too large", "description": "Over quota"},
        files={"file": ("big.csv", b"x\n" + b"1\n" * 1000)},
    )
    assert legacy.status_code == 413
    assert (
        member.put(
            f"/api/admin/users/{me['id']}/storage-quota", json={"quota_gib": 1}
        ).status_code
        == 403
    )

    member.post("/api/auth/logout")
    member.post("/api/auth/register", json={"username": "boss", "password": PASSWORD})
    with database() as db:
        db.scalar(select(User).where(User.username == "boss")).role = "admin"
        db.commit()
    changed = member.put(
        f"/api/admin/users/{me['id']}/storage-quota", json={"quota_gib": 1}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["quota_bytes"] == 1024**3 and changed.json()["custom_quota"]
    report = member.get("/api/admin/storage?q=learner")
    assert report.status_code == 200 and report.headers["x-total-count"] == "1"
    assert report.json()[0]["used_bytes"] == 1500
    with database() as db:
        entry = db.scalar(
            select(AuditLog).where(AuditLog.action == "user.storage_quota")
        )
        assert json.loads(entry.detail)["to_bytes"] == 1024**3
    assert member.delete(f"{base}/versions/1").status_code == 204
    assert member.get("/api/admin/storage?q=learner").json()[0]["used_bytes"] == 1500
    restored = member.put(
        f"/api/admin/users/{me['id']}/storage-quota", json={"quota_gib": None}
    )
    assert not restored.json()["custom_quota"]

    member.post("/api/auth/logout")
    member.post("/api/auth/login", json={"username": "learner", "password": PASSWORD})
    assert member.delete(f"/api/work/datasets/{dataset['id']}").status_code == 204
    assert member.get("/api/storage/usage").json()["stored_bytes"] == 0
