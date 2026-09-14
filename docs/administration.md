# Administration

Arena has three roles, two account states, a small set of site settings, community reports with moderation, and an audit log. Everything is enforced by the API; the web UI only hides controls a user cannot use.

## Roles and account status

| Role | Can do |
| --- | --- |
| `user` (default) | Everything a signed-in member could do before: publish datasets, code, models and discussions, join competitions, report content. |
| `host` | Also create competitions and CSV benchmarks while `competition_creation` is `hosts`. |
| `admin` | Everything, plus the administration area. Admins can edit, delete and moderate anyone's datasets, notebooks/code, models, competitions, discussion topics, comments and replies, pin and lock topics in any scope, manage forums and recalculate progression. Private notebooks and datasets stay private; admins see hidden public content. |

`status` is `active` or `suspended`. A suspended account keeps its content, but sign-in, cookie sessions and API tokens are rejected with `This account is suspended. Contact an administrator for help.` Suspended browsers see public pages as an anonymous visitor. Reactivating the account makes existing sessions and tokens work again; use **Revoke sessions** or **Reset password** to invalidate them.

`/api/auth/me` (and the login/register responses) include `role`, `status`, `can_create_competitions` and `has_password` (false for accounts created by Keycloak sign-in). Public profiles include `role`.

Keycloak (OpenID Connect) sign-in, account linking and group-based roles are described in [authentication.md](authentication.md).

## Bootstrap administrators

There is no default administrator. Create the first one in either of two ways:

- **Environment:** set `ARENA_ADMIN_USERNAMES` to a comma-separated list of existing usernames (case-insensitive). At every API start they are promoted to `admin`. Unknown names are logged and skipped; removing a name does not demote the user.
- **CLI:** inside the API container, run

  ```bash
  python -m app.admin_cli promote <username>              # admin
  python -m app.admin_cli promote <username> --role host  # host
  python -m app.admin_cli demote <username>               # back to user
  python -m app.admin_cli suspend <username>
  python -m app.admin_cli activate <username>
  ```

  The CLI applies pending migrations first, so it also works before the API has started on an upgraded database.

Both methods write audit entries with the system as actor. An administrator cannot change their own role or status in the UI or API; ask another administrator or use the CLI.

## Administration area

Administrators get **Administration** in the account menu, which opens `#admin` with these tabs:

- **Users:** search by username, filter by role and status, change roles, suspend or activate, **Reset password** (generates a strong 24-character temporary password shown once, and revokes all of the user's sessions and API tokens) and **Revoke sessions** (sessions only).
- **Reports:** open, resolved or all reports, with the reporter, reason, the reported item's owner and a link to open it. Hide, unhide or delete the item, and resolve the report with an optional note.
- **Hidden content:** everything currently hidden, with unhide and delete.
- **Community:** create, rename, describe, reorder and archive forums, and **Recalculate progression** to rebuild every user's medals and tiers from source data ([community](community.md)).
- **Audit log:** newest first, filterable by actor (a username or `system`) and by action prefix such as `user.` or `content.hide`.
- **Storage:** per-user storage of dataset and model files, largest first, with per-user quota overrides ([datasets](datasets.md#storage-quotas)).
- **Settings:** the site settings below, with an announcement preview.

## Site settings

Stored in the `site_settings` table as JSON values. Missing rows use the defaults.

| Key | Default | Effect |
| --- | --- | --- |
| `registration_open` | `true` | When `false`, `POST /api/auth/register` returns 403 and the UI hides registration. First Keycloak sign-in still creates accounts. |
| `local_login_enabled` | `true` | When `false`, username and password sign-in is refused for everyone except administrators (break-glass access). Existing sessions keep working. This is intended for installations that use Keycloak sign-in: the sign-in dialog then shows only the Keycloak button, and administrators use `#login?local=1`. Keycloak sign-in is not affected. |
| `competition_creation` | `hosts` | `hosts`: only `host` and `admin` users may create competitions and CSV benchmarks. `everyone`: any active member may. Enforced on `POST /api/competitions` and `POST /api/benchmarks`. |
| `announcement` | empty | Markdown shown to every visitor as a dismissible banner. Dismissal is remembered per browser until the text changes. |
| `storage_quota_gib` | `20` | Default storage per user for dataset and model files and unfinished uploads. `PUT /api/admin/users/{id}/storage-quota {quota_gib}` overrides it for one user (`null` restores the default). |

`GET /api/site` returns the public subset (`registration_open`, `local_login_enabled`, `announcement`) plus `oidc_enabled` and `oidc_label` from the deployment configuration. `GET/PUT /api/admin/settings` reads and partially updates all settings.

**Upgrade note:** existing members lose the ability to create competitions until they are made hosts or the setting is changed to `everyone`.

## Reports and moderation

Any signed-in member can report an item they can see (not their own) with `POST /api/reports {kind, id, reason}`. A member can have only one open report per item. Kinds:

| Kind | Item | `id` |
| --- | --- | --- |
| `competition-post` | Discussion topic (competition, forum, dataset or model) | topic id |
| `reply` | Comment on a topic, reply to a comment, or reply to a notebook comment | reply id |
| `code` | Notebook/code | notebook id |
| `notebook-comment` | Comment on a notebook | comment id |
| `dataset` | Dataset | dataset id |
| `model` | Model card | model id |
| `profile` | Public profile | user id |

The UI shows **Report** on discussion topics and comments, replies, code pages, notebook comments, dataset and model pages, and public profiles. Administrators see **Hide/Unhide** and **Delete** in the same places.

**Hiding** (`PUT /api/admin/moderation/{kind}/{id} {hidden, reason}`; a reason is required to hide) sets the migrated `hidden` and `hidden_reason` columns. Hidden items are filtered on the server from every list, detail, download, search, input picker and discussion feed for everyone except the owner and administrators. The owner sees a "Hidden by a moderator" notice with the reason. A hidden profile returns 404 to other visitors.

Hiding also removes the item from search, activity feeds, rankings, medal counts and notification links, and a hidden topic's comments stop counting toward discussion medals.

**Deleting** (`DELETE /api/admin/moderation/{kind}/{id}`) removes the item permanently and resolves its open reports. Resolving a report, directly or by deleting the item, notifies the reporter in-app. Datasets, code and models are removed through the same path as **Your work** deletion, including files and dependent records; cleanup jobs run in the owner's workspace. Topics and comments are deleted with their replies and reactions. Deleting a profile clears its details and photo but keeps the account.

## Audit log

`audit_log` rows have `actor_id` (null for the system), `action`, `target_kind`, `target_id`, a JSON `detail` and `created_at`. `GET /api/admin/audit?actor=&action=&offset=&limit=` lists them. Temporary passwords are never recorded.

| Action | Recorded when |
| --- | --- |
| `user.role`, `user.status` | Role or status changed by an admin, the CLI, `ARENA_ADMIN_USERNAMES` or Keycloak group sync (`detail.from`, `detail.to`, `detail.source`, e.g. `oidc_groups`) |
| `user.sso_create` | An account was created by a first Keycloak sign-in (system actor; issuer, subject, `preferred_username`) |
| `user.identity_link`, `user.identity_unlink` | A user linked or unlinked a Keycloak identity |
| `user.password_reset`, `user.sessions_revoked` | Admin credential actions, with revoked counts |
| `settings.update` | Changed settings with old and new values |
| `user.storage_quota` | A per-user storage quota override was set or cleared (`detail.from_bytes`, `detail.to_bytes`; null is the site default) |
| `version.publish`, `version.delete`, `variation.create`, `variation.delete`, `model.card` | An administrator changed versions, variations or the card of another user's dataset or model |
| `content.hide`, `content.unhide`, `content.delete` | Moderation, including admin deletion of another user's work |
| `content.update` | An admin edits another user's work title or description, or another user's topic, comment or reply |
| `report.resolve` | A report is resolved, with the note |
| `forum.create`, `forum.update`, `forum.reorder` | Forum management (title changes, description, archive state, order) |
| `topic.lock`, `topic.unlock` | An administrator locks or unlocks a topic |
| `progression.recalculate` | The progression cache is rebuilt, with the number of users |
| `competition.create`, `competition.delete` | Any competition or CSV benchmark creation or deletion |
| `competition.settings`, `competition.rules`, `competition.solution`, `competition.rescore` | Host changes to the timeline, limits, metric, rules, answers, and rescoring ([competitions](competitions.md)) |
| `competition.disqualify`, `competition.reinstate`, `competition.finalize` | Disqualifying or reinstating a user or team, and storing final ranks and medals (the system is the actor for automatic finalization) |

## Pagination

Catalog lists keep their JSON array responses and accept `offset` and `limit` (at most 100; larger values are capped). The total number of matches is returned in the `X-Total-Count` header. This applies to competitions, CSV benchmarks, datasets, models, notebooks, courses, the legacy discussions alias, competition discussion topics, `/api/competitions/{id}/leaderboard`, submission history, notifications, search, activity feeds, follower lists and rankings. `GET /api/code` keeps its cursor response and adds `X-Total-Count` (with `sort=votes` it pages by `offset` and returns `next_offset`); `GET /api/competition-discussions` keeps its object response and accepts `limit`. Admin lists use the same parameters and header.

## Schema migrations

`Base.metadata.create_all` creates missing tables but never changes existing ones. `app/migrations.py` runs at startup right after `create_all` and before seeding. It keeps a `schema_migrations` table (`id`, `applied_at`) and an ordered list of idempotent functions that add missing columns using the SQLAlchemy inspector, so existing data is preserved and reruns are no-ops. The DDL works on SQLite and PostgreSQL.

| Id | Change |
| --- | --- |
| `0001_user_role_status` | `users.role` (default `user`), `users.status` (default `active`) |
| `0002_moderation_hidden` | `hidden` and `hidden_reason` on `datasets`, `notebooks`, `model_cards`, `competition_posts`, `content_replies`, `notebook_comments` and `user_profiles` |
| `0003_competition_solution_usage` | `competitions.solution_usage`: private per-id answer usage (`Public`/`Private`) kept for future public/private leaderboards |
| `0004_session_auth_method` | `sessions.auth_method` (default `password`; `oidc` for Keycloak sessions, used for single sign-out) |
| `0005_competition_rules_acceptance` … `0007_submission_private_scores` | Competition rules, timeline, limits and private scores ([competitions](competitions.md)) |
| `0008_community_columns` | Nullable `competition_posts.competition_id` (SQLite rebuilds the table) with `scope`/`scope_id`, `edited_at`/`deleted_at` on topics, replies and notebook comments, `competition_topic_settings.locked` |
| `0009_legacy_discussions_to_forum` | Default forums; legacy discussions and comments copied into General |
| `0010_community_backfill` | Topic likes copied into votes; topic authors watch their topics |
| `0011_course_authoring`, `0012_gpu_allocation_lock` | Course authoring columns ([learn](learn.md)) and the GPU allocation lock row ([compute](compute.md)) |
| `0013_resource_versions_schema` | `model_cards.card`; on PostgreSQL `datasets.size` and `artifact_versions.size` become `BIGINT` |
| `0014_resource_versions_backfill` | Existing datasets and models become version 1 (models gain a `default` variation) without moving files ([datasets](datasets.md#upgrading-existing-data)) |

New tables (`schema_migrations`, `site_settings`, `content_reports`, `audit_log`, `user_identities`, `oidc_login_attempts`, and the community tables listed in [community](community.md)) are created by `create_all`. Migrations that change data are idempotent, like the column migrations. To add a column, append a new migration to `MIGRATIONS`; never edit or reorder applied ones. Run a single API process while migrations apply.

## Offline practice competitions

At startup Arena imports four practice competitions from `apps/api/app/practice_data/` (breast cancer diagnosis, wine cultivar, diabetes progression and handwritten digits, all prepared from scikit-learn bundled datasets). Each creates a public dataset (train, test and sample submission files with license and citation) and a public competition owned by the internal `arena` user, with an overview, data files, no deadline and local scoring of `id,prediction` submissions. A `sample_imports` receipt per pack (`practice-<slug>-v1`) prevents duplicates on restart, even if an administrator later deletes the content. Set `ARENA_IMPORT_PRACTICE=false` to skip the import.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `ARENA_ADMIN_USERNAMES` | empty | Comma-separated existing usernames promoted to `admin` at startup |
| `ARENA_IMPORT_PRACTICE` | `true` | Import the offline practice competitions at startup |
| `UPLOAD_CHUNK_BYTES`, `UPLOAD_MAX_FILE_BYTES`, `UPLOAD_MAX_ACTIVE_SESSIONS`, `UPLOAD_SESSION_TTL_HOURS`, `UPLOAD_DIR`, `JOB_INPUT_MAX_BYTES` | 8 MiB, 100 GiB, 8, 24, `$DATA_DIR/upload-sessions`, 20 GiB | Chunked uploads and job input staging; see [datasets](datasets.md#uploads) |
| `ARENA_OIDC_ISSUER`, `ARENA_OIDC_CLIENT_ID`, `ARENA_OIDC_CLIENT_SECRET` | empty | Keycloak sign-in; enabled only when all three are set. See [authentication.md](authentication.md) |
| `ARENA_OIDC_CA_FILE`, `ARENA_PUBLIC_URL`, `ARENA_OIDC_LABEL` | empty / request URL / `Sign in with Keycloak` | Keycloak TLS CA bundle, public base URL for redirects, button text |
| `ARENA_OIDC_ADMIN_GROUPS`, `ARENA_OIDC_HOST_GROUPS` | empty | Comma-separated Keycloak groups mapped to `admin`/`host` at each Keycloak sign-in |
