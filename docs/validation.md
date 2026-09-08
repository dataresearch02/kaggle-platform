# Validation

Validated on 2026-09-07 after the JupyterHub integration.

| Check                                                                  | Result                               |
| ---------------------------------------------------------------------- | ------------------------------------ |
| FastAPI workflow, scoring, notebook lifecycle and gateway access tests | 28 passed                            |
| Existing Playwright desktop workflow and mobile navigation             | 2 passed                             |
| Live JupyterHub browser integration                                    | 1 passed                             |
| TypeScript and Vite production build                                   | Passed                               |
| Container builds: API, frontend, Hub, scientific notebook runtime      | Passed                               |
| PostgreSQL-backed Compose deployment                                   | Running; live test passed against it |

The live browser test uses the actual Nginx → JupyterHub → per-user scientific notebook container path. It registers an Arena account, opens a notebook in an iframe without a second login, executes Python using Shift+Enter, verifies `ARENA_KERNEL_OK`, saves the notebook and checks its exported outputs, stops the server, restarts it, and verifies that the output persists. A separate browser context verifies unauthenticated (401) and cross-user (403) gateway rejection. The test stops its user server after completion. A screenshot is saved at `apps/web/hub-test-results/jupyterhub-running.png`.

The 28 API tests include a Hub contract double for start/poll/import/export/stop, preserving existing working copies, separate user paths, unavailable configuration, and traversal/access rejection. The live test complements those contract tests with real image startup, OAuth, WebSockets, kernel execution and volume persistence.

This environment uses Podman 5.8.2 and Podman Compose 1.5.0. A Docker-compatible API service was started on `/tmp/arena-podman.sock`; ignored `.env` is configured with that socket path. Compose's default network was made explicit for Podman compatibility. Standard Docker Engine remains the default documented socket configuration.

Public hostile multi-tenancy, GPU training, automatic idle culling and distributed job scheduling are not implemented or validated. See `notebooks.md` for the actual deployment boundary.

## Notebook Studio follow-up

The live notebook test now also exercises the Arena toolbar, pandas table rendering, Markdown insertion/rendering, file and outline panels, focus/full-IDE switching, light/dark themes, and Run All. Notebook edits still persist through the real JupyterLab document model. The frontend and scientific runtime images were rebuilt; only the frontend container was recreated, preserving the pre-existing user kernel. Older running notebook servers require an explicit save, stop and reopen to load `LabApp.expose_app_in_browser`.
