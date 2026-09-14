"""Idempotent startup import of the offline practice competitions in practice_data/.

Each pack holds data prepared ahead of time from scikit-learn bundled datasets:
train.csv, test.csv, sample_submission.csv, solution.csv (id,prediction,Usage) and
meta.json. Everything needed is local, so the import works fully offline. A
SampleImport receipt per pack makes restarts a no-op, even after administrators
edit or delete the imported content. Set ARENA_IMPORT_PRACTICE=false to skip it.
"""

import csv
import hashlib
import io
import json
import secrets
from pathlib import Path

from sqlalchemy import select

from .competition_metadata import add_file, ensure_profile
from .db import DATA_DIR
from .models import (
    ArtifactVersion,
    ChallengeDetails,
    Competition,
    CompetitionOverview,
    Dataset,
    DatasetAccess,
    SampleImport,
    User,
)

PRACTICE = Path(__file__).with_name("practice_data")
OWNER = "arena"
# Stored for practice competitions; the API reports them as having no deadline.
PRACTICE_DEADLINE = "9999-12-31T23:59:59+00:00"
FILES = ("train.csv", "test.csv", "sample_submission.csv", "solution.csv")
METRICS = {"accuracy": "Accuracy", "rmse": "RMSE", "mae": "MAE", "logloss": "LogLoss"}
EVALUATION = {
    "Accuracy": (
        "Submissions are scored by **accuracy**, the share of test rows whose predicted "
        "class equals the true class:\n\n"
        "$$\\mathrm{Accuracy}=\\frac{1}{n}\\sum_{i=1}^{n}[\\hat y_i = y_i]$$\n\n"
        "Higher is better; 1.0 means every prediction is correct. Submit class labels, "
        "not probabilities."
    ),
    "RMSE": (
        "Submissions are scored by **root mean squared error**:\n\n"
        "$$\\mathrm{RMSE}=\\sqrt{\\frac{1}{n}\\sum_{i=1}^{n}(y_i-\\hat y_i)^2}$$\n\n"
        "Lower is better; 0 means every prediction is exact. Large errors cost more "
        "than small ones."
    ),
    "MAE": (
        "Submissions are scored by **mean absolute error**:\n\n"
        "$$\\mathrm{MAE}=\\frac{1}{n}\\sum_{i=1}^{n}|y_i-\\hat y_i|$$\n\nLower is better."
    ),
    "LogLoss": (
        "Submissions are scored by **binary log loss** on predicted probabilities "
        "between 0 and 1. Lower is better."
    ),
}


def receipt_key(slug):
    return f"practice-{slug}-v1"


def load_pack(folder):
    """Read and validate a pack before anything is written."""
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    files = {name: (folder / name).read_text(encoding="utf-8") for name in FILES}
    reader = csv.DictReader(io.StringIO(files["solution.csv"]))
    if reader.fieldnames != ["id", "prediction", "Usage"]:
        raise ValueError(f"{folder.name}: solution.csv needs id,prediction,Usage")
    solution, usage = {}, {}
    for row in reader:
        if row["id"] in solution or row["Usage"] not in ("Public", "Private"):
            raise ValueError(f"{folder.name}: invalid solution row {row['id']!r}")
        solution[row["id"]] = float(row["prediction"])
        usage[row["id"]] = row["Usage"]
    for name in ("test.csv", "sample_submission.csv"):
        ids = [row["id"] for row in csv.DictReader(io.StringIO(files[name]))]
        if len(ids) != len(solution) or set(ids) != set(solution):
            raise ValueError(f"{folder.name}: {name} ids do not match solution.csv")
    metric = METRICS[meta["metric"].lower()]
    return meta, files, solution, usage, metric


def texts(meta, files, metric):
    target = meta["target"]
    header = next(csv.reader(io.StringIO(files["train.csv"])))
    features = [name for name in header if name not in ("id", target)]
    citation = f"{meta['source']}\n\nLicense: {meta['license']}."
    file_list = (
        "| File | Rows | Contents |\n| --- | --- | --- |\n"
        f"| `train.csv` | {meta['train_rows']} | `id`, {len(features)} features and "
        f"the target `{target}` |\n"
        f"| `test.csv` | {meta['test_rows']} | `id` and the same features, without "
        "the target |\n"
        f"| `sample_submission.csv` | {meta['test_rows']} | The required submission "
        "format: `id,prediction` |"
    )
    feature_list = ", ".join(f"`{name}`" for name in features[:20]) + (
        f" and {len(features) - 20} more" if len(features) > 20 else ""
    )
    description = (
        f"{meta['subtitle']}.\n\n{meta['about']}\n\n"
        f"This is an offline practice competition for a {meta['task']} task: it has no "
        "deadline and no prizes, and everything needed to take part is available in "
        f"Arena. Train on train.csv, predict `{target}` for every row of test.csv and "
        "submit a CSV with exactly the columns id,prediction.\n\n"
        f"Source: {meta['source']} License: {meta['license']}."
    )
    overview = {
        "prize_details": "Practice competition: no prizes and no deadline. Submit as "
        "often as you like to learn and compare approaches.",
        "getting_started": (
            "1. Join the competition, then open **Data** to preview and download the "
            "files.\n"
            f"2. Train a model on `train.csv` to predict `{target}`; hold out part of "
            "the training data to validate it.\n"
            "3. Predict every row of `test.csv` and write a CSV with exactly the "
            "columns `id,prediction` (see `sample_submission.csv`).\n"
            "4. Upload it in **Submissions**. Your best score appears on the "
            "leaderboard."
        ),
        "evaluation": EVALUATION[metric]
        + "\n\nThe public leaderboard is scored on the test rows marked Public; the "
        "remaining rows are held out for the private leaderboard.",
        "data_description": (
            f"## Task\n\n{meta['about']}\n\nTask type: {meta['task']}. Target column: "
            f"`{target}`.\n\n## Files\n\n{file_list}\n\n## Features\n\n{feature_list}"
            f"\n\n## Citation and license\n\n{citation}"
        ),
    }
    documentation = (
        f"{meta['about']}\n\n{file_list}\n\nThe matching practice competition scores "
        f"predictions of `{target}` for test.csv."
    )
    return description, overview, documentation, citation


def import_practice_competitions(db):
    owner = db.scalar(select(User).where(User.username == OWNER))
    if not owner:
        return []
    results = []
    for folder in sorted(PRACTICE.iterdir()):
        if not (folder / "meta.json").is_file():
            continue
        receipt = db.get(SampleImport, receipt_key(folder.name))
        if receipt:
            results.append(
                {"status": "already imported", **json.loads(receipt.manifest)}
            )
        else:
            results.append(import_pack(db, owner, folder))
    return results


def import_pack(db, owner, folder):
    meta, files, solution, usage, metric = load_pack(folder)
    description, overview, documentation, citation = texts(meta, files, metric)
    license = meta["license"][:80]
    written = []

    def store(directory, content, suffix=""):
        root = DATA_DIR / directory
        root.mkdir(parents=True, exist_ok=True)
        key = secrets.token_hex(16 if suffix else 24) + suffix
        path = root / key
        written.append(path)
        path.write_bytes(content.encode("utf-8"))
        return key

    try:
        dataset = Dataset(
            owner_id=owner.id,
            title=f"{meta['title']} data",
            description=f"{meta['subtitle']}.\n\n{documentation}\n\n{citation}",
            tags="practice," + meta["task"].replace(" ", "-") + ",tabular",
            license=license,
            filename="train.csv",
            storage_key=store("uploads", files["train.csv"], ".csv"),
            size=len(files["train.csv"].encode("utf-8")),
        )
        db.add(dataset)
        db.flush()
        db.add(DatasetAccess(dataset_id=dataset.id, visibility="public"))
        profile = ensure_profile(db, dataset)
        profile.citation, profile.documentation = citation, documentation
        described = json.loads(profile.columns_json)
        for column in described:
            if column["name"] == "id":
                column["description"] = "Row identifier used in submissions"
            elif column["name"] == meta["target"]:
                column["description"] = "Target to predict (training data only)"
        profile.columns_json = json.dumps(described)
        for name in ("test.csv", "sample_submission.csv"):
            content = files[name].encode("utf-8")
            db.add(
                ArtifactVersion(
                    kind="datasets",
                    resource_id=dataset.id,
                    path=name,
                    storage_key=store("artifacts", files[name]),
                    size=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                )
            )
        competition = Competition(
            title=meta["title"][:160],
            description=description,
            category="Practice",
            metric=metric,
            deadline=PRACTICE_DEADLINE,
            solution=json.dumps(solution),
            # Public/Private row assignment for the two leaderboards.
            solution_usage=json.dumps(usage),
            prize="Practice",
            max_daily_submissions=20,
        )
        db.add(competition)
        db.flush()
        db.add(
            ChallengeDetails(
                competition_id=competition.id,
                owner_id=owner.id,
                kind="competition",
                test_csv=files["test.csv"],
            )
        )
        # Creating the overview first stops backfill_metadata adding default files.
        db.add(CompetitionOverview(competition_id=competition.id, **overview))
        for path, role, name, text in [
            ("train/train.csv", "train", "train.csv", "Training data with the target."),
            ("test/test.csv", "test", "test.csv", "Features to predict, one per id."),
            (
                "submission/sample_submission.csv",
                "submission",
                "sample_submission.csv",
                "Submission format example: replace the predictions.",
            ),
        ]:
            add_file(
                db,
                competition.id,
                path,
                role,
                files[name],
                description=text,
                license=license,
                source_dataset_id=dataset.id,
            )
        manifest = {
            "slug": folder.name,
            "dataset": dataset.id,
            "competition": competition.id,
        }
        db.add(
            SampleImport(key=receipt_key(folder.name), manifest=json.dumps(manifest))
        )
        db.commit()
        return {"status": "imported", **manifest}
    except Exception:
        db.rollback()
        for path in written:
            path.unlink(missing_ok=True)
        raise
