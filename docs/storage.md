# Local persistent storage

The local container stack stores application data in this checkout's `data/` directory. `scripts/configure_notebooks.py` writes its absolute path to `DATA_ROOT` in ignored `.env`. Bind mounts use that path on the container daemon's host; run these commands on the machine hosting Docker/Podman. OpenShift deployment is deferred until local testing is complete.

```text
data/
  .arena-storage.json     Initialization marker and legacy migration inventory
  postgres/               PostgreSQL 17 cluster, accounts, sessions and all metadata
  platform/               Uploaded and seeded CSV datasets
  hub/                    Hub database and persistent cookie secret
  notebooks/
    arena-<user-id>/       Private .ipynb files, outputs and workspace files
  recovered-notebooks/    Legacy private files without a matching current account
  legacy-notebooks/       Older shared notebook volume, if present
  backups/                Consistent offline archives, including local credentials
  development/            Separate SQLite/files for standalone API development
```

Competition and benchmark definitions, public test CSVs, private answers, creator metadata, public notebook templates, competition submissions/scores, course progress, discussions, comments and model reference cards are database records. Private executed notebook copies live in each user's workspace. New notebooks start as leased `arena-draft-<id>.ipynb` files; only explicit Save creates their permanent record and working copy. Discard and expiry cleanup remove temporary files (see [draft lifecycle](notebooks.md#new-notebook-drafts)). Save notebook files and experiment artifacts under `/home/jovyan/work`; kernels, unsaved editor state and packages installed into the container image filesystem are temporary. Add reusable packages to the scientific image. Dataset uploads to Arena and artifacts written by notebook code are separate stores; automatic dataset mounting is still pending. The native editor does not expose a file browser. Add Input copies a public CSV dataset to `arena-input-<dataset-id>.csv` in the user workspace. Upload publishes a public dataset and attaches a copy; both remain after discarding a notebook draft.

## First installation

```bash
python scripts/configure_notebooks.py
python scripts/storage.py plan
python scripts/storage.py init
python scripts/containers.py up --build
```

`scripts/containers.py` uses Compose directly on Docker. On Podman it starts services in order and checks initialization exit codes and service health, avoiding podman-compose’s native dependency issue with completed one-shot containers. `make up` and `make down` use this script.

Initialization uses a temporary root helper container to set service ownership without making directories world-writable. PostgreSQL uses UID/GID 70 from the pinned Alpine image; the API uses UID 10001; notebook workspaces use UID 1000/GID 100. On rootless Podman, these map through the runtime's user namespace. Do not replace permissions with `chmod -R 777`.

The one-shot `storage-check` service refuses startup without the initialization marker, required directories or the expected PostgreSQL major version. Keep `DATA_ROOT` stable. If you move the checkout, stop all notebook servers and services, move the complete data directory and update the absolute path before restarting.

## Upgrade from named volumes

Save work and close active notebooks first. Review the mapping, then migrate:

```bash
python scripts/configure_notebooks.py
python scripts/storage.py plan
python scripts/storage.py migrate
python scripts/containers.py up --build
```

Migration stops only Arena services and notebook containers, copies existing named volumes into empty destinations, verifies every copied regular file with SHA-256, and prepares ownership. It refuses to overwrite nonempty destinations and never deletes the original named volumes. A failed migration leaves services stopped; investigate before restarting or changing the destination. Keep the legacy volumes until you have verified the migrated installation and a backup.

Account IDs are read from the running legacy database before shutdown. Only notebook volumes belonging to verified account IDs become active workspaces. Others are retained in `recovered-notebooks`, preventing newly registered users from inheriting old private files after a previous database reset. If the legacy database is stopped, start it before migration to enable account matching; otherwise all notebooks are preserved for manual recovery. Review ownership before copying recovered files into an active user's directory.

A separate older standalone SQLite installation is not automatically imported into PostgreSQL. Its original `apps/api/.data` remains untouched. Export/import those records separately if that development database contains data you need.

## Stop, rebuild and restart

```bash
python scripts/containers.py down
python scripts/containers.py up --build
```

Container deletion and image rebuilding preserve host files. Stop user servers in Arena before planned maintenance. A host reboot requires the Docker/Podman service and its API socket to be available again. With Podman, configure a persistent socket service as described in [notebook setup](notebooks.md).

## Backup and recovery

```bash
python scripts/storage.py backup
python scripts/containers.py up
```

Backup stops Arena services and user servers, then creates `data/backups/arena-<UTC timestamp>.tar.gz` with the complete data tree except previous backups, plus `.env` under `secrets/.env`. It leaves services stopped on success or failure. Archives are mode 0600 because they contain password hashes, session data and service credentials. Copy backups to another disk or backup system: container persistence does not protect against host disk loss.

To restore, stop Arena and its notebook servers, and extract a trusted archive into a new empty staging directory, preserving numeric ownership (use root or the corresponding rootless runtime user namespace). The archive contains `data/` and `secrets/.env`. Preserve the current data and environment for rollback; place the restored data tree in the intended location, restore credentials, and set `DATA_ROOT` to its absolute host path. Start the same PostgreSQL 17 image and compatible application version with `python scripts/containers.py up`, then verify login, dataset downloads and saved notebooks. Never extract over a running or nonempty database. Major PostgreSQL upgrades require logical dump/restore or the PostgreSQL upgrade tools, not copying an old cluster into a new major image.

References: [Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/) and [DockerSpawner data persistence](https://jupyterhub-dockerspawner.readthedocs.io/en/stable/data-persistence.html).

## Podman startup dependency error

If direct `docker compose up --build -d` ends with `container state improper` or a dependency that is not running, use:

```bash
python scripts/containers.py up
```

The startup script detects native Podman dependencies left by direct Compose startup and recreates the Arena containers before starting them in health-checked order. This briefly stops Arena and its notebook servers; saved data stays in the existing host directories. Subsequent starts keep correctly configured containers. Use `make up` when rebuilding images, or the command above to start already built images.

The `Emulate Docker CLI using podman` message is informational. The `SHELL` and image `HEALTHCHECK` OCI warnings in the scientific image build are separate from the dependency failure; the Compose service health checks remain explicit.

## Deleting your work

Your work supports permanent deletion of owned datasets, notebooks, model cards and challenges. The API checks ownership and removes the published database record in a transaction. Challenge entries, submissions and creator metadata are removed in that transaction. Model-card deletion does not delete an externally hosted model.

Dataset upload deletion uses a durable `work_file_deletions` job committed with the record removal; the API attempts the file deletion immediately and the background worker retries failures. Notebook deletion queues the owner's `arena-notebook-<id>.ipynb`, expires linked draft editors and detaches their database references. The existing draft worker removes expired draft files. Every 30 seconds the file worker retries cleanup; it closes the matching notebook session and removes the file once the user's runtime is ready. It does not start offline runtimes solely for cleanup. Pending jobs survive API/container restarts.

Downloaded copies and input or notebook copies in other workspaces remain. Existing backups are not rewritten by deletion.

Competition overview records, dataset profiles, and competition CSV snapshots are stored in PostgreSQL and persist under the existing `DATA_ROOT/postgres` directory. Original catalog CSVs remain in `DATA_ROOT/platform/uploads`. Competition snapshots survive source dataset deletion. The additive startup backfill preserves existing users, memberships and scores; see [competition metadata](competition-metadata.md) for the schema and access rules.
