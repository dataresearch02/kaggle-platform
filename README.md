# Arena

A Kaggle-inspired AI learning and experimentation platform. This repository contains a working first milestone, not full Kaggle parity. All UI data comes from the API and is persisted; starter content is seeded on first startup.

## Run with containers

Requires Docker Engine with Compose v2 (or compatible Podman Compose).

```bash
python scripts/configure_notebooks.py
python scripts/storage.py plan
# New installation only (for existing volumes, use migrate instead):
python scripts/storage.py init
python scripts/containers.py up --build
```

Open **http://localhost:8080** and create an account. API documentation is available at **http://localhost:8080/api/docs**.

## Your work

After you save a notebook, upload a dataset, or publish a model or challenge, **Your work** appears last in the sidebar, separated from the other items by a divider. Learn and Discussions are grouped under **More**. Datasets, Models, Codes, Competitions and Benchmarks also link to the corresponding category in your personal workspace. Search and filter your content, open it, edit its title and description, or download datasets and published code notebooks. Ownership is checked on the server. Temporary unsaved notebooks and other users' examples are excluded. This view uses existing persistent records; it does not duplicate your data. Use the trash button to delete an owned item after reviewing the confirmation. Dataset uploads are removed; notebook files are queued for cleanup when the runtime is ready. Challenge deletion also removes its entries and submissions. Copies already downloaded or attached to other workspaces remain. Bulk actions are not implemented.

## Integrated notebooks

Arena has its own notebook editor: Python cells with syntax highlighting, Markdown previews, streamed text/errors, tables and plots. Use **Create → Notebook** for a full-screen temporary draft, or select a saved notebook and choose **Start session**. The workspace includes menus, floating cell controls, a right input/outline panel and a shared Python console. The toolbar includes Run cell, Run all, Interrupt, Restart kernel and Save. Add Input inserts a dataset loader; Upload saves a private CSV dataset and attaches it. There is no JupyterLab iframe, file browser, terminal or Open command.

JupyterHub runs behind the API to provision a separate scientific Python container per user. The browser only calls notebook-scoped Arena endpoints; direct `/jupyter/` URLs return 404. Python code runs in notebook containers, never in the web API. HTML outputs are sanitized and Markdown does not execute embedded HTML or scripts.

Explicit Save preserves the full notebook document and outputs. Opening a published template creates a private working copy on first use. Saved notebooks can be downloaded through the notebook-scoped export endpoint. Existing saved notebooks and temporary save/discard semantics remain compatible. Interactive widget JavaScript and `input()` prompts are not supported; each cell execution has a two-minute limit and a 10 MB output limit. There is no notebook file uploader; published datasets can be consumed through their download URLs from Python.

The Hub requires a Docker-compatible API socket to launch containers. Docker Engine's default is `/var/run/docker.sock`. For Podman, start its API service and set `DOCKER_SOCKET_PATH` in `.env` to that socket's host path. See [the notebook integration guide](docs/notebooks.md) for setup and troubleshooting.

```bash
docker compose logs -f api web
python scripts/containers.py down
```

All container application data lives under `data/` in this checkout through bind mounts. Existing installations must run `python scripts/storage.py migrate` once before starting the updated stack; this stops Arena, copies and verifies existing volumes, and retains the originals. See [persistent storage, migration and backups](docs/storage.md). This setup targets local container testing; OpenShift deployment is deferred.

## Local development

Use Python 3.12 (the container version; Python 3.9 is also supported for local checks) and Node 22.12+.

```bash
python -m venv .venv
.venv/bin/python -m pip install -r apps/api/requirements.txt
cd apps/api
../../.venv/bin/uvicorn app.main:app --reload --port 8000
```

In another terminal, from the repository root:

```bash
cd apps/web
npm ci
npm run dev
```

Open **http://localhost:5173**. Vite proxies `/api` to FastAPI. This standalone API mode has no notebook runtime unless Hub connection settings are configured. To develop the frontend against the running Compose API and JupyterHub, run `ARENA_API_PROXY=http://127.0.0.1:8080 npm run dev` instead; this keeps Arena and Hub on the same account database. Local development uses SQLite in `data/development`; Docker uses PostgreSQL. Do not put an existing SQLite URL in the container configuration.

## Create community content

Open the **Create** dropdown in the sidebar to choose **Notebook**, **Competition**, **Dataset**, or **Benchmark**. Each section also has its own creation button. **Notebook** opens the full-screen Arena editor immediately with a temporary draft. Name it and click **Save** (or press Ctrl/Cmd+S) to create a permanent notebook with its saved outputs. Closing without Save discards the draft. Other creation options slide in from the right over the selected collection. The panel occupies the right half of the desktop viewport and the full width on smaller screens, with file uploads and metadata fields. Drag a CSV onto the upload area or browse for a file, review its name and size, then publish. Sign in before publishing.

Competitions require a future closing date; benchmarks stay open. Both accept a public UTF-8 test CSV (up to 10 MB, unique `id` plus feature columns) and a private answer CSV (up to 1 MB, exactly `id,prediction`, matching IDs). Participants download test data and a sample submission, join, then upload predictions for automatic scoring and a leaderboard. Choose RMSE, MAE, Accuracy or binary LogLoss; only Accuracy ranks higher scores first. Include the task instructions and training-data links in the description. Evaluation data is fixed after publication. This benchmark feature evaluates prediction CSVs; hardware timing and automatic model execution are not included.

Creator metadata, test data, answers and scores persist in PostgreSQL. A new `challenge_details` table extends existing competition records without rewriting them; the seeded competition continues to work.

## First end-to-end experiment

1. Register an account. Usernames use letters, numbers, and underscores; passwords need at least 10 characters.
2. Open **More → Learn → Python foundations**, read a lesson, and mark it complete.
3. Download **Datasets → City bikes & daily demand**.
4. Open **Competitions → Predict bike demand**, join, and download test data and the sample submission.
5. Create a notebook, or open a saved notebook and click **Start session**. Use Python to load a dataset download URL, then train a baseline in the Arena editor. The Intro to machine learning course includes example code.
6. Open the competition’s **Submissions** tab and upload a UTF-8 CSV with exactly `id,prediction` columns and IDs 7, 8, and 9. Arena calculates RMSE and updates the leaderboard with your best score.
7. Share an approach in Discussions or publish a model reference card.

## Project structure

```text
apps/
  api/
    app/
      main.py          REST API, authorization, upload and workflow handlers
      auth.py          Password hashing and persistent cookie sessions
      db.py            SQLite / PostgreSQL connection and storage configuration
      models.py        Relational data model
      schemas.py       Request validation
      scoring.py       Strict prediction validation and metric calculation
      notebook_runtime.py  Hub lifecycle, first-open import and private export
      seed.py          Synthetic starter datasets, challenge, courses and notebook
    tests/             API workflow, access control and scoring tests
    Dockerfile
    requirements.txt
  web/
    src/
      App.tsx          Responsive workspace and connected feature flows
      api.ts           Typed API client
      styles.css       Visual design and responsive layouts
      NotebookWorkspace.tsx  Native notebook cells, safe outputs and kernel controls
    Dockerfile
    nginx.conf         Same-origin web/API reverse proxy
infra/
  jupyterhub/           Official Hub image, Arena authenticator, DockerSpawner
  singleuser/           Scientific Python runtime image
scripts/
  containers.py           Docker/Podman startup, health checks and shutdown
  configure_notebooks.py  Local service-secret and absolute storage-path setup
  storage.py              Storage initialization, migration and offline backups
  check_storage.py        Container startup storage validation
data/                     Ignored persistent runtime data (see docs/storage.md)
compose.yaml           PostgreSQL, API, frontend, JupyterHub and notebook image
.env.example           Local container settings
Makefile               Common commands
docs/
  architecture.md      Boundaries, data flows and deployment assumptions
  roadmap.md           Feature coverage and remaining milestones
```

## Checks

```bash
make test
make build
docker compose config --quiet
```

Browser workflow checks (automatically starts the API and Vite on ports 8000 and 5173):

```bash
cd apps/web
npx playwright install chromium
npm run test:e2e
```

Browser tests use a separate SQLite database under `.data/e2e` and cover a desktop learning/submission workflow plus mobile navigation. Screenshots are written to `apps/web/test-results`.

The API also exposes `/api/health`. POST/PUT requests require `X-Arena-Client: web`. Browser mutations are restricted to `ALLOWED_ORIGINS`, with same-site HTTP-only session cookies. Interactive API docs are read-only unless you add that custom header through a client. To explore authenticated mutations, use the UI or curl with a cookie jar and the header.

## Current boundaries

- New datasets and notebooks are private by default, with explicit visibility and sharing controls. Notebook history stores immutable saves and supports restoration into the editor. Catalog search returns at most 100 entries.
- Competitions support RMSE, MAE, Accuracy and binary LogLoss, team-owned submissions and a public leaderboard. Private leaderboards, submission limits, final selection and anti-cheating controls remain incomplete.
- Interactive notebooks use the native Arena editor and per-user Jupyter containers. Compose evaluates competition commits through a separate CPU worker with disposable offline containers, cancellation, resource limits and restart recovery. GPU support is deferred.
- Dataset and model details support immutable additional file versions and downloads (10 MB per file). Model cards can contain hosted files and optional external links. Pinned notebook inputs, large artifact storage and hosted inference remain incomplete.
- Courses contain lessons and per-user completion tracking; exercises are not automatically graded.
- Accounts, public discussions and replies are implemented. Email verification, password recovery, OAuth, roles, moderation, quotas, and rate limiting remain future work.
- Schema creation and starter seeding run at startup for the first milestone. Use one API process; schema migrations and coordinated bootstrap are required before scaling.
- The container runtime is intended for a trusted local community. The native editor sanitizes outputs and blocks direct Jupyter UI access; runtime network isolation and resource quotas still need hardening before accepting hostile workloads. The Hub and the trusted evaluation broker mount the container-runtime socket; the API and evaluation job containers do not. Compose binds published ports to loopback. Public deployment needs HTTPS, secure cookies (`COOKIE_SECURE=true`), explicit origins, managed secrets, migrations, backups, upload policy, abuse controls, and isolated compute.

See [architecture](docs/architecture.md) and the [feature roadmap](docs/roadmap.md) for the planned system.

## Code formatting

Prettier formats the frontend, JSON, YAML, and Markdown. Black formats Python. Shared editor settings are in `.editorconfig`.

Install the development formatters from the repository root:

```bash
npm ci
.venv/bin/python -m pip install -r apps/api/requirements-dev.txt
```

Run `make format` to format the project, or `make format-check` to verify formatting without changing files. Generated files, dependencies, lockfiles, and local environment files are excluded from Prettier.

## Competition pages

Competition cards open full pages at `#competitions/<id>/overview`. Overview, Data, Code, Models, Discussion, Leaderboard, Rules, Team and Submissions have shareable tab URLs and support browser back/forward navigation. The header provides Join competition and shows membership or closed status. Data previews public features only and offers test/sample CSV downloads. Leaderboard displays participants’ best scores. Submissions contains prediction uploads and the signed-in user's latest 100 scored submissions, including timestamps. Team supports creating a team, joining by invite code, listing members and leaving. Team membership and submission attribution persist in PostgreSQL. Team scores aggregate on the leaderboard. Membership changes lock after submissions or pending evaluations, and close at the competition deadline.

Creators can link their published Codes and model cards to a competition. These tabs show linked resources, not unrelated community content. Discussion posts are stored per competition. Rules describe the current enforced submission format, size, deadline and scoring behavior; organizer-specific rule editing is not implemented. Competition deletion removes its resource links and discussion posts while retaining the independently published notebooks and model cards.

### Optional Kaggle practice content

See [the sample collection guide](docs/sample-data.md) to import public Iris and Palmer Penguins CSVs, local practice competitions, runnable starter codes and discussion prompts. The import is explicit and repeatable; it preserves existing user content and stores the samples in your configured persistent storage.

### Competition overview and data catalog

Competitions now have editable overview metadata, documented CSV snapshots, and a folder-based data explorer unlocked after joining. Organizers manage dates, prizes, instructions, training/reference files and column descriptions. Dataset owners can edit documentation and attribution. See [the database structure and migration guide](docs/competition-metadata.md).

### Code discovery and publications

Competition code and Data Hub Codes use scroll-loaded lists with personal work, sharing and bookmark filters. Notebooks open on a read-only page; users fork into their own editor, and authors explicitly publish code and outputs. See [the code library guide](docs/code-library.md).

### Sidebar and active events

The sidebar toggle shares a row with Arena home. Compact mode hides the brand
and initially closes Data Hub and More; their icons toggle the nested navigation.
Selected rows fill the sidebar width with a right border. Your work is the final
content item. View Active Events stays at the bottom and opens a dialog with
queued/running notebook competition evaluations, refreshed every five seconds.
The main sidebar's empty-state actions start notebook or benchmark creation.
The event list is private to the signed-in user; synchronous uploads and future
scheduling features are not represented as background jobs.

See the [main workflow review](docs/logic-review.md) for verified behavior, fixes found during the review, and remaining functional limits.

See [local CPU execution and persistent work](docs/local-cpu.md) for the new privacy, history, artifact storage and evaluation behavior, including current limits.

### Account management

Use the avatar in the header to open the account drawer. Profile/photo editing,
groups, expiring CLI API tokens, visibility/password settings, logout and persistent
service notifications are implemented. See [the account guide](docs/accounts.md)
for routes, permissions and operator notification commands.
