# Code library and published notebook viewer

The competition Code tab and Data Hub Codes page use a vertical list. The **All**, **Your work**, **Shared with you**, and **Bookmarks** filters are independent of search. Competition lists include only notebooks associated with that competition.

The browser requests 20 summaries at a time, then requests the next page near the end of the list. A Load more button supports keyboard navigation, and failures offer a retry. Search and filter changes reset pagination. Summaries contain IDs, title, author, a short description, creation date and bookmark state; they omit source code and notebook documents. The sidebar requests only a small work-status flag, not all of the user's notebooks.

## Viewing, editing and forking

- Your own list entries open the full-screen editor at `/#code/{id}/edit`; other users’ entries open the read-only `/#code/{id}` page. Optional `?competition={id}` preserves the link back to the competition.
- The page displays Python cells, Markdown, published outputs and attached catalog inputs. Viewing requires no notebook runtime. HTML output is sanitized; code cells are not editable.
- **Fork code** creates a separate notebook owned by the current user, retains its parent attribution and competition editing context without adding any competition listing, and opens `/#code/{new-id}/edit`.
- Forks copy the published document, including Markdown, input references and outputs. They never read another user's runtime working copy. On first opening the fork's editor, available catalog inputs are copied into the user's workspace under fixed dataset filenames. Missing/deleted source inputs are marked unavailable by the viewer and cannot be restored automatically.
- Authors can use **Edit my code** to open a separate editor. **Save notebook** continues to save the private working copy. **Publish code and outputs** explicitly updates the public snapshot. Users should publish only cells and outputs they intend to make public.
- Legacy notebooks without a snapshot display their original source with no outputs. Existing private saved outputs are not automatically published. The editor's publication action makes them available deliberately.
- If an existing community template is updated using the legacy template API, its public snapshot resets to that source without stale outputs. Private working copies are still preserved.

## Bookmarks and sharing

Bookmarks are personal, persisted in PostgreSQL and can be toggled from either list or viewer. Personal filters require signing in.

An author can select **Share with user**, enter an existing username and later remove that share. The recipient sees it under Shared with you; sharing does not grant edit permissions. All published notebooks remain public. This feature does not introduce private notebooks or send external notifications.

## Database and API

| Table                   | Purpose                                                                                               |
| ----------------------- | ----------------------------------------------------------------------------------------------------- |
| `notebook_publications` | One explicit public document per notebook, optional parent notebook ID, publication update timestamp. |
| `notebook_bookmarks`    | Unique user/notebook bookmark pairs.                                                                  |
| `notebook_shares`       | Unique notebook/recipient pairs managed by the author.                                                |

The additive tables are created at startup without replacing existing notebook rows or working files. Notebook deletion removes its publication, bookmarks and shares, and clears parent links on surviving forks. Fork contents remain intact.

| Endpoint                                 | Behavior                                                                                                                                            |
| ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /api/code`                          | Cursor-paginated summaries. Parameters: `competition_id`, `filter=all/your-work/shared/bookmarks`, `q`, `cursor`, `limit` (default 20, maximum 50). |
| `GET /api/code/{id}`                     | Public document, author, inputs, lineage, associated competitions and the current user's bookmark state.                                            |
| `PUT/DELETE /api/code/{id}/bookmark`     | Add/remove the current user's bookmark.                                                                                                             |
| `GET/POST /api/code/{id}/shares`         | Author-only recipient listing or sharing using JSON `username`.                                                                                     |
| `DELETE /api/code/{id}/shares/{user_id}` | Author-only share removal.                                                                                                                          |
| `PUT /api/code/{id}/publication`         | Author-only explicit publication of an nbformat 4 document (maximum 500 cells / 10 MB).                                                             |
| `POST /api/code/{id}/fork`               | Create an owned copy from the public document.                                                                                                      |
| `GET /api/work/status`                   | Current user's small `has_work` flag for sidebar navigation.                                                                                        |

Pagination orders by descending immutable notebook ID. A cursor uses `id < previous-last-id`, so newly created notebooks cannot shift later pages or cause duplicates. Refresh to see newly added entries. The legacy notebook listing remains available for compatibility; the new browser lists do not use it.

## Create code from a competition

After joining, use **New notebook** on the competition Code tab. **Save notebook** preserves a private working copy in Your work. Saving or forking does not list it in competition Code. **Use existing code** also opens an editor; it no longer links a notebook directly. Closing an unsaved temporary editor still discards the draft.

Use **Save & Commit** to save and queue an immutable snapshot. Choose the prediction CSV filename (default `submission.csv`). The backend starts a fresh Python kernel in a new directory in the owner's existing notebook container, supplies `test.csv` and attached catalog inputs, and runs code cells in order. The directory is retained in the owner's durable workspace. The notebook can read `os.environ['ARENA_TEST_DATA']` and write `os.environ['ARENA_SUBMISSION_FILE']`.

Arena validates the generated `id,prediction` CSV against the competition's IDs and calculates RMSE using answers that remain in the API database. Only after successful execution and scoring does one transaction store the public snapshot and its generated outputs, add a leaderboard submission, and associate the notebook with competition Code. Missing output, Python errors, invalid predictions, runtime failures, or timeouts leave a new fork private; a failed later commit preserves the previous published version. Saving later edits also preserves that version.

Commits require ownership, competition membership, and an open deadline. Direct competition linking and generic publication of competition notebooks cannot bypass commits. Cells have a 120-second execution limit; a job has a 15-minute limit including runtime startup. Prediction CSVs are limited to 1 MB. This local runner uses a fresh kernel in the user's container; it is not a separate hardened competition execution service.

`notebook_working_copies` stores saved snapshots, privacy, and fork context. `notebook_commits` stores durable queued/running/succeeded/failed jobs, snapshots, scores, and errors. The API's single local worker processes queued jobs; a server restart marks interrupted running jobs failed for explicit retry. `POST /api/code/{id}/commits` queues a saved snapshot; `GET /api/code/{id}/commits/latest` reports its status. Old automatically linked competition forks are moved back to private work during the additive startup migration; curator sample notebooks remain listed.

The published code viewer has Notebook, Input, Output, Logs, and Comments tabs.
Input lists published dataset references. Output shows saved cell results; Logs shows
saved stdout, stderr, and errors, not live runtime or infrastructure logs. Notebook
retains the heading outline. Comments are stored in `notebook_comments` in the
platform database, read in pages of 50, and accept up to 10,000 characters. Anyone
can read them; signed-in users can post and delete their own comments. Deleting
the notebook removes its comments.

Notebook comments, discussion comments, and competition discussion posts support
one level of replies plus Like, Helpful, and Celebrate reactions. Discussion
posts also have reactions alongside their existing conversation. Reply and
reaction records are persisted in `content_replies` and `content_reactions` in
the platform database. Each user can apply each reaction once and remove it.
Reply lists load 50 at a time; authors can delete their own replies. Anonymous
visitors can read conversations but must sign in to reply or react.

Use a separate fork for a different competition. A notebook already assigned or
published to one competition cannot replace another competition's evaluated
snapshot through a commit to a different test set.
