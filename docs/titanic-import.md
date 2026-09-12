# Titanic official materials

This import is a local copy for exploration, not an official Kaggle competition. **Local scoring is disabled**, as requested. No holdout split, test answers, Kaggle scores, participant accounts, or scored submission records are fabricated.

Open the imported competition at `http://localhost:8080/#competitions/4/overview`. The original tutorial is code 93 and the runnable adaptation is code 94.

## Included

- Original `train.csv` (891 rows), `test.csv` (418 rows), and `gender_submission.csv` (418 rows), downloaded using authenticated Kaggle access. The sample submission is a set of example predictions, not test labels.
- All five published competition pages: description, evaluation, data description, rules, and frequently asked questions, retrieved through Kaggle's competition pages API. Markdown/HTML is rendered through Arena's sanitized Markdown component.
- Alexis Cook's **Titanic Tutorial**, version 22 when downloaded, with original source cells and attribution. An additional explicitly labeled adaptation writes the original CSV bytes as text to `input/titanic` and changes the source's Kaggle paths to local paths so users can fork and run it in Arena.
- The tutorial's published `submission.csv` and execution log, shown as archived output/log cells. They are not claimed to have been executed or scored in Arena.

Sources: [competition](https://www.kaggle.com/competitions/titanic), [rules](https://www.kaggle.com/competitions/titanic/rules), [tutorial and Apache 2.0 license notice](https://www.kaggle.com/code/alexisbcook/titanic-tutorial/notebook). Original competition data remains subject to Kaggle's source terms; it is not relabeled CC0.

Private test answers and other participants' private submissions are unavailable. The supplied account's submission-history request was rejected by Kaggle. Community notebooks are not exhaustively mirrored; the imported source notebook is the official introductory tutorial. Joining in Arena does not join Kaggle or accept its rules there.

## Storage and reimport

The download archive is `data/imports/titanic/`. A durable runtime copy is placed at `data/platform/imports/titanic/` and mounted as `/data/imports/titanic` in the API container. Ensure the non-secret archive files are readable by the API container user (UID 10001). Catalog CSVs also live under the existing platform uploads directory. Competition pages, immutable file snapshots, publications, provenance and an import receipt live in PostgreSQL.

```bash
# Requires Python 3.11+ and the current kaggle package in a separate environment.
# Configure credentials locally; never commit or paste the token into this command.
python scripts/download_titanic_materials.py

# After copying the archive into the mounted platform imports directory:
docker compose exec -T api python -m app.import_titanic --source /data/imports/titanic
```

The importer checks file hashes, creates a dedicated non-login curator, and commits database records together. A failure rolls back records and removes newly created upload files. A completed receipt makes reruns a no-op, preserving edits and avoiding duplicates. Nothing imports automatically at startup.

`CompetitionSource` stores source links and original pages. Competitions with an empty solution expose `evaluation_available: false`; both direct submission and notebook-commit endpoints return 409 before starting evaluation. Other competitions retain their scoring behavior. The original sample endpoint returns the original `PassengerId,Survived` template.

## Validation

The API suite passed 112 tests before the final provenance cleanup change; the subsequent targeted import and Your Work suite passed 9 tests. All 16 browser workflows passed across the full run and one navigation-timeout retry. The live Titanic test verified original downloads, rendered rules, input references, archived outputs, disabled evaluation and actual CPU execution of an adapted tutorial fork.
