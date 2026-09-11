# Local CPU execution and persistent work

GPU configuration and OpenShift deployment are deferred at the user's request.
The Compose deployment runs CPU workloads only.

## Saving, publishing and sharing

New notebooks and uploaded datasets are private by default. Existing sample and
legacy public content stays public. Saving a notebook creates a durable working
copy; publication is a separate action. Competition code becomes public only
after Save & Commit finishes execution and scoring successfully.

Notebook owners can share read access with registered users, revoke it, and make
a published notebook private. Recipients cannot edit the owner's notebook.
Version history in the editor lists immutable saved snapshots; restoring a
version changes the editor buffer and requires Save to persist the restoration.
Restoring does not replace an evaluated competition publication.

Dataset owners manage visibility and read access in dataset details. Public
notebooks must reference public datasets. Revoking access prevents future reads;
it cannot recall files another user has already copied or downloaded.

Dataset details and model cards accept additional files with relative paths.
Uploading the same path creates another immutable version. Every version has a
SHA-256 checksum and its own download URL. Files are limited to 10 MB each for
local testing. Model cards are public and may omit an external reference URL.
Additional dataset files do not replace the original CSV or automatically become
notebook inputs; the current Add Input workflow still copies that CSV.

## Competition evaluation

Organizers can choose RMSE, MAE, Accuracy or binary LogLoss. Accuracy uses higher
scores as better; the other metrics use lower scores. Predictions must match all
test IDs, contain finite numeric values, and satisfy the metric's domain.

Submissions made while in a team retain that team's attribution. The leaderboard
shows the team's best score and team members can see its submission history.
Choose a team before submitting: a user or team with submissions cannot change
membership, and a user with pending evaluation cannot change teams. A new member
without submissions can join an existing team. Team merging is not implemented.

Compose runs `evaluation-worker` as a single durable queue consumer. The API
queues a saved notebook snapshot in PostgreSQL. The worker launches a fresh
scientific container for each commit, copies public test features and authorized
CSV inputs into its job directory, executes the notebook, then validates and
scores predictions against answers held in the database. The job container has:

- Two CPUs, 2 GB memory and 256 processes/threads maximum.
- No network, database credentials, Docker socket or user workspace.
- A read-only root filesystem and a 256 MB temporary filesystem.
- A writable directory containing only that job's files.
- A 120-second cell timeout and a 15-minute total execution timeout.

The owner can cancel queued or running evaluations. Cancelled jobs do not publish.
The worker removes job containers after completion, failure or cancellation. On
restart it removes orphaned evaluation containers and marks interrupted jobs
failed for explicit retry; queued jobs remain queued. Run only one evaluation
worker for this local configuration.

The trusted worker broker needs the Docker/Podman socket and database access.
Those credentials are never passed to job containers. JupyterHub independently
continues to provision interactive user containers. The API has no runtime socket.

## Persistence and remaining limits

Alongside the existing PostgreSQL and user-workspace bind mounts:

- `data/platform/artifacts/` stores uploaded file versions under random keys.
- `data/platform/evaluations/` stores each evaluation's source, inputs and results.
- Notebook history, visibility, sharing, artifact metadata and team submission
  ownership live in PostgreSQL.

These paths are relative to `DATA_ROOT` when using another storage root. Include
them in backups. Deleting a dataset or model queues persistent cleanup for all its
artifact versions. Evaluation directories are retained; automatic retention and
per-user disk quotas are not implemented. Memory limits do not limit job-directory
disk usage.

This increment is not full Kaggle parity. Private leaderboards, submission limits
and final selection, pinned dataset inputs, team resource sharing, GPU scheduling,
account recovery/moderation and other work remain in [the completion plan](completion-plan.md).

## Validation for this increment

- 104 API tests passed, including private access, notebook history, immutable file
  downloads, team attribution, metric validation and cancellation.
- 13 browser workflows passed across the main suite and the new artifact upload test.
- Eight live container workflows passed across the final runs, including notebook
  publication/forking, history restoration, competition creation and evaluation,
  drafts, interactive execution, sample notebooks and CPU isolation/cancellation.
- The CPU isolation test executed assertions inside a real job container: only
  the loopback network interface was present, and database credentials and the
  Docker socket were absent. It then produced predictions and received a score.
- Production frontend builds and formatting checks passed. The existing bundle
  size warning remains.

The nginx proxy periodically resolves the API service through the container
runtime's DNS resolver, allowing recovery after API container replacement.
