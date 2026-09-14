# Arena deployment pipeline (ocp4.lab.local)

Builds and deploys Arena to the `arena` namespace from this host. The host has
internet access; the cluster does not. Images go to the mirror Quay at
`registry.ocp4.lab.local:8443/init`.

## Update the cluster

```bash
make check               # offline API tests + web type-check/build on the working tree
git commit -am "..."     # only committed sources are built
make deploy-plan         # what would be built and which cluster objects change
make deploy              # test, build, push, deploy, verify
```

`make check` needs no commit and does not touch the cluster. Limit it with
`make check ARGS="--only api -k teams"` or `ARGS="--only web"`.

`make deploy` runs `pipeline.py run`:

1. Refuses to run if `apps/`, `infra/`, `scripts/` or `sources/` have uncommitted changes.
2. Copies committed sources into `sources/project`.
3. Refreshes dependencies from the internet if their files changed since the last
   refresh: only the npm cache when just `package*.json` changed, otherwise
   `sources/scripts/bundle.py prepare` (wheels and npm cache).
4. Tags each image
   `src-<hash>` of its sources, base image and wheels. Components whose tag is
   already live are not rebuilt or restarted.
5. Runs the API tests offline under an arbitrary UID if the API changed.
6. Builds changed images with `--network=none` using `sources/dockerfiles/`, and
   pushes them in 64 MiB chunks (Quay rejects multi-GB single-request layer uploads).
7. Renders manifests (`render.sh` → `overlay.py`) and validates them with a server-side dry run.
8. If the runtime image changed, caches it on every node before notebooks and evaluations switch to it.
9. Applies, waits for rollouts, and runs smoke tests: the portal, `/api/health`,
   API → JupyterHub, and the Hub Service endpoints.
10. If any step after apply fails, redeploys the previous release.

Pass options with `ARGS`, e.g. `make deploy ARGS="--skip-tests"`:

| Option           | Effect                                                              |
| ---------------- | ------------------------------------------------------------------- |
| `--skip-tests`   | Skip the offline API tests                                          |
| `--no-cache`     | Rebuild all image layers (automatic after a dependency refresh)     |
| `--refresh-deps` | Re-download wheels and npm cache even if dependency files are unchanged |
| `--refresh-npm`  | Re-download only the npm cache (e.g. `npm ci --offline` reports `ENOTCACHED`) |
| `--force`        | Deploy while evaluation Jobs are running (they are interrupted)      |
| `--no-rollback`  | Leave a failed release in place for debugging                       |

## Releases and rollback

```bash
make deploy-releases                  # * marks the current release
make deploy-rollback                  # redeploy the release before the current one
make deploy-rollback ARGS="--to 20260914T101500Z-9ac55a2"
```

Each release keeps its rendered manifest in `releases/<id>/`. Output of each run
and rollback is in `logs/`. Rollback restores images and manifests, not the
database: the API creates new tables and columns at startup, and those remain.

## Notes

- A deploy restarts only the Deployments whose image or configuration changed.
  Each uses the Recreate strategy, so the portal or Hub is briefly unavailable.
- A running notebook server keeps the old runtime image until its user restarts it.
- The run stops if evaluation Jobs are active and the API or worker would be
  restarted. Images already built are reused when you run it again.
- Cluster-specific fixes to `infra/openshift/render.py` output live in `overlay.py`.
  `postgres.yaml` is applied on every run and is otherwise unmanaged.
- Old `src-*` images are pruned from local podman storage; the registry keeps them for rollback.
