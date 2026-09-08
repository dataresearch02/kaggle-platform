# Arena

A Kaggle-inspired AI learning and experimentation platform. This repository contains a working first milestone, not full Kaggle parity. All UI data comes from the API and is persisted; starter content is seeded on first startup.

## Run with containers

Requires Docker Engine with Compose v2 (or compatible Podman Compose).

```bash
python scripts/configure_notebooks.py
docker compose up --build -d
```

Open **http://localhost:8080** and create an account. API documentation is available at **http://localhost:8080/api/docs**.

## Integrated notebooks

JupyterHub now starts a separate scientific Python container for each Arena user. Open **Notebooks → a notebook → Open in JupyterLab** to run cells in the full-screen Notebook Studio. Its toolbar includes run, save, interrupt/restart, code/Markdown insertion, files, outline, themes, and focus/full-IDE views. Your existing Arena session signs you in automatically; there is no second password or token to paste.

Each user has a persistent workspace. Opening a published template creates a private `.ipynb` working copy on its first launch. JupyterLab saves cells and outputs there; reopening resumes that copy. **Download working copy** exports the saved cells and outputs. **Stop server** shuts down all kernels for your user but retains files. Closing the dialog does not stop your server. Community template edits do not overwrite private working copies.

Use the JupyterLab file browser to upload datasets, and Shift+Enter to run a cell. The Hub and single-user images use the same JupyterHub version. The first build downloads the scientific Python image and can take several minutes.

The Hub requires a Docker-compatible API socket to launch containers. Docker Engine's default is `/var/run/docker.sock`. For Podman, start its API service and set `DOCKER_SOCKET_PATH` in `.env` to that socket's host path. See [the notebook integration guide](docs/notebooks.md) for setup and troubleshooting.

```bash
docker compose logs -f api web
docker compose down
```

Named volumes preserve the database, uploaded datasets, Hub state, and per-user Jupyter work directories across restarts. Do not use `down -v` unless you intend to erase these volumes.

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

Open **http://localhost:5173**. Vite proxies `/api` to FastAPI. This standalone API mode has no notebook runtime unless Hub connection settings are configured. To develop the frontend against the running Compose API and JupyterHub, run `ARENA_API_PROXY=http://127.0.0.1:8080 npm run dev` instead; this keeps Arena and Hub on the same account database. Local development uses SQLite in `apps/api/.data`; Docker uses PostgreSQL. Do not put an existing SQLite URL in the container configuration.

## First end-to-end experiment

1. Register an account. Usernames use letters, numbers, and underscores; passwords need at least 10 characters.
2. Open **Learn → Python foundations**, read a lesson, and mark it complete.
3. Download **Datasets → City bikes & daily demand**.
4. Open **Competitions → Predict bike demand**, join, and download test data and the sample submission.
5. Create or open a notebook and click **Open in JupyterLab**. Upload the downloaded CSVs in its file browser, then train a baseline directly in the embedded editor. The Intro to machine learning course includes example code.
6. Upload a UTF-8 CSV with exactly `id,prediction` columns and IDs 7, 8, and 9. Arena calculates RMSE and updates the leaderboard with your best score.
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
      scoring.py       Strict prediction validation and RMSE calculation
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
      NotebookWorkspace.tsx  Embedded JupyterLab with start/poll/retry/stop
    Dockerfile
    nginx.conf         Same-origin web/API reverse proxy
infra/
  jupyterhub/           Official Hub image, Arena authenticator, DockerSpawner
  singleuser/           Scientific notebook image and iframe configuration
scripts/
  configure_notebooks.py  Local service-secret setup
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

- CSV uploads are public, limited to 10 MB, and stored on a local persistent volume. Search returns at most 100 entries.
- The seeded educational competition uses synchronous RMSE scoring and a single public leaderboard. It is not a prize competition engine; hosted challenge creation, private leaderboards, teams, and anti-cheating controls are planned.
- Notebooks now run in embedded JupyterLab through JupyterHub, with per-user containers, persistent working copies, start/stop controls and output export. Code executes in notebook containers, never in the API. GPU execution, job queues, collaboration and automatic dataset mounting remain future work.
- Model cards contain metadata and external reference links. Artifact hosting, training job orchestration, GPU scheduling, and inference are not implemented yet. Interactive CPU experiments run in JupyterLab.
- Courses contain lessons and per-user completion tracking; exercises are not automatically graded.
- Accounts, public discussions and replies are implemented. Email verification, password recovery, OAuth, roles, moderation, quotas, and rate limiting remain future work.
- Schema creation and starter seeding run at startup for the first milestone. Use one API process; schema migrations and coordinated bootstrap are required before scaling.
- The same-origin iframe deployment is intended for a trusted local community. Notebook-rendered JavaScript shares the Arena origin; use separate per-user domains and appropriate network isolation before accepting hostile workloads. The Hub alone mounts the container-runtime socket. Compose binds published ports to loopback. Public deployment needs HTTPS, secure cookies (`COOKIE_SECURE=true`), explicit origins, managed secrets, migrations, backups, upload policy, abuse controls, and isolated compute.

See [architecture](docs/architecture.md) and the [feature roadmap](docs/roadmap.md) for the planned system.

## Code formatting

Prettier formats the frontend, JSON, YAML, and Markdown. Black formats Python. Shared editor settings are in `.editorconfig`.

Install the development formatters from the repository root:

```bash
npm ci
.venv/bin/python -m pip install -r apps/api/requirements-dev.txt
```

Run `make format` to format the project, or `make format-check` to verify formatting without changing files. Generated files, dependencies, lockfiles, and local environment files are excluded from Prettier.
