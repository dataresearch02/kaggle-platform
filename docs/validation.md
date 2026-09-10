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

## Local persistence validation — 2026-09-08

- Migrated nine existing named volumes to `data/` and verified each copied regular file with SHA-256. Original volumes remain intact. Six notebook volumes had no matching account in the existing database and were preserved under `data/recovered-notebooks`.
- Confirmed original PostgreSQL counts immediately after migration: one user, three datasets, one notebook and zero submissions.
- Passed 35 API/storage tests, two browser workflow tests and the real JupyterHub browser test against host-mounted user workspaces. The live notebook test exercises execution, saving outputs, server removal/recreation and access isolation.
- Built API, web and Hub images; the scientific runtime image was reused. Prettier, Black and diff whitespace checks passed.
- Removed and recreated every Compose container, then verified an existing session, password login, dataset download bytes, notebook template source and all 26 recorded upload/workspace/recovery file hashes. The stack was left running at `http://localhost:8080`.
- Created a consistent offline backup and compared all 1,358 archived regular files with their sources, including the local environment file without displaying credentials.

The local startup wrapper handles Podman Compose 1.5.0’s incorrect native dependencies on completed initialization services. It explicitly checks initialization exit codes and service health before starting dependents. These checks target the local container product; OpenShift resources were not added.

## Community creation — 2026-09-08

Added a shared Create chooser for notebooks, datasets, competitions and benchmarks. Benchmarks are ongoing RMSE prediction evaluations; competitions have timezone-aware closing dates. Public features and private answers are validated together before an atomic database commit. Existing competitions are retained through a separate creator metadata table.

Validation: 47 API tests passed, including both creation/scoring workflows, anonymous creation rejection, private-answer exclusion, invalid IDs, nonfinite answers and deadline validation. All three browser workflows passed, covering dataset/notebook publishing, mobile navigation, and competition/benchmark creation through scoring and leaderboards. TypeScript/Vite, API/frontend image builds, Prettier and Black checks passed.

## Publishing interface follow-up

The sidebar Create dropdown supports keyboard navigation, Escape and outside dismissal. Publishing uses a dedicated workspace page with file drag-and-drop, filename/size review, removal and client-side CSV/size validation. Public visibility and private challenge answer handling remain explicit. Browser checks cover all four content types, authentication continuation, invalid-file rejection, drag-and-drop and mobile overflow. Screenshots are saved under `apps/web/test-results/` as `create-dropdown.png`, `upload-desktop.png` and `upload-mobile.png`.

Design reference: [Kaggle dataset creation documentation](https://www.kaggle.com/docs/datasets). Arena continues to accept one CSV per dataset; private datasets, multiple-file datasets and remote imports are not implemented.

## Sliding creation panel

Creation keeps the selected collection mounted behind a modal drawer. The panel animates from the right and occupies 50% of the viewport on desktop, becoming full-width at 900px and below. Escape, the close button, Cancel and backdrop clicks dismiss it; focus stays inside while open and returns to the trigger on close. Scrolling is contained within the panel, and reduced-motion preferences shorten animations. Browser checks include exact half-width positioning, the visible background collection, mobile overflow, closing and all publishing workflows.

## Temporary notebook editor

Create → Notebook now opens the full-screen Jupyter editor and automatically starts the runtime. New drafts stay outside the notebook catalog. Explicit Save and Ctrl+S preserve one permanent notebook record plus complete working-copy cells and outputs; closing removes the temporary file and its document kernel. A leased cleanup worker retries abandoned draft deletion.

Validated with 52 API tests, four regular browser workflows, and two live JupyterHub browser tests. The new live test checks automatic launch, no catalog entry before Save, actual temporary-file deletion on discard, output persistence on Save, Ctrl+S updating the same notebook, and temporary-file deletion while retaining the permanent copy. Screenshot: `apps/web/hub-test-results/new-notebook-saved.png`.

## Native Arena notebook editor — 2026-09-08

Replaced the JupyterLab iframe with Arena-owned CodeMirror cells, Markdown previews and sanitized rich outputs. JupyterHub supplies backend Python kernels only. The gateway returns 404 for direct Jupyter UI and Contents API URLs. Notebook document and execution endpoints derive each user's allowed document path on the server.

Validation: 56 API tests, four regular browser workflows and two real-kernel browser tests passed. Live checks cover Python text, pandas tables, plots, Markdown, output sanitization, interrupt, restart, saving and reopening after server replacement, temporary draft deletion, and permanent copies surviving draft cleanup. No iframe or Files button is present. Screenshot: `apps/web/hub-test-results/native-notebook.png`.

The API and web images were rebuilt and their local containers recreated. Interactive widgets and stdin prompts are not supported; execution is limited to two minutes and 10 MB of streamed output per request. Removing the file browser does not remove Python's filesystem permissions inside its runtime container.

## Reference notebook workspace — 2026-09-08

Recreated the supplied notebook reference layout with a compact rail and title/menu bar, execution toolbar, gray Python cells, floating cell actions, collapsible input/output/outline sections and a bottom Python console. The console shares the notebook kernel. Dataset selection and public CSV upload copy inputs into the current user's workspace through a notebook-scoped backend endpoint; generated loader cells read local CSV files.

Validation: 57 API tests and four regular browser workflows passed. All three real-kernel scenarios passed, including cell cut/copy/paste, shared console variables, dataset loading, public upload, mobile overflow, temporary drafts, persistence and execution controls. The existing kernel interrupt test timed out waiting for its initial output once; its isolated rerun passed. TypeScript/Vite and container builds, Prettier, Black and whitespace checks passed. The API and web containers were recreated locally.

Screenshots: `apps/web/hub-test-results/notebook-reference-layout.png` (1920 × 1080) and `apps/web/hub-test-results/notebook-reference-mobile.png` (390 × 844). Save remains an update to one permanent snapshot; version history, sharing/collaboration and scheduled execution are not implemented. Dataset uploads and attached CSV copies persist independently of temporary notebook cleanup.

## Your work — 2026-09-09

Added an authenticated personal workspace for owned datasets, saved notebooks (Codes), models, competitions and benchmarks. Sidebar navigation appears after the first published item. Collection-page links open the corresponding personal category. Search, category counts, opening content, title/description editing and dataset/published-notebook downloads are supported. Existing persistent records supply the workspace; temporary drafts and other creators' records are excluded.

Validated with 59 API tests and five browser scenarios. New checks cover ownership across all five categories, rejection of anonymous and cross-user edits, hidden challenge answers/storage keys, metadata validation, unchanged dataset bytes and notebook code, navigation appearing after upload, metadata editing, mobile overflow, and content clearing on sign-out. Screenshots: `apps/web/test-results/your-work-desktop.png` and `apps/web/test-results/your-work-mobile.png`.

## Your work deletion — 2026-09-09

Added an owner-only Delete endpoint and a per-item confirmation in Your work. Deletion removes published records and challenge-dependent entries/submissions. Dataset files are removed immediately with durable retry jobs on failure; notebook file jobs wait for an available runtime, close the matching session and remove the owner's saved copy. Linked notebook drafts expire and cannot recreate a deleted notebook through Save. Other users' copied files are preserved.

Validation: 62 API tests and five browser tests passed, including anonymous/cross-user rejection, all five work categories, challenge reference cleanup, actual CSV removal with neighboring files preserved, offline notebook cleanup retry, draft invalidation, confirmation cancellation and successful deletion from the personal list. TypeScript/Vite and API/web container builds, Prettier, Black and whitespace checks passed.

## Competition overview filters — 2026-09-09

Replaced Explore/Your work collection tabs with a standalone Your work button on Datasets, Models, Codes, Competitions and Benchmarks. Competition search matches titles and descriptions and combines with open/closed status, category, and newest/closing-soon/title sorting. Category choices come from competition records, excluding benchmarks. Status evaluates timezone-aware deadlines, and filters apply before the 100-result limit. Clear filters restores the defaults.

Validation: 63 API tests and six browser tests passed, covering combined queries, description search, category options, sorting, closed deadlines with timezone offsets, invalid filter rejection, clear/reset controls, personal-work navigation and mobile overflow. Production builds and formatting checks passed. Screenshot: `apps/web/test-results/competition-filters.png`.

Local rollout also required repairing stale Podman pod metadata and Arena-only DNS records that still referenced old gateways, restoring the Hub cookie file to mode 600, and stopping an orphaned Arena web monitor holding port 8080. Persistent project data directories were retained while the containers were recreated.
The final port check also found a stale Arena-only DNAT rule forwarding localhost:8080 to the removed container. Removed that obsolete rule and its old subnet mark rule, retaining the new forwarding destination. The web gateway then returned successful health and competition-filter responses.

## Full competition pages — 2026-09-09

Competition cards from the overview, home and Your work now open dedicated pages with hash routes per section. Overview, Data, Code, Models, Discussion, Leaderboard and Rules support refresh and browser history. Join reflects authenticated membership and closing status. Data includes a public CSV preview/downloads; Leaderboard contains scoring and personal submissions. Published notebooks/model cards can be linked by their owners, and discussion posts persist per competition. Competition deletion cleans up its new links and posts; resource deletion removes its links.

Validation: 64 API tests and seven browser tests passed. Coverage includes all sections, deep links, refresh/back navigation, joining/scoring, private-answer exclusion, membership authentication, owner-only resource linking, duplicate link prevention, scoped posts, deletion cleanup and mobile overflow. Production builds and formatting checks passed. Screenshots: `apps/web/test-results/competition-page-desktop.png` and `apps/web/test-results/competition-page-mobile.png`.

## Optional Kaggle sample collection

- API suite: **66 passed**, including import idempotency, preserving edits/deletions, rollback cleanup, public dataset downloads and scoring both generated baseline CSVs.
- Live sample browser test: **1 passed**, executing all four imported notebooks against real Jupyter kernels, rendering both plots, downloading both CSVs and submitting them through the competition leaderboard UI. The resulting scores belong to the explicitly named `sample_test_*` account used by the test.
- Local API/web container builds succeeded. The collection was imported into persistent local storage; a second import returned `already imported` with the same IDs.
- Prettier checks passed. Vite still reports its existing large JavaScript bundle advisory.

Run the optional live check after importing the collection with `npm run test:hub -- samples.spec.ts` from `apps/web`. It skips when the sample competitions are absent.

## Competition metadata and joined data explorer

- API suite: **70 passed**. Additional coverage checks organizer-only metadata writes, date validation, joined-only previews/downloads (including legacy routes), cross-competition file isolation, CSV validation, row pagination, column descriptions, persistent snapshots after source deletion and repeatable backfill.
- Existing browser workflows: **7 passed**. The new organizer workflow passed separately after explicit textarea labels were added: edit/save/reload overview, upload a nested training CSV, edit its dictionary, inspect preview and verify mobile width.
- Final targeted API checks: **6 passed** for metadata and sample import behavior. Frontend TypeScript/Vite build, Prettier and targeted Black checks passed.
- Desktop and mobile data-explorer screenshots were generated under `apps/web/test-results/`.
- Live PostgreSQL/container verification: both existing practice competitions were backfilled with train/test/submission snapshots (Iris: 120/30/30 rows; Penguins: 273/69/69 rows). Anonymous legacy/file downloads returned 401; the existing joined sample account could preview/download all files. Existing leaderboard scores remained available.

## Paginated code library and read-only publications

- API suite: **76 passed**. New coverage verifies bounded cursor pages, stable pagination during insertion, omission of source/documents from summaries, competition scoping, private bookmark filters, author-controlled sharing/revocation, public/private document separation, input-preserving forks and deletion cleanup.
- Browser suite: **10 passed**. Checks include 20/40/42-row scroll loading, personal filters, shared recipients, desktop/mobile read-only viewing, sanitized saved outputs, no runtime requests while viewing, and all existing platform workflows.
- Live notebook checks: **5 passed across two runs**. Publication/fork and sample-submission tests passed; the three existing editor/draft/kernel-control tests also passed through the updated navigation. Fork execution preserved inputs and publishing fork results did not change the source notebook.
- Final API/web images were rebuilt and started locally. The deployed competition code list displayed all four filters. Existing data was retained; new publication/bookmark/share tables were added at startup.
- TypeScript/Vite build, Prettier, targeted Black checks and `git diff --check` passed. Vite's existing large-bundle advisory remains.
- Screenshots: `apps/web/test-results/code-view-desktop.png`, `code-view-mobile.png`, and `apps/web/hub-test-results/competition-code-list.png`.

## New notebook from competition Code

- Draft API tests: **6 passed**, including membership enforcement, automatic competition linking on save, repeated-save idempotency and unsaved-draft cleanup.
- Live browser/kernel test: **1 passed** (`competition-create.spec.ts`): the button stays disabled before joining, opens the full-screen editor after joining, runs Python, saves into the competition's Your work filter, persists after refresh and discards an unsaved second notebook.
- API/web images were rebuilt and started locally; TypeScript/Vite, targeted formatting and diff checks passed.
- The local Podman API service at `/tmp/arena-podman.sock` was not running. It was restored and JupyterHub/web were recreated to bind the restored socket before the successful live test. Persistent data was retained.

### Compact notebook platform navigation

- The notebook rail shares Arena navigation labels and icons with the main sidebar, groups Data Hub destinations, and highlights Codes.
- Frontend production build passed.
- Live container browser test `integration/competition-create.spec.ts` passed, including mobile navigation to Datasets, closing the editor, successful deletion of the temporary draft, and preservation of the previously saved competition notebook.

### Navigation toggle and Markdown snapshots

- Added expand/collapse controls to the platform sidebar and notebook navigation. Expanded notebook navigation overlays the editor on small screens.
- Notebook editing and public code viewing share GFM and KaTeX rendering; Markdown editing includes syntax highlighting, insertion controls, Shift+Enter preview, and double-click/Enter to edit.
- Explicit draft Save now stores the full public notebook snapshot through the existing publication validation, retaining Markdown and outputs.
- Validation: frontend and container builds passed; 12 API draft/publication tests passed; the live competition creation browser test passed with navigation toggling, Markdown heading/table/math preview, saved read-only rendering, and draft cleanup.
- Existing notebooks whose public representation contains only Python require the owner to open the preserved working copy and select Publish code and outputs to refresh that snapshot.

### Published code viewer tabs

Frontend build passed. Seven code API tests passed, including comment persistence,
authentication, blank-body rejection and ownership checks. Two browser tests passed,
covering Input/Output/Logs tab contents, comment posting, persistence after reload,
deletion, and returning to the Notebook outline.

### Replies and reactions

Eleven API tests passed, including all four conversation target types, persistent
replies, idempotent reactions, reaction removal, authentication, reply ownership,
and invalid targets/reactions. Three browser tests passed, including notebook
comment and competition discussion replies/reactions surviving reload and removal.
Frontend and local API/web container builds passed.

### Sample notebook narratives

Updated all four existing curator notebook snapshots with Markdown headings,
descriptions, notes, tables, source credits, and runnable code cells. Three sample
API tests passed, including exact preservation of executable code and idempotent
upgrades. The live sample workflow test passed across all four notebooks: public
headings/tables, forks, plots, downloadable CSVs, and real competition scoring.

### Evaluated competition notebook commits

Forks and competition draft saves now stay private. The API suite verifies private
visibility, immutable commit snapshots, scoring before publication, idempotent
completion, and ownership/membership controls. Live browser tests verify a missing
CSV fails without publication, a fresh-kernel run receives test data and publishes
only after scoring, and subsequent saves preserve the published snapshot.

Final validation: **88 API tests** and **11 frontend browser tests** passed. Live
new-notebook commits passed after correcting the post-commit list refresh. The
runner now waits for shell and IOPub readiness before execution; a regression test
covers a dropped initial readiness message without executing code twice.

### Competition teams, submissions and navigation

90 API tests and 11 browser tests passed. New coverage checks membership gating,
invite isolation, duplicate membership, captain transfer, closed competitions,
team cleanup, team persistence after browser reload, the More group, Your work
ordering, and scoring from the Submissions tab. Production frontend and local
API/web container builds passed; the updated containers were recreated.

### Compact sidebar and active events

Twelve browser tests passed, including collapsed brand/group visibility, group
expansion, the Active Events empty state and Escape dismissal. The new API test
passed for owner isolation and queued/running filtering. Frontend build passed.

### Main workflow audit

See [the workflow review](logic-review.md) for findings and limits. Fixed competition
draft publication bypass and legacy private-edit exposure, added a mobile panel
close control, shared kernel readiness handling, and bounded scientific thread
pools. The API suite passed 92 tests; the final probe adjustment passed 10 targeted
tests. Twelve browser tests passed. All seven live workflows passed across the
final runs, with the four-notebook sample workflow passing after the thread-pool
fix. Checked record counts survived API/web recreation. This is local functional
validation, not a production readiness or disaster-recovery certification.
