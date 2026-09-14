# Datasets

A dataset is a set of files with immutable, numbered versions. Versions, safe previews, chunked uploads and storage quotas share their implementation with [models](models.md).

## Versions

- Every dataset has versions 1, 2, … Each version records its files, a version note, its creator and when it was published. The newest published version is **latest**, and latest is the default everywhere: the detail page, the CSV download link, the legacy preview and new notebook inputs.
- Owners and administrators create a new version as a **draft**. A draft can start from the latest version's files (**Start from version N's files**; carried-over files share their stored bytes) or empty. Upload files, remove files, then publish with a note describing the change. A dataset has at most one draft, and only people who can manage the dataset see it.
- Publishing assigns the next number. Numbers are never reused: deleting a version removes its files but keeps a placeholder, so a notebook pinned to it fails with a clear error instead of reading different files. The last remaining version cannot be deleted; delete the dataset instead.
- Visibility follows the dataset. Datasets are private by default; sharing, public visibility and moderation apply to every version and file. Hidden datasets stay out of listings and search for everyone except their owner and administrators.

On the dataset page, **Files** browses any version with a per-file type and size, a path filter and a preview; **Version history** lists versions with notes and lets managers delete them.

### Legacy fields, links and endpoints

`filename`, `size`, `GET /api/datasets/<id>/download` and the ten-row `preview` in `GET /api/datasets/<id>` describe a CSV file of the latest version: the file with the previous primary name if it still exists, otherwise the first CSV by path. When the latest version has no CSV, those fields are empty and the download returns 404. Old notebooks that attached a dataset as `arena-input-<id>.csv` read the same file. Column profiles (`GET /api/datasets/<id>/metadata`) describe that CSV; files over 64 MiB are sampled from their start and report an unknown row count (`-1`).

The single-request endpoints still work. `POST /api/datasets` (one CSV up to 10 MB) creates the dataset with version 1. `POST /api/assets/datasets/<id>` (one file up to 10 MB) keeps its file-version record and also publishes the next version, carrying over the latest files and adding or replacing that path.

### Upgrading existing data

Migration `0014_resource_versions_backfill` turns every existing dataset into version 1 exactly once: its primary CSV plus the newest supplemental file of each path (a supplemental file with the primary's name replaces it, as notebook inputs did before). Files are not moved; `stored_files` rows point at the existing `uploads/` and `artifacts/` blobs. The migration receipt and the per-dataset version rows make re-runs change nothing. `seed()` and the sample, Titanic and practice importers run the same idempotent backfill, so seeded datasets, practice competitions and courses keep working unchanged. Older superseded supplemental file versions stay downloadable through `/api/assets/datasets/<id>` but are not part of any version and do not count toward quotas.

## Files and previews

A version holds up to 10,000 files. Paths are relative, NFC-normalized and at most 240 characters; absolute paths, drive letters, backslashes, colons, control characters and empty, `.` or `..` segments are rejected. Every preview reads a bounded prefix of the file; nothing is executed or extracted.

| Type | Extensions | Preview |
| --- | --- | --- |
| Table | `.csv`, `.tsv` | First 100 rows and 100 columns from the first 1 MiB, plus a column summary (values, missing, distinct, min, mean, max) from up to 10,000 rows |
| JSON | `.json` | Pretty-printed when at most 256 KiB, otherwise the first 256 KiB as text |
| JSON Lines | `.jsonl`, `.ndjson` | First 50 records, pretty-printed |
| Text and Markdown | `.txt`, `.md`, `.py`, `.yaml`, `.log`, … | First 256 KiB; Markdown uses the sanitized Markdown renderer |
| Image | `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp` | Shown inline up to 20 MB, only when the file's magic bytes match its type |
| NumPy | `.npy` | dtype, shape and up to 20 values (header parsed without NumPy) |
| ZIP | `.zip` | Member names and sizes (500 shown) from the central directory, with warnings for unsafe member paths and extreme compression ratios. Archives declaring over 10,000 members or a central directory over 16 MiB are not listed |
| Parquet | `.parquet` | Download only: pyarrow is not in the offline Python kit |
| HTML, SVG, XML | `.html`, `.htm`, `.svg`, `.xml`, … | Never displayed; download only |
| Other | anything else | Text if the first 8 KiB is UTF-8 without NUL bytes, otherwise download only |

Downloads are served as `application/octet-stream` attachments with `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'; sandbox` and a sanitized filename. Images are served inline with their verified type from a separate endpoint. Stored files are opened without following symlinks and only from their store folder.

## Uploads

The web proxy accepts request bodies up to about 11 MB and waits 180 seconds, so the UI uploads every file in resumable chunks:

1. `POST /api/uploads` with the draft `version_id`, the relative `path`, `size` and an optional `sha256`. The owner's quota and the uploader's limit on unfinished uploads are checked.
2. `PUT /api/uploads/<id>/chunks/<index>` sends raw chunk bytes (8 MiB by default) in any order; an `X-Chunk-Sha256` header is verified when present. Parts are written to a temporary name and renamed into place, so a retried chunk simply replaces the previous attempt.
3. `GET /api/uploads/<id>` lists received chunks. The browser remembers the session id in `localStorage`, keyed by the draft, path, file name, size and modification time; choosing the same file again after a reload resumes where it stopped.
4. `POST /api/uploads/<id>/complete` checks every chunk and the quota, then assembles the parts in the background into a hidden temporary file, verifies the total size and the declared SHA-256 (the server always computes its own), renames it into place and attaches it to the draft. Poll the status until it is `completed` or `failed`; a digest mismatch fails the upload and deletes the parts.
5. `DELETE /api/uploads/<id>` cancels an upload and deletes its parts.

The uploader shows per-file progress and supports pause, resume, retry of failed chunks (with backoff) and cancel. A background task removes sessions idle for `UPLOAD_SESSION_TTL_HOURS`, deletes their parts and orphaned part folders, and returns assemblies interrupted by a restart to `uploading` so they can be completed again.

| Variable | Default | Purpose |
| --- | --- | --- |
| `UPLOAD_CHUNK_BYTES` | `8388608` (8 MiB) | Chunk size, 1 KiB to 10 MiB; keep it under the proxy body limit |
| `UPLOAD_MAX_FILE_BYTES` | `107374182400` (100 GiB) | Largest single file |
| `UPLOAD_MAX_ACTIVE_SESSIONS` | `8` | Unfinished uploads per user |
| `UPLOAD_SESSION_TTL_HOURS` | `24` | Idle time before an upload and its parts are removed |
| `UPLOAD_DIR` | `$DATA_DIR/upload-sessions` | Chunk parts; must be shared by every API replica |
| `JOB_INPUT_MAX_BYTES` | `21474836480` (20 GiB) | Largest dataset or model version staged into one background job |

## Storage quotas

Each user has a storage quota: the `storage_quota_gib` site setting (default 20 GiB), or a per-user override set in **Administration → Storage** (recorded as `user.storage_quota` in the audit log).

Usage is the size of every stored blob the user owns (dataset-version files, model-version files and legacy supplemental files) plus the bytes received so far by their unfinished uploads. A blob shared by several versions through carry-over counts once; uploading identical bytes again stores and counts a new blob. Files are charged to the owner of the dataset or model, also when an administrator uploads them.

A new upload must fit next to the full declared size of the owner's other unfinished uploads, and completing it must still fit. The single-request endpoints check the quota too. Deleting a version, a draft file, a draft, a dataset or a model frees the space of blobs no remaining version uses; the files are removed by the durable cleanup queue. Account settings and the uploader show a usage meter (`GET /api/storage/usage`); administrators see per-user usage in `GET /api/admin/storage`.

## Notebooks

- **New notebook** on a dataset, or **Add Input → Datasets** in the editor, attaches the latest version and pins it. The notebook metadata stores a format 3 reference with `version`. In the input panel, choose **Always latest** to follow new versions (the reference stores `"version": null` and is resolved whenever the notebook runs) or pick another version.
- Files are copied read-only to `input/<dataset-slug>-dataset-<id>/<path>`. Save & Run All, scheduled runs and competition commits stream every file of the resolved version into the isolated Job's work folder and make files under `input/` read-only (mode 0440); access is checked again for the notebook owner when the job starts.
- Interactive sessions copy sources through the Jupyter contents API, so sources over 200 MB or 1,000 files are attached without copying and marked in the input panel; background runs still stage them.
- Existing references keep working: format 2 references with pinned supplemental file ids resolve exactly as before, and `arena_inputs` references read the latest version's CSV.
- A notebook can be published only when its dataset inputs are public.

## API

| Method and path | Purpose |
| --- | --- |
| `POST /api/datasets/drafts` | Create a private dataset with an empty draft version (JSON: title, description, tags, license) |
| `GET /api/datasets/<id>/versions` | Published versions, plus the draft for managers |
| `GET /api/datasets/<id>/versions/<number\|latest\|draft>` | One version |
| `GET /api/datasets/<id>/versions/<ref>/files?q=&offset=&limit=` | Paginated files with type and size (`X-Total-Count`) |
| `POST /api/datasets/<id>/versions` | Create or return the draft (`{"carry_over": true}`) |
| `POST /api/datasets/<id>/versions/draft/publish` | Publish the draft (`{"note": "…"}`) |
| `DELETE /api/datasets/<id>/versions/draft` | Discard the draft and its uploads |
| `DELETE /api/datasets/<id>/versions/draft/files/<file_id>` | Remove a file from the draft |
| `DELETE /api/datasets/<id>/versions/<number>` | Delete a published version |
| `GET /api/datasets/<id>/files/<file_id>/download` | Download a version file |
| `GET /api/datasets/<id>/files/<file_id>/preview` | Bounded preview JSON |
| `GET /api/datasets/<id>/files/<file_id>/raw` | Verified image, inline |
| `POST /api/uploads`, `PUT /api/uploads/<id>/chunks/<index>`, `GET /api/uploads/<id>`, `POST /api/uploads/<id>/complete`, `DELETE /api/uploads/<id>` | Chunked uploads |
| `GET /api/storage/usage` | The signed-in user's storage |
| `GET /api/admin/storage`, `PUT /api/admin/users/<id>/storage-quota` | Per-user usage and quota overrides (administrators) |

All mutations use the usual `X-Arena-Client: web` header and origin checks. Tables: `stored_files`, `resource_versions`, `resource_version_files`, `upload_sessions`, `upload_chunks` and `user_storage_quotas`.
