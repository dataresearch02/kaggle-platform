"""Explicit import of downloaded Titanic materials. Never creates evaluation answers."""

import argparse
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import secrets

from .auth import hash_password
from .competition_metadata import add_file, profile_csv
from .db import Base, DATA_DIR, SessionLocal, engine
from .models import (
    ChallengeDetails,
    Competition,
    CompetitionOverview,
    CompetitionResource,
    CompetitionSource,
    Dataset,
    DatasetAccess,
    DatasetProfile,
    Notebook,
    NotebookPublication,
    SampleImport,
    User,
)

PACK = "titanic-official-v1"
SOURCE = "https://www.kaggle.com/competitions/titanic"
TUTORIAL = "https://www.kaggle.com/code/alexisbcook/titanic-tutorial"
DESCRIPTIONS = {
    "PassengerId": "Passenger identifier.",
    "Survived": "Survival label: 0 = died, 1 = survived.",
    "Pclass": "Ticket class: 1, 2 or 3.",
    "Name": "Passenger name.",
    "Sex": "Recorded sex.",
    "Age": "Age in years; some values are missing.",
    "SibSp": "Siblings and spouses aboard.",
    "Parch": "Parents and children aboard.",
    "Ticket": "Ticket identifier.",
    "Fare": "Passenger fare.",
    "Cabin": "Cabin identifier; some values are missing.",
    "Embarked": "Embarkation port: C, Q or S.",
}


def load_bundle(root):
    manifest = json.loads((root / "source/manifest.json").read_text())
    contents = {}
    for name, count in [
        ("train.csv", 891),
        ("test.csv", 418),
        ("gender_submission.csv", 418),
    ]:
        raw = (root / "source" / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest["files"][name]["sha256"]:
            raise ValueError(f"Source checksum mismatch: {name}")
        text = raw.decode("utf-8-sig")
        if profile_csv(text)["row_count"] != count:
            raise ValueError(f"Unexpected row count: {name}")
        contents[name] = (raw, text)
    tutorial = json.loads((root / "tutorial.json").read_text())
    if tutorial["metadata"]["ref"] != "alexisbcook/titanic-tutorial":
        raise ValueError("Unexpected tutorial source")
    document = json.loads(tutorial["blob"]["source"])
    from .notebook_editor import Document

    Document(**copy.deepcopy(document))
    return manifest, contents, tutorial, document


def import_titanic(db, root, data_dir=DATA_DIR):
    receipt = db.get(SampleImport, PACK)
    if receipt:
        return {"status": "already imported", **json.loads(receipt.manifest)}
    root = Path(root)
    source_manifest, contents, tutorial, original = load_bundle(root)
    pages = {
        page["name"].lower(): page["content"]
        for page in json.loads((root / "pages.json").read_text())["pages"]
    }
    details = json.loads((root / "competition.json").read_text())
    if not all(
        pages.get(name)
        for name in ("description", "evaluation", "rules", "data-description")
    ):
        raise ValueError("Missing official competition pages")
    created_files = []
    try:
        owner = User(
            username="titanic_import_" + secrets.token_hex(4),
            password_hash=hash_password(secrets.token_urlsafe(48)),
        )
        db.add(owner)
        db.flush()
        competition = Competition(
            title="Titanic - Machine Learning from Disaster",
            description="Official Kaggle Titanic materials imported for local exploration. Predict passenger survival from recorded passenger attributes. This Arena copy is not hosted by Kaggle. Local scoring is deferred: private evaluation answers are not included. Original competition: "
            + SOURCE,
            category="Getting Started",
            metric="Accuracy",
            prize="Learning; no local prizes",
            deadline="9999-12-31T00:00:00+00:00",
            solution="{}",
        )
        db.add(competition)
        db.flush()
        db.add(
            ChallengeDetails(
                competition_id=competition.id,
                owner_id=owner.id,
                kind="competition",
                test_csv=contents["test.csv"][1],
            )
        )
        db.add(
            CompetitionSource(
                competition_id=competition.id,
                source_url=SOURCE,
                rules_url=SOURCE + "/rules",
                ongoing=1,
                rules_content=pages["rules"],
                pages_json=json.dumps(pages),
            )
        )
        db.add(
            CompetitionOverview(
                competition_id=competition.id,
                starts_at=details.get("enabledDate"),
                prize_details="An introductory learning competition. No prizes are offered by this Arena import.",
                getting_started="Join this Arena competition to preview the original files. Explore train.csv, validate models on training data, then predict survival for test.csv. The original submission columns are PassengerId,Survived. Open Code for the attributed Kaggle tutorial and an explicitly adapted Arena copy. Submit to Kaggle yourself if you want an official score.",
                evaluation="Kaggle uses classification accuracy. Its private answers were not downloaded. Arena evaluation, scored submissions and scored code commits are disabled for this import. gender_submission.csv contains example predictions, never authoritative labels.",
                data_description="Original files retain their columns and rows: train.csv has 891 labeled passengers; test.csv has 418 passengers without survival labels; gender_submission.csv demonstrates the 418-row prediction format. No training/test resplit or synthetic answers were created. Source: "
                + SOURCE
                + "/data",
            )
        )
        overview = next(row for row in db.new if isinstance(row, CompetitionOverview))
        overview.getting_started += (
            "\n\n## Official Kaggle overview\n\n" + pages["description"]
        )
        overview.evaluation += (
            "\n\n## Original evaluation instructions (Kaggle only)\n\n"
            + pages["evaluation"]
        )
        overview.data_description += "\n\n" + pages["data-description"]
        datasets = []
        uploads = Path(data_dir) / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        for name, (raw, text) in contents.items():
            key = secrets.token_hex(16) + ".csv"
            path = uploads / key
            created_files.append(path)
            path.write_bytes(raw)
            dataset = Dataset(
                owner_id=owner.id,
                title="Titanic — " + name,
                description="Original Kaggle competition file. " + SOURCE + "/data",
                tags="titanic,kaggle,classification",
                license="Kaggle Titanic competition terms",
                filename=name,
                storage_key=key,
                size=len(raw),
            )
            db.add(dataset)
            db.flush()
            datasets.append(dataset)
            db.add(DatasetAccess(dataset_id=dataset.id, visibility="public"))
            values = profile_csv(text)
            columns = json.loads(values["columns_json"])
            for column in columns:
                column["description"] = DESCRIPTIONS.get(column["name"], "")
            values["columns_json"] = json.dumps(columns)
            values["sha256"] = hashlib.sha256(raw).hexdigest()
            db.add(
                DatasetProfile(
                    dataset_id=dataset.id,
                    source_url=SOURCE + "/data",
                    citation="Will Cukierski. Titanic - Machine Learning from Disaster. Kaggle, 2012.",
                    documentation="Original downloaded bytes. Dataset use remains subject to the source competition terms.",
                    **values,
                )
            )
            role = {
                "train.csv": "train",
                "test.csv": "test",
                "gender_submission.csv": "submission",
            }[name]
            row = add_file(
                db,
                competition.id,
                name,
                role,
                text,
                source_dataset_id=dataset.id,
                source_url=SOURCE + "/data",
                license=dataset.license,
                description="Original Kaggle file. "
                + (
                    "Example predictions, not ground truth."
                    if role == "submission"
                    else "See the column dictionary."
                ),
            )
            row.columns_json = values["columns_json"]
        notebook_ids = []
        for adapted in (False, True):
            document = copy.deepcopy(original)
            credit = f"# Titanic Tutorial — {'Arena adaptation' if adapted else 'original source'}\n\nAuthor: Alexis Cook. Source: {TUTORIAL}. Version {tutorial['metadata']['currentVersionNumber']}. License: [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0).\n\n"
            credit += (
                "Modified for Arena: a setup cell writes the original CSV inputs to a relative folder, and code paths use that folder. No local score is computed."
                if adapted
                else "Source cells are preserved. Original /kaggle/input paths require Kaggle; use the Arena adaptation for local execution."
            )
            cells = [{"cell_type": "markdown", "metadata": {}, "source": credit}]
            if adapted:
                setup = "from pathlib import Path\n_titanic_input = Path('input/titanic')\n_titanic_input.mkdir(parents=True, exist_ok=True)\n"
                for name, (_, text) in contents.items():
                    setup += f"(_titanic_input / {name!r}).write_text({text!r}, encoding='utf-8')\n"
                setup += "print('Original Titanic input files are ready.')"
                cells.append(
                    {
                        "cell_type": "code",
                        "metadata": {},
                        "source": setup,
                        "outputs": [],
                        "execution_count": None,
                    }
                )
                for cell in document["cells"]:
                    if cell["cell_type"] == "code":
                        cell["source"] = "".join(cell["source"]).replace(
                            "/kaggle/input", "input"
                        )
            document["cells"] = cells + document["cells"]
            document["metadata"]["arena_inputs"] = [
                {"id": d.id, "title": d.title, "filename": d.filename} for d in datasets
            ]
            output = root / "outputs/submission.csv"
            if output.is_file():
                document["cells"].extend(
                    [
                        {
                            "cell_type": "markdown",
                            "metadata": {},
                            "source": "## Published Kaggle output\n\nThe CSV below was downloaded from the original tutorial's published output. It was not generated or scored by Arena.",
                        },
                        {
                            "cell_type": "code",
                            "metadata": {},
                            "source": "# Archived output from the source tutorial; rerun the tutorial to produce a new file.",
                            "execution_count": None,
                            "outputs": [
                                {
                                    "output_type": "display_data",
                                    "metadata": {},
                                    "data": {
                                        "text/csv": output.read_text(),
                                        "text/plain": "Downloaded tutorial artifact: submission.csv (not locally scored)",
                                    },
                                }
                            ],
                        },
                    ]
                )
            log = root / "outputs/titanic-tutorial.log"
            if log.is_file():
                lines = json.loads(log.read_text())
                document["cells"].extend(
                    [
                        {
                            "cell_type": "markdown",
                            "metadata": {},
                            "source": "## Archived Kaggle execution log\n\nThis is the source tutorial's log, including its original warnings; it is not an Arena execution.",
                        },
                        {
                            "cell_type": "code",
                            "metadata": {},
                            "source": "# Archived Kaggle log",
                            "execution_count": None,
                            "outputs": [
                                {
                                    "output_type": "stream",
                                    "name": (
                                        "stderr"
                                        if line.get("stream_name") == "stderr"
                                        else "stdout"
                                    ),
                                    "text": str(line.get("data", "")),
                                }
                                for line in lines
                            ],
                        },
                    ]
                )
            from .notebook_editor import Document

            document = Document(**document).model_dump()
            notebook = Notebook(
                owner_id=owner.id,
                title="Titanic Tutorial — "
                + ("Arena adaptation" if adapted else "Alexis Cook (original)"),
                description=credit,
                code="\n\n".join(
                    "".join(c["source"])
                    for c in document["cells"]
                    if c["cell_type"] == "code"
                ),
            )
            db.add(notebook)
            db.flush()
            notebook_ids.append(notebook.id)
            db.add(
                NotebookPublication(
                    notebook_id=notebook.id, document=json.dumps(document)
                )
            )
            db.add(
                CompetitionResource(
                    competition_id=competition.id,
                    kind="notebooks",
                    resource_id=notebook.id,
                )
            )
        result = {
            "competition": competition.id,
            "datasets": [d.id for d in datasets],
            "notebooks": notebook_ids,
            "source_files": source_manifest["files"],
            "local_scoring": False,
            "scored_submissions": 0,
            "tutorial_output_imported": (root / "outputs/submission.csv").is_file(),
        }
        db.add(SampleImport(key=PACK, manifest=json.dumps(result)))
        db.commit()
        return {"status": "imported", **result}
    except Exception:
        db.rollback()
        for path in created_files:
            path.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        print(json.dumps(import_titanic(db, args.source), indent=2))


if __name__ == "__main__":
    main()
