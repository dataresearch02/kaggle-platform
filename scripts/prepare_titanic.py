"""Download or validate the official Titanic files without changing Arena records."""

import argparse
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import ZipFile

URL = "https://www.kaggle.com/api/v1/competitions/data/download-all/titanic"
LIMIT = 10 * 1024 * 1024
FEATURES = (
    "PassengerId,Pclass,Name,Sex,Age,SibSp,Parch,Ticket,Fare,Cabin,Embarked".split(",")
)
FILES = {
    "train.csv": ([FEATURES[0], "Survived", *FEATURES[1:]], 891),
    "test.csv": (FEATURES, 418),
    "gender_submission.csv": (["PassengerId", "Survived"], 418),
}


class SafeRedirect(HTTPRedirectHandler):
    """Signed storage redirects must not receive Kaggle credentials."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https":
            raise ValueError("Refusing a non-HTTPS download redirect")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected and urlsplit(req.full_url).netloc != urlsplit(newurl).netloc:
            redirected.remove_header("Authorization")
        return redirected


def authorization():
    token = os.getenv("KAGGLE_API_TOKEN")
    if token:
        return "Bearer " + token.strip()
    username, key = os.getenv("KAGGLE_USERNAME"), os.getenv("KAGGLE_KEY")
    config = (
        Path(os.getenv("KAGGLE_CONFIG_DIR", str(Path.home() / ".kaggle")))
        / "kaggle.json"
    )
    if not (username and key) and config.is_file():
        values = json.loads(config.read_text())
        username, key = values.get("username"), values.get("key")
    if not (username and key):
        raise ValueError(
            "Configure Kaggle credentials locally or supply downloaded CSV files. Never paste API secrets into chat."
        )
    return "Basic " + base64.b64encode(f"{username}:{key}".encode()).decode()


def validate(contents):
    manifest = {}
    ids = {}
    for name, (headers, count) in FILES.items():
        raw = contents[name]
        if len(raw) > LIMIT:
            raise ValueError(f"{name} exceeds the file limit")
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        rows = list(reader)
        if reader.fieldnames != headers or len(rows) != count:
            raise ValueError(f"{name}: expected {count} rows and columns {headers}")
        if any(None in row or None in row.values() for row in rows):
            raise ValueError(f"{name}: inconsistent CSV row width")
        ids[name] = {row["PassengerId"] for row in rows}
        if len(ids[name]) != count or "" in ids[name]:
            raise ValueError(f"{name}: missing or duplicate PassengerId")
        if "Survived" in headers and any(
            row["Survived"] not in ("0", "1") for row in rows
        ):
            raise ValueError(f"{name}: Survived must contain binary values")
        manifest[name] = {
            "rows": count,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    if (
        ids["test.csv"] != ids["gender_submission.csv"]
        or ids["train.csv"] & ids["test.csv"]
    ):
        raise ValueError(
            "Training, test and sample-submission passenger IDs do not align"
        )
    return manifest


def download():
    request = Request(
        URL,
        headers={
            "Authorization": authorization(),
            "User-Agent": "Arena Titanic import",
        },
    )
    try:
        with build_opener(SafeRedirect()).open(request, timeout=60) as response:
            archive = response.read(LIMIT + 1)
    except HTTPError as error:
        raise ValueError(
            f"Kaggle returned HTTP {error.code}. Check credentials and accept the competition rules on Kaggle."
        ) from None
    if len(archive) > LIMIT:
        raise ValueError("Download exceeds the archive limit")
    with ZipFile(io.BytesIO(archive)) as source:
        contents = {}
        for name in FILES:
            if (
                source.namelist().count(name) != 1
                or source.getinfo(name).file_size > LIMIT
            ):
                raise ValueError(
                    f"Archive has a missing, duplicate or oversized {name}"
                )
            contents[name] = source.read(name)
    validate(contents)
    return contents


def prepare(directory, fetch=False):
    directory = Path(directory)
    contents = (
        download()
        if fetch
        else {name: (directory / name).read_bytes() for name in FILES}
    )
    files = validate(contents)
    directory.mkdir(parents=True, exist_ok=True)
    # Never replace files that a previous import or the user may have changed.
    for name, raw in contents.items():
        path = directory / name
        if path.exists() and path.read_bytes() != raw:
            raise ValueError(f"Refusing to overwrite different existing file: {path}")
    for name, raw in contents.items():
        path = directory / name
        if not path.exists():
            with path.open("xb") as target:
                target.write(raw)
    manifest = {
        "competition": "Titanic - Machine Learning from Disaster",
        "source": "https://www.kaggle.com/competitions/titanic",
        "retrieval": (
            "authenticated Kaggle download"
            if fetch
            else "user-supplied files; structure validated, origin not independently verified"
        ),
        "files": files,
        "arena_import_status": "pending",
        "scoring": "Official test labels are not included. gender_submission.csv is a prediction example, not ground truth.",
        "unavailable": [
            "private test labels",
            "other participants' private submissions",
            "private notebooks and outputs",
        ],
    }
    with tempfile.NamedTemporaryFile(
        mode="w", dir=directory, delete=False, suffix=".json"
    ) as output:
        json.dump(manifest, output, indent=2)
        output.write("\n")
    Path(output.name).replace(directory / "manifest.json")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path("data/imports/titanic/source")
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Use locally configured Kaggle credentials",
    )
    args = parser.parse_args()
    try:
        result = prepare(args.source, args.download)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Titanic preparation blocked: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
