# Integrated JupyterHub notebooks

## Start

```bash
python scripts/configure_notebooks.py
docker compose up --build -d
```

Open http://localhost:8080, sign in, open a notebook, and choose **Open in JupyterLab**. The service secret is generated in ignored `.env`, shared only between the API and Hub, and never embedded in an iframe URL. The Hub does not expose a separate host port.

For Podman, enable its Docker-compatible API first. One local development option is:

```bash
podman system service --time=0 unix:///tmp/arena-podman.sock
```

Keep that command running in a separate terminal and set `DOCKER_SOCKET_PATH=/tmp/arena-podman.sock` in `.env`. For a persistent installation, use Podman's systemd socket activation and set its actual socket path. Reconcile the whole stack with `docker compose up -d`; some Podman Compose versions cannot replace a single service while dependent containers exist. SELinux-enabled hosts may need a suitable socket access policy; do not relabel a shared system socket blindly.

## Notebook Studio

Opening a notebook now uses a full-screen workspace. The notebook is centered in a focus view with larger code cells, line numbers, wrapped source, readable Markdown, and scrollable table/image outputs. Switch **Full IDE / Focus view** to reveal JupyterLab's full menus and panels when needed.

The Arena toolbar drives the current JupyterLab notebook directly:

- **Run cell / Run all**, **Interrupt**, and **Restart** use the active kernel. Restart retains JupyterLab's confirmation dialog.
- **Code / Markdown** insert a cell below the selection and enter editing mode.
- **Save** persists the current working notebook. The bottom bar displays cell position and the notebook's actual dirty state.
- **Files** opens the upload/file browser; **Outline** opens the table of contents.
- Theme and keyboard-shortcut controls are available beside the layout controls.

JupyterLab continues to own notebook models, rendering, autosave, undo, keyboard shortcuts and kernel messages. `jupyterBridge.ts` connects to its public application/command API; the runtime enables `LabApp.expose_app_in_browser`. The bridge is only for the existing same-origin trusted deployment, not a cross-origin integration.

After upgrading, save your current notebook, stop its server, and reopen it once to pick up the new image configuration. Existing running servers are not automatically terminated. If the command bridge is unavailable, the ordinary embedded JupyterLab interface remains usable and the workspace displays recovery guidance.

## Request flow

1. Arena authenticates `POST /api/notebook-session` and derives a stable Hub name, `arena-{user.id}`. No endpoint accepts a client-selected Hub username.
2. The API creates the Hub user if necessary and starts their default server through the Hub REST API. The browser polls `GET /api/notebook-session` while DockerSpawner starts the container.
3. `POST /api/notebooks/{id}/open` waits for a ready server, then uses the Jupyter Contents API to import the template if the user's working copy does not exist. It returns a relative Hub login URL containing only the notebook path.
4. The Hub's custom authenticator verifies the existing HTTP-only Arena session against `/api/auth/me`, sets its own login cookie, and redirects to JupyterLab. Normal Hub OAuth establishes the single-user browser session.
5. Nginx proxies `/jupyter/` including kernel WebSockets. Its `auth_request` gate requires a valid Arena session and restricts `/jupyter/user/arena-ID/` to the current user. Hub management APIs are not exposed through this browser path. Hub and notebook CSP permit same-origin framing; XSRF checks remain enabled.
6. JupyterLab saves to a per-user volume. Downloading a working copy retrieves its current saved notebook JSON, including outputs. Stopping a server removes the container and retains its volume for the next launch.

## Storage and lifecycle

- One running default server per Arena account; all its notebooks share that server.
- Public template source remains in Arena's database; private working files live at `/home/jovyan/work/arena-notebook-ID.ipynb`.
- Volume names are `arena-notebook-data-{escaped Hub username}` (DockerSpawner escapes punctuation in `arena-ID`); they are managed by DockerSpawner and are not deleted by ordinary Compose shutdown.
- No automatic synchronization from private output back into the community template. Use the template editor deliberately to publish source; use JupyterLab to edit and save your private working copy.
- Existing legacy `notebook-data` is retained but is not automatically migrated into a user's new volume.
- Stopping ends every kernel in the user's server. Save in JupyterLab first. Closing the Arena dialog keeps execution running.
- Defaults: 2 GB RAM, 2 CPUs, 256 processes per user, five concurrent starts, twenty active servers. These are configurable in `infra/jupyterhub/jupyterhub_config.py`. Idle culling and per-account usage quotas are not implemented.

## Development and tests

For frontend hot reload with live notebooks, keep Compose running and use:

```bash
cd apps/web
ARENA_API_PROXY=http://127.0.0.1:8080 npm run dev
```

Both `/api` and `/jupyter` must refer to the same deployed Arena account database. Do not mix a standalone SQLite API with the PostgreSQL-backed Hub authenticator.

```bash
make test
make build
cd apps/web
npm run test:e2e
npm run test:hub
```

`test:e2e` starts standalone local test servers and checks the regular platform workflows. `test:hub` targets the already running stack on port 8080 and tests a real iframe, Python kernel output, saving, stop/restart persistence, and cross-user access rejection. It creates test accounts/notebooks and persistent notebook volumes; it stops the successful test's server but keeps its files.

## Troubleshooting

- **JupyterHub is not configured:** the API needs `JUPYTERHUB_API_URL`, `JUPYTERHUB_PROXY_URL`, and `JUPYTERHUB_API_TOKEN`. Compose supplies all three.
- **Service credentials rejected:** API and Hub must use the same token; recreate both after changing it.
- **Container cannot start:** check `docker compose logs jupyterhub`, the Docker socket mount, the `arena-singleuser:5.3.0` image, and the `arena-notebooks` network.
- **Iframe is blank or forbidden:** use the Arena web gateway rather than a direct Hub address; check the authenticated Arena session and preserve CSP `frame-ancestors 'self'` and the WebSocket proxy headers.
- **Old notebook code appears:** this is your previously saved working copy. Community template changes intentionally do not replace it. Rename/delete that working file in JupyterLab if you want the next open to import a fresh template.

## Deployment boundary

This is a functioning local/trusted-community integration, not a hostile multi-tenant sandbox. Same-origin notebook content can act on the user's Arena origin. Public multi-tenant deployment should use per-user notebook domains, a deliberate iframe/SSO policy, runtime network restrictions, quotas and idle cleanup. The Hub's Docker socket access is equivalent to host container-administration authority; keep it out of notebook containers and restrict access to Hub configuration and credentials.

References: [JupyterHub container images](https://github.com/jupyterhub/jupyterhub-container-images), [DockerSpawner image compatibility](https://jupyterhub-dockerspawner.readthedocs.io/en/latest/docker-image.html), [persistent user volumes](https://jupyterhub-dockerspawner.readthedocs.io/en/stable/data-persistence.html), [Hub OAuth](https://jupyterhub.readthedocs.io/en/stable/reference/api/services.auth.html).
