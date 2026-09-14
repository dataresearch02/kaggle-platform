import io
import stat
import struct
import zipfile

import pytest
from sqlalchemy import func, select

from app.db import get_db
from app.file_previews import preview
from app.input_sources import resolve_attachment, source_files
from app.isolated_runner import stage_inputs
from app.main import app
from app.models import (
    Dataset,
    ModelCard,
    ResourceVersion,
    StoredFile,
    User,
    WorkFileDeletion,
)
from app.runtime_jobs import prepare_permissions
from conftest import upload_file

PASSWORD = "good-password-123"


def database():
    return next(app.dependency_overrides[get_db]())


def switch(client, username, register=False):
    client.post("/api/auth/logout")
    path = "/api/auth/register" if register else "/api/auth/login"
    response = client.post(path, json={"username": username, "password": PASSWORD})
    assert response.status_code in (200, 201), response.text


def new_dataset(client, title="Weather records"):
    response = client.post(
        "/api/datasets/drafts",
        json={"title": title, "description": "Daily weather observations"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def publish(client, base, note):
    response = client.post(f"{base}/versions/draft/publish", json={"note": note})
    assert response.status_code == 200, response.text
    return response.json()


def draft(client, base, carry_over=True):
    response = client.post(f"{base}/versions", json={"carry_over": carry_over})
    assert response.status_code == 201, response.text
    return response.json()


def learner(db):
    return db.scalar(select(User).where(User.username == "learner"))


def test_dataset_versions_carry_over_pinning_and_legacy_links(member, tmp_path):
    dataset = new_dataset(member)
    id, base = dataset["id"], f"/api/datasets/{dataset['id']}"
    assert dataset["draft_version"]["status"] == "draft"
    # A dataset without a published version cannot be attached yet.
    assert all(
        item["id"] != id
        for item in member.get("/api/input-sources?kind=dataset").json()["items"]
    )
    version_id = dataset["draft_version"]["id"]
    upload_file(member, version_id, "train.csv", b"day,temp\n1,20\n")
    upload_file(member, version_id, "docs/notes.md", b"# Notes\n")
    first = publish(member, base, "Initial observations")
    assert (first["number"], first["file_count"]) == (1, 2)
    detail = member.get(base).json()
    assert detail["filename"] == "train.csv" and detail["preview"] == [
        {"day": "1", "temp": "20"}
    ]
    assert detail["latest_version"]["number"] == 1 and detail["input_available"]
    assert member.get(f"{base}/download").content == b"day,temp\n1,20\n"

    second = draft(member, base)
    assert second["file_count"] == 2
    files = member.get(f"{base}/versions/draft/files").json()
    notes = next(file for file in files if file["path"] == "docs/notes.md")
    assert (
        member.delete(f"{base}/versions/draft/files/{notes['id']}").status_code == 204
    )
    upload_file(member, second["id"], "train.csv", b"day,temp\n1,20\n2,25\n")
    assert publish(member, base, "Add day two")["number"] == 2
    assert [row["number"] for row in member.get(f"{base}/versions").json()] == [2, 1]
    old = member.get(f"{base}/versions/1/files").json()
    assert [file["path"] for file in old] == ["docs/notes.md", "train.csv"]
    old_train = next(file for file in old if file["path"] == "train.csv")
    assert (
        member.get(f"{base}/files/{old_train['id']}/download").content
        == b"day,temp\n1,20\n"
    )
    # Existing download links and the legacy preview follow the latest version.
    assert member.get(f"{base}/download").content == b"day,temp\n1,20\n2,25\n"
    assert member.get(f"{base}/versions/latest").json()["number"] == 2
    with database() as db:
        user = learner(db)
        pinned, _ = source_files(db, user, "dataset", id)
        assert (pinned["format_version"], pinned["version"]) == (3, 2)
        assert pinned["path"] == f"input/weather-records-dataset-{id}"
        one = {**pinned, "version": 1}
        restored, files = resolve_attachment(db, user, one)
        assert restored["resolved_version"] == 1
        assert {file.filename for file in files} == {"train.csv", "docs/notes.md"}
        # Background runs stage the pinned version, streamed and read-only.
        work = tmp_path / "work"
        work.mkdir()
        stage_inputs(db, user, {"metadata": {"arena_input_sources": [one]}}, work)
        staged = work / pinned["path"] / "train.csv"
        assert staged.read_bytes() == b"day,temp\n1,20\n"
        prepare_permissions(work)
        assert stat.S_IMODE(staged.stat().st_mode) == 0o440
        assert (work / pinned["path"]).stat().st_mode & 0o200
        latest = {**pinned, "version": None}
        publish_latest = resolve_attachment(db, user, latest)[0]
        assert publish_latest["version"] is None
        assert publish_latest["resolved_version"] == 2

    assert member.delete(f"{base}/versions/1").status_code == 204
    with database() as db:
        with pytest.raises(Exception) as missing:
            resolve_attachment(db, learner(db), one)
        assert missing.value.status_code == 404
    assert member.get(f"{base}/versions/1").status_code == 404
    # Numbers are never reused, and the last version cannot be deleted.
    third = draft(member, base, carry_over=False)
    upload_file(member, third["id"], "readme.txt", b"No CSV in this version")
    assert publish(member, base, "Documentation only")["number"] == 3
    detail = member.get(base).json()
    assert (detail["filename"], detail["preview"]) == ("", [])
    assert member.get(f"{base}/download").status_code == 404
    with database() as db:
        with pytest.raises(ValueError):
            stage_inputs(
                db,
                learner(db),
                {"metadata": {"arena_inputs": [{"id": id}]}},
                tmp_path,
            )
    assert member.delete(f"{base}/versions/2").status_code == 204
    assert member.delete(f"{base}/versions/3").status_code == 409


def test_versions_and_files_follow_dataset_privacy(member):
    dataset = new_dataset(member, "Private sensor data")
    base = f"/api/datasets/{dataset['id']}"
    upload_file(member, dataset["draft_version"]["id"], "a.csv", b"x\n1\n")
    publish(member, base, "First")
    staged = draft(member, base)
    upload_file(member, staged["id"], "b.csv", b"y\n2\n")
    published_file = member.get(f"{base}/versions/1/files").json()[0]
    draft_file = next(
        file
        for file in member.get(f"{base}/versions/draft/files").json()
        if file["path"] == "b.csv"
    )
    assert [row["status"] for row in member.get(f"{base}/versions").json()] == [
        "draft",
        "published",
    ]

    member.post("/api/auth/logout")
    for path in (
        f"{base}/versions",
        f"{base}/versions/1/files",
        f"{base}/files/{published_file['id']}/download",
        f"{base}/files/{published_file['id']}/preview",
    ):
        assert member.get(path).status_code == 404, path
    switch(member, "stranger", register=True)
    assert member.get(f"{base}/versions").status_code == 404
    assert member.post(f"{base}/versions", json={}).status_code == 404
    denied = member.post(
        "/api/uploads", json={"version_id": staged["id"], "path": "x.csv", "size": 3}
    )
    assert denied.status_code == 404

    switch(member, "learner")
    assert (
        member.post(f"{base}/shares", json={"username": "stranger"}).status_code == 201
    )
    switch(member, "stranger")
    assert [row["number"] for row in member.get(f"{base}/versions").json()] == [1]
    assert member.get(f"{base}/versions/draft").status_code == 404
    assert member.get(f"{base}/files/{draft_file['id']}/download").status_code == 404
    assert (
        member.get(f"{base}/files/{published_file['id']}/download").content == b"x\n1\n"
    )
    assert (
        member.post(f"{base}/versions/draft/publish", json={"note": "x"}).status_code
        == 404
    )

    switch(member, "learner")
    assert (
        member.put(f"{base}/access", json={"visibility": "public"}).status_code == 200
    )
    member.post("/api/auth/logout")
    assert (
        member.get(f"{base}/files/{published_file['id']}/download").status_code == 200
    )
    assert member.get(f"{base}/files/{draft_file['id']}/download").status_code == 404
    with database() as db:
        db.get(Dataset, dataset["id"]).hidden = 1
        db.commit()
    assert member.get(f"{base}/versions").status_code == 404
    assert all(row["id"] != dataset["id"] for row in member.get("/api/datasets").json())


def npy_bytes():
    header = "{'descr': '<f8', 'fortran_order': False, 'shape': (3,), }"
    header += " " * (63 - (10 + len(header)) % 64) + "\n"
    return (
        b"\x93NUMPY\x01\x00"
        + struct.pack("<H", len(header))
        + header.encode("latin-1")
        + struct.pack("<3d", 1.0, 2.0, 3.0)
    )


def zip_bytes(count):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for index in range(count):
            archive.writestr(f"images/{index}.txt", "x")
        archive.writestr("../escape.txt", "x")
    return buffer.getvalue()


def test_safe_previews_and_downloads(member):
    dataset = new_dataset(member, "Mixed files")
    base = f"/api/datasets/{dataset['id']}"
    version_id = dataset["draft_version"]["id"]
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    contents = {
        "table.tsv": b"name\tscore\nann\t1.5\nbob\t2.5\ncy\t\n",
        "config.json": b'{"layers": [1, 2], "name": "net"}',
        "rows.jsonl": b'{"a": 1}\n{"a": 2}\n',
        "README.md": b"# Title\n<script>alert(1)</script>\n",
        "page.html": b"<html><script>alert(1)</script></html>",
        "icon.svg": b"<svg onload='alert(1)'></svg>",
        "data.xml": b"<root/>",
        "photo.png": png,
        "fake.png": b"<script>not an image</script>",
        "array.npy": npy_bytes(),
        "archive.zip": zip_bytes(600),
        "table.parquet": b"PAR1\x00\x00PAR1",
        "weights.bin": bytes(range(256)),
        'we"ird name.txt': b"quoted",
    }
    for path, content in contents.items():
        upload_file(member, version_id, path, content)
    for path in (
        "../escape.csv",
        "/absolute.csv",
        "a\\b.csv",
        "C:/x.csv",
        "a//b.csv",
        "a/./b.csv",
        "bad\nname.csv",
    ):
        response = member.post(
            "/api/uploads", json={"version_id": version_id, "path": path, "size": 3}
        )
        assert response.status_code == 422, path
    publish(member, base, "Mixed formats")
    files = {
        file["path"]: file for file in member.get(f"{base}/versions/1/files").json()
    }
    assert files["photo.png"]["type"] == "image" and files["weights.bin"]["size"] == 256

    def view(path):
        response = member.get(f"{base}/files/{files[path]['id']}/preview")
        assert response.status_code == 200, response.text
        return response.json()

    table = view("table.tsv")
    assert table["format"] == "table" and table["columns"] == ["name", "score"]
    score = table["summary"][1]
    assert (score["type"], score["min"], score["max"], score["missing"]) == (
        "number",
        1.5,
        2.5,
        1,
    )
    assert view("config.json")["text"].startswith('{\n  "layers"')
    assert view("rows.jsonl")["format"] == "json"
    readme = view("README.md")
    assert readme["format"] == "markdown" and "<script>" in readme["text"]
    for path in (
        "page.html",
        "icon.svg",
        "data.xml",
        "fake.png",
        "table.parquet",
        "weights.bin",
    ):
        assert view(path)["format"] == "download", path
    assert "pyarrow" in view("table.parquet")["message"]
    image = view("photo.png")
    assert image["format"] == "image" and image["url"].endswith("/raw")
    raw = member.get(image["url"])
    assert raw.headers["content-type"] == "image/png"
    assert raw.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in raw.headers["content-security-policy"]
    for path in ("icon.svg", "page.html", "fake.png"):
        assert member.get(f"{base}/files/{files[path]['id']}/raw").status_code == 415
    download = member.get(f"{base}/files/{files['page.html']['id']}/download")
    assert download.headers["content-type"] == "application/octet-stream"
    assert download.headers["content-disposition"].startswith("attachment;")
    assert download.headers["x-content-type-options"] == "nosniff"
    quoted_id = files['we"ird name.txt']["id"]
    quoted = member.get(f"{base}/files/{quoted_id}/download")
    assert 'filename="we_ird name.txt"' in quoted.headers["content-disposition"]
    array = view("array.npy")
    assert (array["dtype"], array["shape"], array["values"]) == (
        "<f8",
        [3],
        [1.0, 2.0, 3.0],
    )
    archive = view("archive.zip")
    assert archive["format"] == "archive" and archive["total_entries"] == 601
    assert len(archive["entries"]) == 500 and archive["truncated"]
    # The notebook input preview uses the same safe previewer for version files.
    notebook_preview = member.get(
        f"/api/input-sources/dataset/{dataset['id']}/files/{files['page.html']['id']}/preview?file_kind=version-file"
    )
    assert notebook_preview.json()["format"] == "download"


def test_zip_listing_refuses_huge_member_lists_before_parsing():
    declared = struct.pack("<4sHHHHIIH", b"PK\x05\x06", 0, 0, 60000, 60000, 100, 0, 0)
    result = preview(io.BytesIO(declared), "bomb.zip", len(declared))
    assert result["entries"] == [] and result["total_entries"] == 60000
    zip64 = struct.pack(
        "<4sQHHIIQQQQ", b"PK\x06\x06", 44, 45, 45, 0, 0, 2**40, 2**40, 2**40, 0
    )
    locator = struct.pack("<4sIQI", b"PK\x06\x07", 0, 0, 1)
    end = struct.pack(
        "<4sHHHHIIH", b"PK\x05\x06", 0, 0, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0
    )
    data = zip64 + locator + end
    result = preview(io.BytesIO(data), "bomb.zip", len(data))
    assert result["entries"] == [] and result["total_entries"] == 2**40
    unsafe = zip_bytes(1)
    listing = preview(io.BytesIO(unsafe), "a.zip", len(unsafe))
    assert [entry["unsafe_path"] for entry in listing["entries"]] == [False, True]
    assert preview(io.BytesIO(b"not a zip"), "a.zip", 9)["format"] == "download"


def test_model_variations_versions_card_and_notebook_inputs(member, tmp_path):
    created = member.post(
        "/api/models",
        json={
            "title": "Trained weights",
            "description": "A small network",
            "framework": "PyTorch",
            "license": "MIT",
        },
    )
    assert created.status_code == 201, created.text
    model = created.json()
    base = f"/api/models/{model['id']}"
    for section in (
        "## Overview",
        "## Intended use",
        "## Training data",
        "## Evaluation",
        "## Limitations & bias",
        "## License",
        "## How to use",
    ):
        assert section in model["card"]
    detail = member.get(base).json()
    assert detail["input_available"] is False
    assert [(row["framework"], row["slug"]) for row in detail["variations"]] == [
        ("pytorch", "default")
    ]
    variation = member.post(
        f"{base}/variations", json={"framework": "pytorch", "slug": "base"}
    )
    assert variation.status_code == 201, variation.text
    variation = variation.json()
    assert (
        member.post(
            f"{base}/variations", json={"framework": "pytorch", "slug": "base"}
        ).status_code
        == 409
    )
    for invalid in (
        {"framework": "pytorch", "slug": "Bad Slug"},
        {"framework": "caffe", "slug": "x"},
    ):
        assert member.post(f"{base}/variations", json=invalid).status_code == 422
    scope = f"{base}/variations/{variation['id']}"
    staged = draft(member, scope)
    upload_file(member, staged["id"], "weights.pt", b"version-one")
    assert publish(member, scope, "First weights")["number"] == 1
    detail = member.get(base).json()
    assert detail["input_available"] is True
    listed = next(row for row in detail["variations"] if row["slug"] == "base")
    folder = f"input/trained-weights-pytorch-base-model-{model['id']}"
    assert listed["input_path"] == folder
    assert (
        folder in listed["snippet"]
        and 'torch.load(model_dir / "weights.pt"' in listed["snippet"]
    )
    assert any(
        item["id"] == model["id"]
        for item in member.get("/api/input-sources?kind=model").json()["items"]
    )
    with database() as db:
        user = learner(db)
        manifest, files = source_files(db, user, "model", model["id"])
        assert (manifest["variation_id"], manifest["version"]) == (variation["id"], 1)
        assert manifest["path"] == folder
    upload_file(member, draft(member, scope)["id"], "weights.pt", b"version-two")
    publish(member, scope, "Retrained")
    with database() as db:
        user = learner(db)
        _, pinned = resolve_attachment(db, user, manifest)
        assert pinned[0].read(db) == b"version-one"
        _, latest = resolve_attachment(db, user, {**manifest, "version": None})
        assert latest[0].read(db) == b"version-two"
        stage_inputs(
            db, user, {"metadata": {"arena_input_sources": [manifest]}}, tmp_path
        )
        assert (tmp_path / folder / "weights.pt").read_bytes() == b"version-one"
        with pytest.raises(Exception):
            resolve_attachment(
                db, user, {k: v for k, v in manifest.items() if k != "variation_id"}
            )

    card = member.put(
        f"{base}/card", json={"card": "# Updated\n<img src=x onerror=alert(1)>"}
    )
    assert card.status_code == 200
    switch(member, "stranger", register=True)
    assert member.put(f"{base}/card", json={"card": "defaced"}).status_code == 404
    assert (
        member.post(
            f"{base}/variations", json={"framework": "onnx", "slug": "x"}
        ).status_code
        == 404
    )
    assert len(member.get(f"{scope}/versions").json()) == 2
    with database() as db:
        db.get(ModelCard, model["id"]).hidden = 1
        db.commit()
    assert member.get(f"{base}/variations").status_code == 404
    assert member.get(f"{scope}/versions/1/files").status_code == 404

    switch(member, "learner")
    assert member.delete(f"{base}/variations/{variation['id']}").status_code == 204
    assert member.get(base).json()["input_available"] is False
    with database() as db:
        assert not db.scalar(
            select(func.count())
            .select_from(ResourceVersion)
            .where(
                ResourceVersion.kind == "model",
                ResourceVersion.resource_id == model["id"],
            )
        )
        owner = learner(db).id
        assert not db.scalar(
            select(func.count())
            .select_from(StoredFile)
            .where(StoredFile.owner_id == owner)
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(WorkFileDeletion)
                .where(WorkFileDeletion.kind == "artifact")
            )
            >= 2
        )
    assert member.delete(f"/api/work/models/{model['id']}").status_code == 204


def test_editor_attach_version_options_and_large_sources(member, monkeypatch):
    from app import input_sources
    from app.notebook_runtime import get_hub
    from test_input_sources import Hub

    hub = Hub()
    app.dependency_overrides[get_hub] = lambda: hub
    dataset = new_dataset(member, "Attach options")
    base = f"/api/datasets/{dataset['id']}"
    upload_file(member, dataset["draft_version"]["id"], "a.csv", b"x\n1\n")
    publish(member, base, "First")
    notebook = member.post(
        "/api/notebooks", json={"title": "Consumer", "code": "print(1)"}
    ).json()["id"]
    attach = f"/api/editor/notebooks/{notebook}/input-sources/dataset/{dataset['id']}"
    assert member.post(attach + "?version=abc").status_code == 422
    assert member.post(attach + "?version=9").status_code == 404
    latest = member.post(attach + "?version=latest").json()
    assert latest["version"] is None and latest["resolved_version"] == 1
    assert list(hub.files.values()) == [b"x\n1\n"]
    hub.files.clear()
    # Sources too large for the contents API are referenced but not copied.
    monkeypatch.setattr(input_sources, "INTERACTIVE_BYTES", 1)
    large = member.post(attach + "?version=1").json()
    assert large["version"] == 1 and large["interactive"] is False
    assert hub.files == {}
