# Kaggle practice collection

Import the bundled collection explicitly into your local container stack:

```bash
docker compose build api
docker compose up -d --no-deps --force-recreate api
docker compose exec -T api python -m app.import_samples
```

If the web proxy retains the old API container address, recreate the web service with `docker compose up -d --no-deps --force-recreate web`.

The importer creates four datasets (two original CSVs and two training splits), two local practice competitions, four runnable notebooks, four competition discussion prompts and two global discussion topics. They appear under a dedicated `examples_<random suffix>` curator account with an unshared random password. Your account and existing content are preserved. Sign in with your own account to join, execute code, submit predictions and discuss results.

These are **local practice competitions and original Arena code/discussion prompts**, not imported official Kaggle competitions, notebooks or community posts. No Kaggle account, credentials or competition rules acceptance is required. No participants, scores or comments are fabricated.

## Sources and attribution

Downloaded directly from Kaggle's public dataset download endpoints on September 9, 2026:

| Bundled CSV         | Kaggle source                                                                                                             | Attribution                                                                                                                                                                                        | License                                                       |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| `Iris.csv`          | [Iris Species](https://www.kaggle.com/datasets/uciml/iris)                                                                | Kaggle publisher: UCI Machine Learning; classic Iris measurements associated with Fisher (1936)                                                                                                    | [CC0-1.0](https://creativecommons.org/publicdomain/zero/1.0/) |
| `penguins_size.csv` | [Palmer Archipelago penguin data](https://www.kaggle.com/datasets/parulpandey/palmer-archipelago-antarctica-penguin-data) | Kaggle publisher: Parul Pandey. Data: Kristen Gorman and Palmer Station LTER. Gorman, Williams and Fraser (2014), [doi:10.1371/journal.pone.0090081](https://doi.org/10.1371/journal.pone.0090081) | [CC0-1.0](https://creativecommons.org/publicdomain/zero/1.0/) |

Original files and their SHA-256 hashes are in `apps/api/app/sample_data/`. The importer verifies the bundled source bytes before writing anything. Source links and credits also appear in catalog descriptions, notebooks and discussion prompts. Original CSVs preserve all source rows and missing values (150 Iris rows, 344 penguin rows).

## Try the complete workflow

1. Open Competitions and select either title ending in **(practice)**.
2. Review Overview, then Data: Iris has 30 test rows; Penguins has 69. The corresponding training datasets have 120 and 273 rows.
3. Open Code, view the exploration notebook, then select **Fork code** and run your copy to inspect a table, missing values and a histogram.
4. View and fork the submission baseline notebook, then run your copy. It embeds the training and test CSVs, uses training species means, and writes `iris-submission.csv` or `penguins-submission.csv`.
5. Click **Download CSV** below the executed cell, join the competition, and upload it on Leaderboard. Your actual scored submission then appears there.
6. Post a question in Discussion and verify it survives refreshing the page.

Iris predicts `PetalLengthCm`; Penguins predicts `body_mass_g`. Both use the platform's RMSE scorer. The import adds stable row IDs, excludes rows with missing targets, then holds out every fifth eligible row. Remaining missing feature values are retained. Full source labels remain publicly available: this is a workflow exercise, not a secret test set or an official Kaggle leaderboard. The deadline is one year from initial import and the prize is “Practice only”. Models remains empty until a user shares a model.

## Persistence and reruns

Database records and the `sample_imports` receipt are persisted in the existing PostgreSQL storage. Downloadable CSVs are stored under `data/platform/uploads/` (or your configured `DATA_ROOT/platform/uploads/`). Notebook working copies and generated submission files use the existing per-user notebook storage.

Rerunning the import reports `already imported`; it does not reset deadlines, overwrite edits, duplicate entries or restore deleted samples. It never runs automatically on startup. A failed import rolls back database changes and removes the files it created. A process killed during file writing can leave unreferenced CSV files, but no completed receipt or partially committed catalog records. Back up the database and platform files together as described in [storage.md](storage.md).

Sample notebooks include Markdown introductions, dataset and column-guide tables,
notes, section headings, and suggested next experiments alongside three executable
code cells. Baselines also include a submission checklist and an RMSE equation.
These are original Arena explanations; source attribution remains in each notebook.

To upgrade already imported curator notebooks without creating duplicate samples:

```sh
docker compose exec -T api python -m app.import_samples --update-notebooks
```

The update uses the sample import receipt, checks curator ownership and unchanged
sample code, and skips deleted or modified notebooks. It updates public sample
snapshots; existing user forks and working copies are not rewritten. Fresh imports
include the narrative notebooks automatically.
