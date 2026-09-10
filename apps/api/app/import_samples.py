"""Explicit, offline import of attributed Kaggle datasets and local practice content.

Run inside the API container: python -m app.import_samples
Nothing is imported at application startup. A database receipt makes reruns a no-op.
"""

import csv
import argparse
from sqlalchemy import select
import hashlib
import io
import json
import math
from pathlib import Path
import secrets
from datetime import datetime, timedelta, timezone

from .auth import hash_password
from .db import Base, DATA_DIR, SessionLocal, engine
from .models import (
    ChallengeDetails,
    Competition,
    CompetitionPost,
    CompetitionResource,
    Dataset,
    Discussion,
    Notebook,
    NotebookPublication,
    SampleImport,
    User,
)

SAMPLES = Path(__file__).with_name("sample_data")
PACK = "kaggle-practice-v1"


def csv_text(rows, columns):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def load_sources():
    sources = json.loads((SAMPLES / "sources.json").read_text())
    for source in sources:
        content = (SAMPLES / source["file"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != source["sha256"]:
            raise ValueError(f"Source checksum mismatch: {source['file']}")
        source["content"] = content.decode("utf-8")
    return sources


def split_rows(source):
    rows = []
    for index, row in enumerate(csv.DictReader(io.StringIO(source["content"])), 1):
        try:
            if not math.isfinite(float(row[source["target"]])):
                continue
        except ValueError:
            continue
        rows.append({"id": str(index), **{k: v for k, v in row.items() if k != "Id"}})
    # Stable interleaved split preserves species represented in both partitions.
    train = [row for index, row in enumerate(rows) if index % 5 != 0]
    test = [row for index, row in enumerate(rows) if index % 5 == 0]
    columns = list(rows[0])
    return train, test, columns


def notebook_code(source, train_csv, test_csv, baseline):
    header = (
        "# Original Arena example, not a copied Kaggle notebook.\n"
        f"# Data source (CC0-1.0): {source['url']}\n"
        f"# {source['credit']}\n"
        "# Embedded CSVs make this example runnable without downloads or credentials.\n"
    )
    if not baseline:
        return header + (
            "import io\nimport pandas as pd\nimport matplotlib.pyplot as plt\n\n"
            f"df = pd.read_csv(io.StringIO({train_csv!r}))\n"
            "print('Training rows:', len(df))\nprint(df.head().to_string(index=False))\n"
            "print('Missing values:')\nprint(df.isna().sum())\n"
            f"print(df.groupby({source['group']!r})[{source['target']!r}].describe())\n"
            f"df.hist(column={source['target']!r}, bins=20)\nplt.show()\n"
        )
    return header + (
        "import csv\nimport io\nfrom collections import defaultdict\nfrom statistics import mean\n\n"
        f"train = list(csv.DictReader(io.StringIO({train_csv!r})))\n"
        f"test = list(csv.DictReader(io.StringIO({test_csv!r})))\n"
        "groups = defaultdict(list)\nfor row in train:\n"
        f"    groups[row[{source['group']!r}]].append(float(row[{source['target']!r}]))\n"
        "averages = {group: mean(values) for group, values in groups.items()}\n"
        f"fallback = mean(float(row[{source['target']!r}]) for row in train)\n"
        f"output_name = '{source['slug']}-submission.csv'\n"
        "with open(output_name, 'w', newline='') as output:\n"
        "    writer = csv.writer(output)\n    writer.writerow(['id', 'prediction'])\n"
        "    for row in test:\n"
        f"        writer.writerow([row['id'], averages.get(row[{source['group']!r}], fallback)])\n"
        "print('Created', output_name, 'with', len(test), 'predictions.')\n"
        "try:\n    from IPython.display import display\n"
        "    with open(output_name) as output:\n"
        "        display({'text/csv': output.read()}, raw=True)\n"
        "except ImportError:\n    print('CSV saved in the current directory.')\n"
        "print('Use Download CSV below, join the practice competition, then submit on Leaderboard.')\n"
    )


def sample_document(source, train_csv, test_csv, baseline):
    """Original narrative cells interleaved with the existing executable examples."""
    code = notebook_code(source, train_csv, test_csv, baseline)
    name = "Iris" if source["slug"] == "iris" else "Palmer penguins"
    target, group = source["target"], source["group"]
    training = list(csv.DictReader(io.StringIO(train_csv)))
    testing = list(csv.DictReader(io.StringIO(test_csv)))
    columns = list(training[0])
    cells = []

    def markdown(value):
        cells.append(
            {
                "id": f"sample-{len(cells)}",
                "cell_type": "markdown",
                "metadata": {},
                "source": value,
            }
        )

    def python(value):
        cells.append(
            {
                "id": f"sample-{len(cells)}",
                "cell_type": "code",
                "metadata": {},
                "source": value,
                "execution_count": None,
                "outputs": [],
            }
        )

    markdown(
        f"# {name}: {'a first submission' if baseline else 'explore the training data'}\n\n"
        f"This guided example uses **{name}** measurements to {'predict' if baseline else 'understand'} "
        f"`{target}`. The code is an original Arena example using attributed open data.\n\n"
        "## What you will learn\n\n"
        "1. Load the embedded training data.\n2. Inspect measurements and group differences.\n"
        + (
            "3. Create a prediction file for the practice competition.\n"
            if baseline
            else "3. Visualize the target and identify questions for modeling.\n"
        )
    )
    markdown(
        "## Dataset at a glance\n\n"
        "| Property | Value |\n| --- | --- |\n"
        f"| Training rows | {len(training)} |\n| Held-out rows | {len(testing)} |\n"
        f"| Prediction target | `{target}` |\n| Group column | `{group}` |\n"
        f"| License | {source['license']} |\n\n"
        "### Column guide\n\n| Column | Role |\n| --- | --- |\n"
        + "\n".join(
            f"| `{column}` | "
            + (
                "Row identifier"
                if column == "id"
                else (
                    "Target (training only)"
                    if column == target
                    else "Group label" if column == group else "Available feature"
                )
            )
            + " |"
            for column in columns
        )
        + "\n\n> **Note:** Every fifth usable row is held out using a deterministic split. "
        "This is a small learning exercise; use a separate validation split to compare models fairly."
    )
    markdown(
        "## 1. Load the data\n\nCSV data is embedded in the next cell, so no downloads or credentials are needed. "
        "Fork the notebook to run it, then execute cells from top to bottom.\n\n"
        "> **Data quality:** Rows without a finite target were excluded when creating this sample. "
        "Other columns can still contain missing values."
    )
    if baseline:
        first, rest = code.split("groups = defaultdict(list)", 1)
        second, third = ("groups = defaultdict(list)" + rest).split("output_name =", 1)
        python(first)
        markdown(
            f"## 2. Build a group-mean baseline\n\nFor each `{group}`, calculate the average training "
            f"`{target}`. A group absent from training uses the overall mean.\n\n"
            "| Situation | Prediction |\n| --- | --- |\n| Known group | Mean target for that group |\n"
            "| Unseen group | Mean target across all training rows |\n\n"
            "> **Avoid leakage:** Compute these averages from training labels only."
        )
        python(second)
        markdown(
            "## 3. Export a submission\n\nThe next cell writes a CSV with exactly two columns: "
            "`id` and `prediction`. It also displays a download link in the cell output.\n\n"
            "### Submission checklist\n\n- [ ] Run every code cell.\n- [ ] Download the generated CSV.\n"
            "- [ ] Join the matching practice competition.\n- [ ] Upload the CSV on its Leaderboard tab."
        )
        python("output_name =" + third)
        markdown(
            "## Next experiments\n\nTry a median baseline or a model using additional measurements. "
            "Compare approaches on your own validation split before submitting.\n\n"
            "### Evaluation\n\nThe practice competition uses root mean squared error (RMSE):\n\n"
            "$$\\mathrm{RMSE}=\\sqrt{\\frac{1}{n}\\sum_{i=1}^{n}(y_i-\\hat y_i)^2}$$\n\nLower is better."
        )
    else:
        first, rest = code.split("print('Training rows:'", 1)
        second, third = ("print('Training rows:'" + rest).split("df.hist(", 1)
        python(first)
        markdown(
            f"## 2. Inspect the measurements\n\nReview the first rows, missing-value counts, and target "
            f"statistics grouped by `{group}`.\n\n"
            "| Check | Question |\n| --- | --- |\n| Missing values | Which features need imputation? |\n"
            "| Group counts | Are some groups underrepresented? |\n| Target range | Are unusual values plausible? |"
        )
        python(second)
        markdown(
            f"## 3. Visualize `{target}`\n\nThe histogram summarizes the training target distribution. "
            "Look for skew, multiple peaks, and unusual observations.\n\n"
            "> **Interpretation note:** A pattern in this sample is an observation, not evidence of causation."
        )
        python("df.hist(" + third)
        markdown(
            "## Questions to investigate\n\n- How does the target vary between groups?\n"
            "- Would a group-specific baseline improve on an overall mean?\n"
            "- Which features could help a model generalize?\n\n"
            "### Next step\n\nOpen the matching **submission baseline** sample to build a prediction CSV."
        )
    markdown(
        f"## Sources and attribution\n\n[Dataset source]({source['url']}) · {source['license']}\n\n"
        f"{source['credit']}\n\nThese explanations and notebook code were written for Arena. "
        "Outputs appear after you run and publish your own fork; no example results are fabricated."
    )
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "name": "python3",
                "display_name": "Python 3",
                "language": "python",
            },
            "arena_sample_revision": 2,
        },
        "cells": cells,
    }


def update_sample_notebooks(db):
    receipt = db.get(SampleImport, PACK)
    if not receipt:
        return {"status": "samples not imported", "updated": [], "skipped": []}
    manifest = json.loads(receipt.manifest)
    owner = db.scalar(select(User).where(User.username == manifest["owner"]))
    updated, skipped = [], []
    for index, source in enumerate(load_sources()):
        train, test, columns = split_rows(source)
        train_csv = csv_text(train, columns)
        test_csv = csv_text(
            test, [column for column in columns if column != source["target"]]
        )
        for offset, baseline in enumerate((False, True)):
            notebook_id = manifest["notebooks"][index * 2 + offset]
            notebook = db.get(Notebook, notebook_id)
            if (
                not notebook
                or not owner
                or notebook.owner_id != owner.id
                or notebook.code != notebook_code(source, train_csv, test_csv, baseline)
            ):
                skipped.append(notebook_id)
                continue
            publication = db.get(NotebookPublication, notebook_id)
            if (
                publication
                and json.loads(publication.document)
                .get("metadata", {})
                .get("arena_sample_revision")
                == 2
            ):
                skipped.append(notebook_id)
                continue
            if not publication:
                publication = NotebookPublication(notebook_id=notebook_id)
                db.add(publication)
            publication.document = json.dumps(
                sample_document(source, train_csv, test_csv, baseline)
            )
            updated.append(notebook_id)
    db.commit()
    return {"status": "updated", "updated": updated, "skipped": skipped}


def import_samples(db, data_dir=DATA_DIR):
    receipt = db.get(SampleImport, PACK)
    if receipt:
        return {"status": "already imported", **json.loads(receipt.manifest)}
    sources = load_sources()  # Verify everything before creating records or files.
    files = []
    manifest = {"competitions": [], "datasets": [], "notebooks": [], "discussions": []}
    try:
        # Separate curator identity; never assign imported content to a real user.
        owner = User(
            username="examples_" + secrets.token_hex(5),
            password_hash=hash_password(secrets.token_urlsafe(48)),
        )
        db.add(owner)
        db.flush()
        manifest["owner"] = owner.username
        uploads = Path(data_dir) / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)

        def add_dataset(title, content, filename, description):
            key = secrets.token_hex(16) + ".csv"
            path = uploads / key
            files.append(path)
            path.write_text(content, encoding="utf-8")
            dataset = Dataset(
                owner_id=owner.id,
                title=title,
                description=description,
                tags="kaggle,sample,regression",
                license="CC0-1.0",
                filename=filename,
                storage_key=key,
                size=len(content.encode("utf-8")),
            )
            db.add(dataset)
            db.flush()
            manifest["datasets"].append(dataset.id)
            return dataset

        for source in sources:
            name = "Iris" if source["slug"] == "iris" else "Palmer Penguins"
            credit = f"Source: {source['url']}\n{source['credit']}\nLicense: CC0-1.0."
            train, test, columns = split_rows(source)
            train_csv = csv_text(train, columns)
            test_csv = csv_text(test, [c for c in columns if c != source["target"]])
            add_dataset(
                f"{name} — Kaggle source",
                source["content"],
                source["file"],
                f"Original downloaded CSV, including original missing values.\n{credit}",
            )
            training = add_dataset(
                f"{name} — practice training",
                train_csv,
                f"{source['slug']}-train.csv",
                "Local training split: added stable id, removed missing targets, "
                "held out every fifth eligible row.\n" + credit,
            )
            competition = Competition(
                title=f"{name} — {source['target']} prediction (practice)",
                description=(
                    f"Local practice competition using a public Kaggle dataset. Predict {source['target']}. "
                    f"Training data: {training.title} (Datasets, ID {training.id}). "
                    f"{len(train)} training rows and {len(test)} test rows. "
                    "Open Code for self-contained exploration and a baseline that writes a submission CSV. "
                    "Click Download CSV below the cell, join, and submit on Leaderboard. Lower RMSE is better. "
                    "This is not an official Kaggle competition. Source labels are public, so this is "
                    "a workflow exercise, not a blind evaluation. No prizes.\n" + credit
                ),
                category="Getting Started",
                metric="RMSE",
                prize="Practice only",
                deadline=(datetime.now(timezone.utc) + timedelta(days=365)).isoformat(),
                solution=json.dumps(
                    {row["id"]: float(row[source["target"]]) for row in test}
                ),
            )
            db.add(competition)
            db.flush()
            manifest["competitions"].append(competition.id)
            db.add(
                ChallengeDetails(
                    competition_id=competition.id,
                    owner_id=owner.id,
                    kind="competition",
                    test_csv=test_csv,
                )
            )
            for baseline in (False, True):
                notebook = Notebook(
                    owner_id=owner.id,
                    title=f"{name} — {'submission baseline' if baseline else 'explore the training data'}",
                    description="Original Arena starter code with embedded training data. "
                    "Run all cells; no Kaggle account or manual file upload needed.\n"
                    + credit,
                    code=notebook_code(source, train_csv, test_csv, baseline),
                )
                db.add(notebook)
                db.flush()
                db.add(
                    NotebookPublication(
                        notebook_id=notebook.id,
                        document=json.dumps(
                            sample_document(source, train_csv, test_csv, baseline)
                        ),
                    )
                )
                manifest["notebooks"].append(notebook.id)
                db.add(
                    CompetitionResource(
                        competition_id=competition.id,
                        kind="notebooks",
                        resource_id=notebook.id,
                    )
                )
            for title, body in [
                (
                    "Getting started and making a submission",
                    "Open the submission baseline in Code and run it. Download the generated CSV from Output. "
                    "Join this competition, then upload that CSV on Leaderboard. It must contain exactly "
                    "id,prediction and one prediction per test row. What baseline score did you get?",
                ),
                (
                    "Validation and public labels",
                    "Reserve validation rows from the training split before experimenting. Compare a global "
                    "mean with the starter's species means. The full source contains the held-out labels; "
                    "avoid using them to train. This local exercise tests the platform rather than measuring "
                    "performance on secret data. How would you design a stronger validation split?",
                ),
            ]:
                db.add(
                    CompetitionPost(
                        competition_id=competition.id,
                        owner_id=owner.id,
                        title=title,
                        body="Original Arena discussion prompt.\n"
                        + body
                        + "\n"
                        + credit,
                    )
                )
            discussion = Discussion(
                owner_id=owner.id,
                title=f"{name}: share your first experiment",
                body="Original Arena discussion prompt, not a copied Kaggle community post. "
                f"Try the local practice competition at /#competitions/{competition.id}/overview. "
                "What patterns do you see in the training data? Share your validation approach "
                "and any questions about missing values.\n" + credit,
            )
            db.add(discussion)
            db.flush()
            manifest["discussions"].append(discussion.id)
        db.add(SampleImport(key=PACK, manifest=json.dumps(manifest)))
        from .competition_metadata import backfill_metadata

        db.flush()
        backfill_metadata(db)
        return {"status": "imported", **manifest}
    except Exception:
        db.rollback()
        for path in files:
            path.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--update-notebooks",
        action="store_true",
        help="Refresh existing curator sample notebook narratives",
    )
    args = parser.parse_args()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        print(
            json.dumps(
                (
                    update_sample_notebooks(db)
                    if args.update_notebooks
                    else import_samples(db)
                ),
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
