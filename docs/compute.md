# Compute: Save & Run All, schedules, accelerators and GPU quotas

Arena runs on a disconnected cluster. **No notebook session, background run or exercise
attempt has internet access**, and the UI says so ("Internet: off"). Install nothing at
run time; use the packages in the runtime image and attached inputs.

## Save & Run All

Any notebook owner can run a saved version in the background, without a competition:

- **Save Version → Save & Run All (background)** saves a version and queues it.
- **Notebook panel → Background runs → Run saved version** queues the latest saved
  version. (`POST /api/code/{id}/runs` also accepts a `version_id`.)

A run executes the notebook from top to bottom in a fresh runtime through the same
broker as competition commits: a Kubernetes Job (`EVALUATION_RUNTIME=kubernetes`) or a
local Docker container, with no network, no service-account token, CPU/memory limits,
`EVALUATION_TIMEOUT_SECONDS` for the run and `NOTEBOOK_CELL_TIMEOUT_SECONDS` per cell.
Attached datasets, notebook outputs, competition files and practice data are copied in
after checking the owner still has access.

Statuses: queued, running, succeeded, failed, cancelled and timed out. Each run records
its accelerator, trigger (manual or schedule), start and end times and a log of cell
output and errors (terminal codes removed, truncated to 50,000 characters). On success
Arena adds the executed notebook with its outputs to the version history as
"Run *n*" and saves generated files with the same rules and limits as commits (up to 200
files and 50 MB, excluding inputs). The working copy is not changed. Owners can cancel
queued or running runs; one run per notebook can be active. A notebook with an active
run cannot be deleted.

Competition commits keep their scoring behavior. Commits, runs and attempts share the
input staging (`isolated_runner.stage_inputs`) and the broker (`runtime_jobs.run`).

## Scheduled runs

**Notebook panel → Schedule a notebook to run** creates schedules that run the latest
saved version daily or weekly at a UTC time, or every N hours (1–168). Owners can pause,
resume and delete schedules; deleting keeps run history. An administrator setting limits
schedules per user (`max_schedules_per_user`, default 5).

The evaluation worker's scheduler loop checks every `SCHEDULER_INTERVAL_SECONDS`
(default 30):

- Each schedule slot creates at most one run (`notebook_runs` is unique on
  `schedule_id, scheduled_for`), and `next_run_at` moves past the current time in the
  same transaction, so restarts never create duplicates.
- After downtime, missed slots collapse into **one** catch-up run.
- A slot is skipped if the notebook's previous run is still active.
- Three consecutive failed or timed-out runs disable the schedule. Every failure and the
  disabling notify the owner (notification kind `run`). Resuming resets the count.

## Accelerators

Users choose CPU or GPU when starting an interactive session, queuing a run, creating a
schedule and checking an exercise (exercises default to CPU). GPU options are shown as
unavailable when the site cannot run GPU work.

**Interactive sessions.** The API starts the Hub server with
`user_options = {"accelerator": "cpu" | "gpu"}`. `jupyterhub_config.py` validates the
options in `apply_user_options` (any other key or value is refused) and, per spawn:

- GPU: requests and limits `NOTEBOOK_GPU_COUNT` × `GPU_RESOURCE_NAME`, adds
  `NOTEBOOK_GPU_TOLERATIONS` (default: tolerate the `nvidia.com/gpu` NoSchedule taint)
  and merges `NOTEBOOK_GPU_NODE_SELECTOR`.
- CPU: no GPU request, and tolerations for the GPU taint are removed even if
  `NOTEBOOK_TOLERATIONS` lists one.

`NOTEBOOK_GPUS` no longer gives every session a GPU. A running server keeps its
accelerator; to switch, save and stop the session, then start it with the other choice.
Opening another notebook reuses the running server.

**Background runs and attempts** request `NOTEBOOK_GPU_COUNT` GPUs only when GPU is
selected; CPU Jobs drop GPU tolerations from `EVALUATION_TOLERATIONS`. Competition
commits and benchmark Jobs keep `EVALUATION_GPUS`.

## GPU quotas and capacity

Administrator settings (**Administration → Settings → Compute**):

| Setting | Default | Meaning |
| --- | --- | --- |
| `gpu_weekly_hours` | 30 | GPU hours per user per week, resetting Monday 00:00 UTC |
| `gpu_capacity` | 1 | GPUs Arena allocates at once; 0 disables GPU work |
| `max_schedules_per_user` | 5 | Schedules per user |

Every GPU allocation is a `gpu_usage` row:

- **Sessions** start when Arena starts the server and end when Arena stops it or the Hub
  reports it stopped. The API checks open GPU sessions against the Hub every minute and
  whenever the user's session status is polled. If a stopped server was last seen
  running more than three minutes earlier, usage is charged until that sighting.
- **Runs and attempts** are charged for their actual Job duration.
- **Commit and benchmark Jobs** that request `EVALUATION_GPUS` hold capacity but are not
  charged to a quota.

Arena refuses to start a GPU session when the user's weekly quota is used or all GPU
capacity is allocated. GPU runs, schedules and attempts are refused at queue time when
GPUs are unavailable or the quota is used; a queued GPU run waits in the worker until a
GPU is free, while CPU work behind it continues. CPU work is always available.

The usage meter (used and remaining hours, reset time, GPUs in use) is in the notebook
panel and **Account → Settings**. **Administration → Compute** lists each user's usage
this week and who holds a GPU now.

## Operating a single GPU

- **One live GPU session holds the whole card, even while idle.** Arena warns users in
  the editor and asks them to stop GPU sessions they do not use (**Run → Save and stop
  notebook server**). Closing the browser does not stop a session. Consider a Hub idle
  culler; Arena closes the usage record when the Hub reports the server stopped.
- With `EVALUATION_GPUS=1`, every competition commit and benchmark Job also needs the
  card. While one runs, GPU sessions are refused; if a GPU session already holds the
  card, the commit Job stays pending until it is released or the deadline expires. Set
  `EVALUATION_GPUS=0` if commits do not need CUDA.
- Keep `gpu_capacity` at the number of allocatable GPUs (1 for one RTX 4090).
- The evaluation worker stays a single replica: commits, benchmarks, and attempts plus
  notebook runs are three serial consumers, with the scheduler loop alongside. On
  restart it fails interrupted runs and attempts (not counted against learners) and
  closes their GPU usage.
- Allocation decisions lock the `gpu_allocation_lock` settings row (migration
  `0012_gpu_allocation_lock`), so concurrent starts cannot exceed capacity.
- In standalone API mode without the evaluation worker, runs and attempts stay queued.

## Environment variables

| Variable | Default | Used by |
| --- | --- | --- |
| `NOTEBOOK_GPU_COUNT` | `1` | GPUs per GPU session, run or attempt (API, worker, Hub) |
| `NOTEBOOK_GPU_TOLERATIONS` | tolerate `GPU_RESOURCE_NAME` NoSchedule | Hub, GPU sessions only |
| `NOTEBOOK_GPU_NODE_SELECTOR` | `{}` | Hub, GPU sessions only |
| `EXERCISE_TIMEOUT_SECONDS` | `180` | Worker, whole attempt Job |
| `EXERCISE_CELL_TIMEOUT_SECONDS` | `60` | Worker, learner code and checks |
| `SCHEDULER_INTERVAL_SECONDS` | `30` | Worker scheduler loop |
| `NOTEBOOK_SPAWNER` | `docker` | API: GPU sessions need `kubernetes` |
| `EVALUATION_RUNTIME` | `docker` | API: GPU runs and attempts need `kubernetes` |

Existing variables keep their meaning: `GPU_RESOURCE_NAME`, `EVALUATION_GPUS`
(commits and benchmarks), `EVALUATION_TOLERATIONS`, `NOTEBOOK_TOLERATIONS`,
`NOTEBOOK_NODE_SELECTOR`, `EVALUATION_TIMEOUT_SECONDS` and
`NOTEBOOK_CELL_TIMEOUT_SECONDS`.

## API

| Method and path | Purpose |
| --- | --- |
| `POST /api/notebook-session` `{"accelerator"}` | Start a session; without a body, reuse or start CPU |
| `GET /api/compute/usage` | Quota, capacity and session accelerator |
| `GET /api/admin/compute/usage` | Per-user GPU usage (admin) |
| `POST/GET /api/code/{id}/runs` | Queue a run; run history |
| `GET /api/code/{id}/runs/{runId}`, `POST …/cancel` | Run detail with log; cancel |
| `GET/POST /api/code/{id}/schedules` | List and create schedules |
| `PUT/DELETE /api/code/{id}/schedules/{scheduleId}` | Update or delete |
| `POST /api/code/{id}/schedules/{scheduleId}/pause`, `/resume` | Pause or resume |
