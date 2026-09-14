# Community and progression

This page describes Arena's community features: site forums and resource
discussions, editing and topic moderation, @mentions, notifications, votes,
follows, the activity feed, site search, and the medal, tier and ranking rules.
Everything runs offline: there is no email, and notifications are in-app only.

Every new surface uses the same visibility rules as the content's own page
(`apps/api/app/community.py`). Private notebooks and datasets, moderator-hidden
content and restricted profiles never appear in feeds, search, notifications,
vote endpoints, follower lists, rankings or mention links for people who cannot
see them.

## Forums and discussion scopes

A discussion topic is a `competition_posts` row with a **scope**:

| Scope         | `scope_id`   | Where it appears                                    | Pin and lock                        |
| ------------- | ------------ | --------------------------------------------------- | ----------------------------------- |
| `competition` | competition  | Competition **Discussion** tab                      | Competition host, administrators    |
| `forum`       | forum        | `#discussions/forums/<id>`                          | Administrators                      |
| `dataset`     | dataset      | **Discussion** section of `#datasets/<id>`          | Dataset owner, administrators       |
| `model`       | model card   | **Discussion** section of `#models/<id>`            | Model owner, administrators         |

`competition_id` stays set for competition topics (older clients keep working)
and is null for the other scopes. Comments and replies are `content_replies`
rows in every scope, so all topics share one feed, thread view, pinning, locks,
bookmarks, watches, votes, reactions and moderation. Topics on a dataset or model
are visible exactly when the dataset or model is: a private dataset's topics are
visible only to its owner, people it is shared with and administrators.

**Forums** are managed by administrators in **Administration → Community**
(create, rename, edit the description, reorder, archive). Six default forums are
created once: General, Getting Started, Questions & Answers, Datasets, Notebooks
and Product Feedback. Archived forums disappear from the forum list but their
topics remain readable; new topics and comments are refused (HTTP 409).

`#discussions` shows the forums and a feed of topics across forums, competitions,
datasets and models with search, All/Owned/Bookmarks/Watching filters, a
without-comments filter and sorting by recent comments, **Hot** (topics active in
the last 14 days first, then comments plus votes), newest topics, most votes and
most comments. Forum and resource topics open at `#discussions/<id>`; competition
topics keep `#competitions/<id>/discussion/<topic>`. Image uploads are available
in competition discussions only; other scopes support Markdown text and links.

| API                                                             | Purpose                                            |
| --------------------------------------------------------------- | -------------------------------------------------- |
| `GET /api/forums[?include_archived=true]`, `GET /api/forums/{id or slug}` | Forums with topic counts                 |
| `POST /api/forums/{id or slug}/topics`                          | New forum topic                                    |
| `POST /api/competition-discussions` `{scope, scope_id, title, body}` | New topic in any scope                        |
| `GET /api/competition-discussions?scope=&scope_id=&competition_id=&q=&filter=&sort=&unanswered=&offset=&limit=` | Topic feed (X-Total-Count) |
| `POST /api/admin/forums`, `PUT /api/admin/forums/{id}`, `PUT /api/admin/forums/order` | Forum management (audited `forum.*`) |

### Legacy discussions

The earlier `discussions`/`comments` tables had no UI. Migration
`0009_legacy_discussions_to_forum` copies each legacy discussion into the General
forum and each comment onto the new topic, moves replies and reactions to the new
ids, and records every copy in `legacy_discussion_map`, so rerunning copies
nothing twice. The legacy rows are kept. `GET/POST /api/discussions` and
`GET/POST /api/discussions/{id}/comments` are now deprecated aliases that list and
create General forum topics and their comments; the engagement kinds `discussion`
and `discussion-comment` are aliases for `competition-post` and
`competition-comment`.

## Editing, deletion and topic moderation

- Authors edit their topics (`PUT /api/competition-discussions/{id}`), topic
  comments and replies (`PUT /api/engagement/{kind}/{id}/replies/{reply}`) and
  notebook comments (`PUT /api/code/{id}/comments/{comment}`). The previous text
  is stored in `content_revisions` and the item shows "edited" with the time.
  Administrators may also edit (audited as `content.update`) and see the history
  in the thread or with `GET /api/admin/revisions/{kind}/{id}`.
- Authors delete their topics, comments and replies. An item that still has
  comments or replies becomes a placeholder ("deleted by its author"): the text is
  cleared (a revision keeps it for administrators), votes are removed and no new
  replies are accepted. Items without replies are deleted outright. Administrator
  deletion through moderation removes the item and its replies as before.
- Hosts and administrators pin topics and **lock** them
  (`PUT /api/competition-discussions/{id}/lock {"enabled": true}`). Locked topics
  stay readable and editable but refuse new comments and replies (HTTP 409).

## Mentions

`@username` (3–40 letters, digits or underscores, not inside inline code or code
blocks, not part of an e-mail address or URL) in topics, comments, replies and
notebook comments becomes a link to `#profile/<username>`, but only for usernames
that exist: API responses include a `mentions` list of existing mentioned users.
A mentioned user is notified once per item, and only if they can see the item; an
edit notifies only users who were not mentioned before. At most 20 mentions per
item are processed.

## Notifications

Notifications are stored in `notifications` (recipient, kind, actor, target kind
and id, url, detail, group key, count, read time, created time) and shown under
the bell in the header with the unread count. The list merges them with the
existing service notices (`service_notices`), newest first.

| Kind      | Sent to                                     | When                                                                  |
| --------- | ------------------------------------------- | --------------------------------------------------------------------- |
| `reply`   | Topic author / comment author                | Someone comments on your topic or replies to your comment             |
| `mention` | Mentioned user                               | You are mentioned in content you can see                              |
| `watch`   | Watchers of the topic                        | A new comment or reply in a topic you watch                           |
| `comment` | Notebook, dataset or model owner             | A comment on your notebook, or a new topic on your dataset or model   |
| `vote`    | Content owner                                | Upvotes on your notebook, dataset, model, topic or comment; one notification per item per day counts the voters |
| `fork`    | Notebook owner                               | Someone forks your notebook (the link goes to your notebook)          |
| `follow`  | Followed user                                | Someone follows you                                                   |
| `result`  | Every ranked participant                     | Final rank and medal after finalization; refreshed if results change  |
| `report`  | Reporter                                     | A report you made is resolved (also when the item is deleted)         |

Topic authors watch their topics automatically; anyone can watch or unwatch with
the eye button (`PUT /api/competition-discussions/{id}/watch`). One event creates
at most one notification per person (mention before reply before comment before
watch), never for the person who acted. Each kind can be switched off in
**Account → Settings → Notifications** (`notification_preferences`; a missing row
means enabled). Service notices are always shown.

Links and titles are recomputed whenever the list is read. If an item was later
hidden, deleted or made private, the notification stays but shows no title or
link.

| API                                                  | Purpose                                           |
| ---------------------------------------------------- | ------------------------------------------------- |
| `GET /api/notifications?offset=&limit=`              | Activity notifications and service notices (X-Total-Count) |
| `GET /api/notifications/unread-count`                | Unread activity notifications plus unread notices |
| `POST /api/notifications/{activity or service}/{id}/read`, `POST /api/notifications/read-all` | Mark read |
| `GET/PUT /api/account/notification-preferences`      | Per-kind preferences (browser sessions only)      |

The existing `/api/account/notifications` endpoints and the account drawer keep
working for service notices.

## Votes

`votes` holds one upvote per user per item (`PUT` to vote, `DELETE` to remove,
`GET` for the count, all at `/api/votes/{kind}/{id}`). Kinds are `code`,
`dataset`, `model`, `competition-post`, `reply` (topic comments and all replies)
and `notebook-comment`. Voting on your own content is refused (422), voting on
something you cannot see returns 404, and deleted placeholders cannot be voted on
(409). Removing an item removes its votes.

Lists and detail pages return `votes` and `voted`. Code (`GET /api/code?sort=votes`,
paged by `offset` with `next_offset`), datasets and models (`?sort=votes`) and the
topic feed (`sort=votes`) offer **Most votes**. Topic votes previously counted
"like" reactions; migration `0010_community_backfill` copied those likes into
votes (skipping authors' likes on their own topics). Reactions (like, helpful,
celebrate) remain separate and keep working.

## Follows and activity

`follows` stores who follows whom. `PUT/DELETE /api/profiles/{username}/follow`
follows or unfollows; you cannot follow yourself or a profile you cannot see, but
you can always unfollow. `GET /api/profiles/{username}/follows` returns the counts,
and `/followers` and `/following` return paginated lists. Users with a private
profile (or a moderator-hidden profile, for non-administrators) are left out of
lists and counts for everyone else.

The activity feed is derived from the source tables at request time, so it never
shows content after it is hidden or made private:

- a notebook published or republished (public, not hidden),
- a public dataset and a model card,
- a new topic whose scope is public and that is not hidden or deleted,
- a competition medal.

`GET /api/feed` (home page **Your feed**) shows this activity for people you follow
whose profiles are not restricted, plus your own. `GET /api/profiles/{username}/activity`
(profile **Activity** tab) shows one user's activity to anyone who can see the
profile. Both are paginated with X-Total-Count.

## Search

`GET /api/search?q=&type=&offset=&limit=` searches competitions (title and
description), datasets (title, description and tags), code (title and
description), models, topics (title and body), courses and users (username). Each
source applies its listing's visibility filter for the current user, so owners
find their own private items and nobody else does. Results are ordered by a
simple relevance score: 3 for an exact title or username match, 2 for a title or
username containing the words, 1 for a description or body match; then newest
first. `type` limits results to one kind; `GET /api/search/counts?q=` returns the
number of matches per type. The header search box opens `#search?q=…&type=…`,
which groups results by type with type filters.

## Medals, tiers and rankings

Progression has four categories. Only public, non-hidden, non-deleted content
counts, and self-votes are impossible.

### Medals

| Category    | Medal source                                                        | Bronze | Silver | Gold |
| ----------- | ------------------------------------------------------------------- | -----: | -----: | ---: |
| Competitions | Final results in `competition_results` ([competitions](competitions.md)) | — | — | — |
| Datasets    | Upvotes from other users on a public dataset                         | 5      | 20     | 50   |
| Notebooks   | Upvotes from other users on a public notebook                        | 5      | 20     | 50   |
| Discussions | Upvotes on each public topic, topic comment, reply or notebook comment | 1    | 5      | 10   |

An item holds only its highest medal. Comments and replies count when their topic
(or notebook) is public. A medal is lost if the item is hidden, deleted or made
private, or votes are removed.

### Tiers

Every registered user is a **Novice**. **Contributor** needs at least one scored
submission (competitions), public notebook (notebooks), public dataset
(datasets), or public topic, comment or reply (discussions). Higher tiers need
medals; a higher medal fills a requirement for a lower medal, and each medal fills
only one requirement. "1 gold + 2 silver" therefore means at least 1 gold and at
least 3 medals that are silver or gold.

| Category     | Expert        | Master                                  | Grandmaster                                     |
| ------------ | ------------- | --------------------------------------- | ----------------------------------------------- |
| Competitions | 2 bronze      | 1 gold + 2 silver                       | 5 gold, at least 1 of them solo (no team)       |
| Datasets     | 3 bronze      | 1 gold + 4 silver                       | 5 gold + 5 silver                               |
| Notebooks    | 5 bronze      | 10 silver                               | 15 gold                                         |
| Discussions  | 50 bronze     | 50 silver + 200 medals in total         | 50 gold + 500 medals in total                   |

"N bronze" means N medals of any kind; "N silver" means N silver or gold medals.
The overall tier is the highest category tier.

### Cache and rankings

`user_progression` stores, per user and category, the tier, gold, silver and bronze
counts and `achieved_at`: when the current medals were reached (the time of the
vote that crossed each medal threshold, or the finalization time). It is a cache:
`progression.compute` derives everything from source rows. Requests that change
votes, publication or dataset visibility, topics and comments, moderation,
submissions, competition finalization or deletion mark the affected users, and
their rows are recomputed just before the transaction commits. **Administration →
Community → Recalculate progression** (`POST /api/admin/progression/recalculate`,
audited as `progression.recalculate`) rebuilds the cache for everyone and gives the
same result. After an upgrade the cache is filled once at startup.

`#rankings/<category>` (`GET /api/rankings/{category}?offset=&limit=`) lists users
with at least one medal in the category, ordered by gold, then silver, then bronze,
then earliest `achieved_at`. Users with restricted profiles are not listed.
Profiles show the overall tier and each category's tier and medals
(`GET /api/profiles/{username}/progression`). Discussions, comments, follower lists
and competition leaderboards show a small badge for Contributor and above (solo
leaderboard entries only); restricted profiles get no badge.

## Upgrading existing installations

| Migration                            | Change                                                                                     |
| ------------------------------------ | ------------------------------------------------------------------------------------------ |
| `0008_community_columns`             | `competition_posts.competition_id` becomes nullable (SQLite rebuilds the table), adds `scope` (default `competition`), `scope_id` (backfilled from `competition_id`), `edited_at`, `deleted_at` and index `ix_competition_posts_scope`; `edited_at`/`deleted_at` on `content_replies` and `notebook_comments`; `competition_topic_settings.locked` |
| `0009_legacy_discussions_to_forum`   | Creates the default forums and copies legacy discussions and comments into General (idempotent through `legacy_discussion_map`) |
| `0010_community_backfill`            | Copies topic likes into `votes` (no self-votes) and makes topic authors watch their topics |

`create_all` creates `forums`, `legacy_discussion_map`, `content_revisions`,
`votes`, `topic_watches`, `notifications`, `notification_preferences`, `follows`
and `user_progression`. Existing topics, comments, reactions, pins and bookmarks
are kept with their ids; every data step can be rerun safely.
