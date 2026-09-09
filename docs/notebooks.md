# Arena notebook editor

Arena owns notebook editing and output rendering. JupyterHub and Jupyter Server are backend compute services. The browser does not embed JupyterLab or connect to its Contents API, file browser, terminal or kernel WebSockets. The web gateway rejects `/jupyter/` URLs.

## Start

```bash
python scripts/configure_notebooks.py
python scripts/containers.py up --build
```

For first installation, prepare storage as described in [storage operations](storage.md). Podman requires its Docker-compatible API socket configured in `.env`.

## Editing and execution

Create → Notebook opens a temporary notebook automatically. Existing notebooks open a full-screen Arena editor; Start session connects their private working copy. CodeMirror supplies Python highlighting, indentation and editor undo/redo. Cells can be inserted, deleted and moved. Markdown supports headings, tables, lists and fenced code. Run cell, Run all, Interrupt and Restart kernel are available. Shift+Enter runs a cell; Ctrl/Cmd+S saves.

The workspace follows the supplied Kaggle reference: a slim navigation rail, editable title, menus and execution toolbar, a scrolling cell canvas, a right notebook panel and a bottom console. Cell controls float above the selected cell. View toggles the console, notebook panel and line numbers. Edit provides cell cut/copy/paste and output clearing. The console executes Python in the same notebook kernel, so it can inspect variables created in cells; its output is transient and is not included in notebook saves.

**Add Input** selects an existing public Arena dataset and inserts a `pandas.read_csv` loader cell. The backend copies the CSV into the user’s workspace as `arena-input-<dataset-id>.csv`; the loader reads that local file inside the notebook container. Input references persist in notebook metadata on Save. **Upload** explicitly publishes a public CSV dataset and attaches its loader; published datasets remain even if a temporary notebook is discarded. Input copies persist in the user’s workspace independently of notebook drafts and can be reused by later notebooks; automatic mounting and input-copy cleanup are not implemented. The output panel reports cell outputs and offers saved notebook download. Markdown headings populate the clickable table of contents.

Save updates the existing permanent snapshot; version history, collaboration/sharing controls and scheduled runs are not implemented. The schedule section states this limitation rather than accepting a schedule it cannot execute.

The API creates or reuses a kernel session tied to the current user's exact notebook path, forwards execution requests over an internal authenticated kernel WebSocket and streams results as NDJSON. No client-supplied filesystem path or kernel ID is accepted. Execution preserves kernel variables between cells. Interrupt stops Run all from starting further cells. Restart clears kernel memory, retaining cell sources and existing outputs.

Supported outputs include text, Python errors, PNG/JPEG plots, sanitized HTML tables and Markdown. Embedded scripts, raw Markdown HTML, Jupyter widgets and interactive stdin prompts are not supported. Execution is limited to two minutes per cell and 10 MB of streamed output. Output is kept in editor memory until explicit Save. Saved documents are limited to 500 cells and 10 MB.

The browser never receives the Hub service token. Files are accessed only through notebook-specific Arena operations. Python code itself still has the filesystem and network permissions of its container; removing a file browser is not a sandbox for hostile code.

## Persistence

Private working copies and draft files remain in `data/notebooks/arena-ID/`. Saved `.ipynb` files retain all cell sources, Markdown, outputs and metadata. Public template code stays in PostgreSQL. The runtime socket is mounted only into Hub. See [storage operations](storage.md) for backups and migration.

## Tests

```bash
make test
make build
cd apps/web
npm run test:e2e
npm run test:hub
```

The live suite verifies real Python execution, table/plot rendering, safe HTML output, Markdown cells, persistent reopening, drafts, and direct Jupyter URL rejection. Screenshot: `apps/web/hub-test-results/native-notebook.png`.

References: [Jupyter Server REST API](https://jupyter-server.readthedocs.io/en/stable/developers/rest-api.html), [Jupyter kernel WebSocket protocol](https://github.com/jupyter-server/jupyter_server/blob/main/docs/source/developers/websocket-protocols.rst), [websockets client API](https://websockets.readthedocs.io/en/15.0.1/reference/asyncio/client.html).

## New notebook drafts

**Create → Notebook** and **New notebook** open a full-screen editor and start the user's Jupyter server automatically. A randomly named `arena-draft-<id>.ipynb` file is created in that user's workspace. It is temporary and it does not appear in the public notebook list.

Give the notebook a title and use the Arena **Save** button or the editor's keyboard shortcut (Ctrl/Cmd+S). This creates one persistent notebook record and copies the full notebook document—including Markdown and outputs—to `arena-notebook-<id>.ipynb`. Further explicit saves update that same record and working copy. The current kernel continues running in the draft during editing. After the first save, closing retains the last explicit saved version; further unsaved edits are discarded. Published template code follows the existing public notebook behavior, while executed working copies remain private to the user.

Closing the editor shuts down only the draft's document session and deletes its temporary file; it does not stop other notebooks. Browser page-exit cleanup is best effort. An active editor renews a three-minute lease every thirty seconds, and the API checks abandoned drafts every thirty seconds. If Jupyter is unavailable, deletion is retried when it becomes reachable and the user's server is ready. Temporary files may therefore remain on disk during an outage, but are not published or treated as permanent notebooks. Pausing a browser or losing its connection for longer than the lease can expire an unsaved draft.
