"""Stored dataset and model blobs under DATA_DIR, with path and filename safety.

Blobs live in DATA_DIR/<store>/<storage_key>. Keys come from the database but are
still validated, and blobs are opened without following symlinks, so a tampered row
or a symlink planted in a store cannot read outside it. New blobs are written to a
hidden temporary name and atomically renamed into place.
"""

import os
import re
import secrets
import stat
import unicodedata
from pathlib import PurePosixPath

from .db import DATA_DIR

# Store folder -> WorkFileDeletion kind that removes one of its blobs.
STORES = {"uploads": "upload", "artifacts": "artifact"}
KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")
MAX_PATH = 240


def clean_path(value):
    """A safe relative file path inside a version, or ValueError.

    Rejects absolute paths, drive letters, backslashes, control characters and empty,
    `.` or `..` segments. Unicode is NFC-normalized so lookalike duplicates collide.
    """
    if not isinstance(value, str):
        raise ValueError("File paths must be text")
    path = unicodedata.normalize("NFC", value.strip())
    if (
        not path
        or len(path) > MAX_PATH
        or "\\" in path
        or ":" in path
        or any(ord(char) < 32 or ord(char) == 127 for char in path)
        or PurePosixPath(path).is_absolute()
        or any(part in ("", ".", "..") or len(part) > 120 for part in path.split("/"))
    ):
        raise ValueError(
            "Use a relative file path (up to 240 characters) without empty, dot or"
            " parent segments, backslashes, colons or control characters"
        )
    return path


def fallback_path(value, default="data.csv"):
    """Best-effort safe path for legacy names that predate clean_path."""
    try:
        return clean_path(value)
    except ValueError:
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", PurePosixPath(str(value)).name)
        name = name.strip("._")[:120]
        return name or default


def download_name(path):
    """Content-Disposition filename: the last segment without quotes or controls."""
    name = PurePosixPath(path).name
    name = "".join(
        char if ord(char) >= 32 and char not in '"\\;' and ord(char) != 127 else "_"
        for char in name
    )
    return name[:150] or "download"


def blob_path(store, key):
    if store not in STORES or not KEY.fullmatch(key or "") or ".." in key:
        raise ValueError("Invalid stored file reference")
    return DATA_DIR / store / key


def open_blob(store, key):
    """Open a stored regular file read-only; never follow a symlink or open a FIFO."""
    fd = os.open(
        blob_path(store, key),
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("Stored file is not a regular file")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def new_key(suffix=""):
    return secrets.token_hex(24) + suffix


def temporary_path(store, key):
    """Hidden sibling used while writing; never matches KEY, so it is never served."""
    blob_path(store, key)
    root = DATA_DIR / store
    root.mkdir(exist_ok=True)
    return root / f".{key}.{secrets.token_hex(4)}.tmp"


def store_bytes(store, content, suffix=""):
    """Write a small blob atomically and return its key."""
    key = new_key(suffix)
    temporary = temporary_path(store, key)
    try:
        with open(temporary, "xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, blob_path(store, key))
    finally:
        temporary.unlink(missing_ok=True)
    return key


def primary_store(db, dataset):
    """The store holding a dataset's legacy primary CSV (uploads unless recorded)."""
    from sqlalchemy import select
    from .models import StoredFile

    return (
        db.scalar(
            select(StoredFile.store)
            .where(StoredFile.storage_key == dataset.storage_key)
            .limit(1)
        )
        or "uploads"
    )


def primary_path(db, dataset):
    """The latest version's primary CSV of a dataset as a regular file, or None."""
    if not dataset.storage_key:
        return None
    try:
        path = blob_path(primary_store(db, dataset), dataset.storage_key)
    except ValueError:
        return None
    return path if path.is_file() and not path.is_symlink() else None


def copy_blob(store, key, target, limit=None):
    """Stream a blob into a new file at target (never into an existing path)."""
    copied = 0
    with open_blob(store, key) as source, open(target, "xb") as stream:
        while chunk := source.read(1024 * 1024):
            copied += len(chunk)
            if limit is not None and copied > limit:
                raise ValueError("Input file exceeds its staging limit")
            stream.write(chunk)
    return copied
