"""Bounded, read-only previews of stored dataset and model files.

Nothing here executes or renders file contents. Every reader stops after a fixed
number of bytes, so a large or hostile file cannot exhaust memory: tables use the
first MiB, text the first 256 KiB, ZIP archives only their central directory (after
checking its declared size), and NumPy arrays only their header and a few values.
HTML, SVG and XML are never previewed; browsers only download them as attachments.
Parquet is listed as download-only because pyarrow is not part of the offline kit.
"""

import csv
import io
import json
import math
import re
import struct
import zipfile
from pathlib import PurePosixPath

TABLE_BYTES = 1024 * 1024
TABLE_ROWS = 100
TABLE_COLUMNS = 100
SUMMARY_ROWS = 10_000
CELL = 1000
TEXT_BYTES = 256 * 1024
TEXT_CHARS = 64_000
JSON_LINES = 50
ZIP_LISTED = 500
ZIP_MAX_ENTRIES = 10_000
ZIP_MAX_DIRECTORY = 16 * 1024 * 1024
IMAGE_BYTES = 20 * 1024 * 1024
IMAGE_TYPES = {
    ".png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    ".jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".gif": ("image/gif", (b"GIF87a", b"GIF89a")),
    ".webp": ("image/webp", ()),
}
UNSAFE = (".html", ".htm", ".xhtml", ".shtml", ".svg", ".svgz", ".xml", ".xsl", ".xslt")
TEXT = (
    ".txt", ".log", ".py", ".r", ".sql", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".rst", ".sh", ".conf", ".properties", ".vocab", ".tokens",
)  # fmt: skip
NPY_TYPES = {
    "<f8": "d", "<f4": "f", "<i8": "q", "<i4": "i", "<i2": "h", "|i1": "b",
    "<u8": "Q", "<u4": "I", "<u2": "H", "|u1": "B", "|b1": "?",
}  # fmt: skip


def file_type(path):
    suffix = PurePosixPath(path.lower()).suffix
    if suffix in (".csv", ".tsv"):
        return "table"
    if suffix == ".json":
        return "json"
    if suffix in (".jsonl", ".ndjson"):
        return "jsonl"
    if suffix in (".md", ".markdown"):
        return "markdown"
    if suffix in TEXT:
        return "text"
    if suffix in IMAGE_TYPES:
        return "image"
    if suffix == ".npy":
        return "npy"
    if suffix == ".zip":
        return "zip"
    if suffix == ".parquet":
        return "parquet"
    if suffix in UNSAFE:
        return "unsafe"
    return "binary"


def image_type(path, head):
    """The image media type when the extension and the file's magic bytes agree."""
    media_type, signatures = IMAGE_TYPES.get(
        PurePosixPath(path.lower()).suffix, (None, ())
    )
    if media_type == "image/webp":
        return media_type if head[:4] == b"RIFF" and head[8:12] == b"WEBP" else None
    if media_type and any(head.startswith(value) for value in signatures):
        return media_type
    return None


def download_only(message):
    return {"format": "download", "message": message}


def decode(content):
    """UTF-8 text, or None for binary content."""
    if b"\x00" in content:
        return None
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        # A multi-byte character cut at the read limit is still text.
        if exc.start < len(content) - 4:
            return None
        return content[: exc.start].decode("utf-8-sig")


def read_prefix(stream, limit):
    content = stream.read(limit + 1)
    return content[:limit], len(content) > limit


def number(value):
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def table(stream, path, size):
    content, truncated = read_prefix(stream, TABLE_BYTES)
    text = decode(content)
    if text is None:
        return download_only("This file is not UTF-8 text, so it cannot be previewed.")
    if truncated and "\n" in text:
        text = text[: text.rindex("\n")]
    delimiter = "\t" if path.lower().endswith(".tsv") else ","
    try:
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        header = [value[:CELL] for value in next(reader, [])]
        columns = header[:TABLE_COLUMNS]
        stats = [
            {"name": name, "values": 0, "missing": 0, "numeric": 0, "min": None,
             "max": None, "sum": 0.0, "distinct": set()}
            for name in columns
        ]  # fmt: skip
        rows, sampled = [], 0
        for row in reader:
            if sampled >= SUMMARY_ROWS:
                truncated = True
                break
            sampled += 1
            if len(rows) < TABLE_ROWS:
                rows.append([value[:CELL] for value in row[:TABLE_COLUMNS]])
            for column, value in zip(stats, row):
                if value.strip().lower() in ("", "na", "nan", "null", "none"):
                    column["missing"] += 1
                    continue
                column["values"] += 1
                if len(column["distinct"]) <= 1000:
                    column["distinct"].add(value[:200])
                parsed = number(value)
                if parsed is not None:
                    column["numeric"] += 1
                    column["sum"] += parsed
                    column["min"] = (
                        parsed if column["min"] is None else min(column["min"], parsed)
                    )
                    column["max"] = (
                        parsed if column["max"] is None else max(column["max"], parsed)
                    )
    except csv.Error:
        return text_preview(io.BytesIO(content), "text")
    summary = []
    for column in stats:
        numeric = column["values"] > 0 and column["numeric"] == column["values"]
        summary.append(
            {
                "name": column["name"],
                "type": "number" if numeric else "text",
                "values": column["values"],
                "missing": column["missing"],
                "distinct": min(len(column["distinct"]), 1000),
                "distinct_capped": len(column["distinct"]) > 1000,
                "min": column["min"] if numeric else None,
                "max": column["max"] if numeric else None,
                "mean": column["sum"] / column["numeric"] if numeric else None,
            }
        )
    return {
        "format": "table",
        "columns": columns,
        "rows": rows,
        "summary": summary,
        "sampled_rows": sampled,
        "total_columns": len(header),
        "truncated": truncated or len(header) > TABLE_COLUMNS or sampled > len(rows),
    }


def text_preview(stream, format="text"):
    content, truncated = read_prefix(stream, TEXT_BYTES)
    text = decode(content)
    if text is None:
        return download_only("This file is not UTF-8 text, so it cannot be previewed.")
    return {
        "format": format,
        "text": text[:TEXT_CHARS],
        "truncated": truncated or len(text) > TEXT_CHARS,
    }


def json_preview(stream, size):
    content, truncated = read_prefix(stream, TEXT_BYTES)
    text = decode(content)
    if text is None:
        return download_only("This file is not UTF-8 text, so it cannot be previewed.")
    if not truncated:
        try:
            pretty = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
            return {
                "format": "json",
                "text": pretty[:TEXT_CHARS],
                "truncated": len(pretty) > TEXT_CHARS,
            }
        except (ValueError, RecursionError):
            pass  # Invalid JSON is shown as text.
    return {"format": "json", "text": text[:TEXT_CHARS], "truncated": True, "raw": True}


def jsonl_preview(stream):
    content, truncated = read_prefix(stream, TEXT_BYTES)
    text = decode(content)
    if text is None:
        return download_only("This file is not UTF-8 text, so it cannot be previewed.")
    lines = text.splitlines()
    if truncated and lines:
        lines.pop()  # The last line may be incomplete.
    shown = []
    for line in lines[:JSON_LINES]:
        try:
            shown.append(json.dumps(json.loads(line), indent=2, ensure_ascii=False))
        except (ValueError, RecursionError):
            shown.append(line)
    output = "\n".join(shown)
    return {
        "format": "json",
        "text": output[:TEXT_CHARS],
        "truncated": truncated or len(lines) > JSON_LINES or len(output) > TEXT_CHARS,
    }


def npy_preview(stream):
    head = stream.read(12)
    if len(head) < 10 or head[:6] != b"\x93NUMPY" or head[6] not in (1, 2, 3):
        return download_only("This is not a readable NumPy .npy file.")
    if head[6] == 1:
        length, offset = struct.unpack("<H", head[8:10])[0], 10
    else:
        length, offset = struct.unpack("<I", head[8:12])[0], 12
    if length > 65536:
        return download_only("This NumPy header is too large to preview.")
    stream.seek(offset)
    header = stream.read(length).decode("latin-1")
    descr = re.search(r"'descr':\s*'([^']{1,32})'", header)
    order = re.search(r"'fortran_order':\s*(True|False)", header)
    shape = re.search(r"'shape':\s*\(([\d,\s]*)\)", header)
    if not (descr and order and shape):
        return download_only(
            "This NumPy array uses a structured type that cannot be previewed."
        )
    dimensions = [
        int(value) for value in shape.group(1).replace(" ", "").split(",") if value
    ]
    result = {
        "format": "array",
        "dtype": descr.group(1),
        "shape": dimensions,
        "fortran_order": order.group(1) == "True",
        "values": [],
    }
    code = NPY_TYPES.get(descr.group(1))
    count = math.prod(dimensions) if dimensions else 1
    if code:
        wanted = min(count, 20)
        item = struct.calcsize("<" + code)
        data = stream.read(wanted * item)
        wanted = len(data) // item
        result["values"] = [
            (
                value
                if not isinstance(value, float) or math.isfinite(value)
                else str(value)
            )
            for value in struct.unpack("<" + code * wanted, data[: wanted * item])
        ]
    result["truncated"] = count > len(result["values"])
    return result


def zip_directory(stream, size):
    """(entries, central directory size) from the end record, or None if not a ZIP."""
    tail_size = min(size, 65536 + 22)
    stream.seek(size - tail_size)
    tail = stream.read(tail_size)
    at = tail.rfind(b"PK\x05\x06")
    if at < 0 or len(tail) - at < 22:
        return None
    _, _, _, _, entries, directory, offset, _ = struct.unpack(
        "<4sHHHHIIH", tail[at : at + 22]
    )
    if entries == 0xFFFF or directory == 0xFFFFFFFF or offset == 0xFFFFFFFF:
        if at < 20 or tail[at - 20 : at - 16] != b"PK\x06\x07":
            return None
        record = struct.unpack("<4sIQI", tail[at - 20 : at])[2]
        if record > size - 56:
            return None
        stream.seek(record)
        zip64 = stream.read(56)
        if len(zip64) < 56 or zip64[:4] != b"PK\x06\x06":
            return None
        entries, directory = struct.unpack("<QQ", zip64[32:48])
    return entries, directory


def zip_preview(stream, size):
    try:
        found = zip_directory(stream, size)
        if found is None:
            return download_only("This is not a readable ZIP archive.")
        entries, directory = found
        if entries > ZIP_MAX_ENTRIES or directory > ZIP_MAX_DIRECTORY:
            return {
                "format": "archive",
                "entries": [],
                "total_entries": entries,
                "message": f"This archive declares {entries:,} members; listings are"
                f" limited to {ZIP_MAX_ENTRIES:,}. Download it to inspect.",
                "truncated": True,
            }
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            members = archive.infolist()[:ZIP_MAX_ENTRIES]
    except (zipfile.BadZipFile, OSError, ValueError, struct.error, NotImplementedError):
        return download_only("This ZIP archive could not be read.")
    listed, total, compressed = [], 0, 0
    for info in members:
        total += info.file_size
        compressed += info.compress_size
        if len(listed) >= ZIP_LISTED:
            continue
        name = "".join(char if ord(char) >= 32 else "?" for char in info.filename)[:300]
        listed.append(
            {
                "name": name,
                "size": info.file_size,
                "compressed_size": info.compress_size,
                "directory": info.is_dir(),
                # Archive paths that would escape a folder if someone extracted them.
                "unsafe_path": name.startswith(("/", "\\"))
                or ".." in re.split(r"[\\/]", name)
                or bool(re.match(r"^[A-Za-z]:", name)),
            }
        )
    ratio = total / compressed if compressed else 0
    return {
        "format": "archive",
        "entries": listed,
        "total_entries": len(members),
        "uncompressed_size": total,
        # Extreme compression is how zip bombs work; Arena never extracts archives.
        "suspicious": ratio > 100 and total > 100 * 1024 * 1024,
        "truncated": len(members) > len(listed),
    }


def preview(stream, path, size):
    """Preview JSON for a binary stream positioned at 0; see module docstring."""
    kind = file_type(path)
    result = {"type": kind, "size": size}
    if kind == "unsafe":
        result.update(
            download_only(
                "HTML, SVG and XML files are never displayed in Arena. Download the file"
                " to inspect it."
            )
        )
    elif kind == "table":
        result.update(table(stream, path, size))
    elif kind == "json":
        result.update(json_preview(stream, size))
    elif kind == "jsonl":
        result.update(jsonl_preview(stream))
    elif kind in ("text", "markdown"):
        result.update(text_preview(stream, kind))
    elif kind == "image":
        media_type = image_type(path, stream.read(16))
        if not media_type:
            result.update(
                download_only("The file contents do not match its image type.")
            )
        elif size > IMAGE_BYTES:
            result.update(
                download_only("This image is larger than 20 MB; download it.")
            )
        else:
            result.update(format="image", media_type=media_type)
    elif kind == "npy":
        result.update(npy_preview(stream))
    elif kind == "zip":
        result.update(zip_preview(stream, size))
    elif kind == "parquet":
        result.update(
            download_only(
                "Parquet previews need pyarrow, which is not installed on this server."
                " Download the file or read it with pandas in a notebook."
            )
        )
    else:
        sample = stream.read(8192)
        if sample and decode(sample) is not None:
            stream.seek(0)
            result.update(text_preview(stream))
        else:
            result.update(download_only("Binary file: download it to use it."))
    return result
