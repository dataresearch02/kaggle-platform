# Competitions

This page describes how a hosted competition runs in Arena: rules, timeline,
public and private leaderboards, submission limits, final submission selection,
metrics, host tools, finalization and medals. Everything runs offline; scoring is
pure Python in the API (`apps/api/app/scoring.py`).

## Lifecycle

1. **Create.** A host or administrator (see [administration](administration.md)
   for the creation policy) uploads a public test CSV and a private answer CSV,
   chooses a metric, and optionally a public fraction, daily limit and rules.
2. **Join.** Participants read the rules in the join dialog and accept them. Arena
   stores the acceptance time and rules revision on the entry.
3. **Compete.** Between the start and the end, participants upload predictions or
   commit notebooks. Each submission is scored on the public and the private rows;
   only the public score is shown while the competition runs.
4. **Select.** Participants (team-wide for teams) choose up to the final
   submission limit for private scoring.
5. **End and finalize.** After the end the private leaderboard is published. The
   first request after the end (or the host's **Finalize now**) stores final ranks
   and medals.

Practice competitions, ongoing imports and CSV benchmarks have no deadline. They
have no timeline limits, are never finalized and award no medals.

## Rules

Hosts write rules in Markdown (at creation or in **Host → Rules**). Imported
competitions also show their imported rules text. Every competition also lists the
rules Arena enforces (submission format, limits, timeline and scoring).

- `POST /api/competitions/{id}/join` requires `{"accept_rules": true}`. An optional
  `rules_revision` must match the current revision, so a participant cannot accept
  rules they have not seen. Posting again as a member accepts the current revision.
- A host saving rules with **Material change** increments `rules_revision`
  (`PUT /api/competitions/{id}/rules`, audited as `competition.rules`). Members
  must accept again before submitting or committing code (HTTP 409 until they do);
  the UI shows a banner and the same dialog. Editorial changes keep the revision.
- `GET /api/competitions/{id}/membership` returns the accepted revision and
  `needs_rules_acceptance`.
- Upgrading marks every existing entry as having accepted revision 1 at the time
  of the migration.

## Timeline

| Field                   | Stored in                              | Enforced                                                       |
| ----------------------- | -------------------------------------- | -------------------------------------------------------------- |
| Start                   | `competition_overviews.starts_at`      | No submissions or notebook commits before it                   |
| Entry deadline          | `competitions.entry_deadline`          | No new entries, team creation or team joining after it         |
| Team merger deadline    | `competitions.merger_deadline`         | No team creation, joining or leaving after it                  |
| End (final submissions) | `competitions.deadline`                | No submissions, commits, joining, team changes or final selection after it |

Empty entry and merger deadlines default to the end. Deadlines must fall between
the start and the end. All checks are server-side (`competition_policy.py`); a
notebook commit that finishes after the end fails. Hosts edit the timeline in
**Host → Timeline, limits and metric** (`PUT /api/competitions/{id}/host/settings`)
or the overview editor (start and end). Moving the end back into the future clears
stored final results. The overview page shows the timeline.

Arena has no separate team merge operation: joining an existing team is the
merge, so it follows both deadlines.

## Public and private leaderboards

Answer rows are split into **Public** and **Private**:

- An answer CSV may have a third `Usage` column (`id,prediction,Usage`) with
  `Public` or `Private` per row.
- Without it, the host may give a public fraction (0–1). Rows are ordered by the
  SHA-256 of their id and the first `round(n × fraction)` rows are public, so the
  assignment is deterministic and does not depend on row order.
- Practice competitions store the split from their `solution.csv`.
- Without both kinds of rows, every row is public.

Every CSV submission and notebook commit is validated against all ids and scored
twice. `submissions.score` holds the public score (all rows without a split), so
existing clients keep working, and `submissions.private_score` holds the private
score. The original predictions are kept compressed in `submission_predictions` so
the host can rescore.

Visibility:

- The public leaderboard (`GET /api/competitions/{id}/leaderboard`) shows each
  entry's best public score while the competition runs and afterwards.
- The private leaderboard (`?board=private`) is available to everyone after the
  end. Hosts and administrators can preview it earlier; others receive 403.
- Private scores appear in submission history only after the end, or for hosts.
  Submission responses, notebook commit results, team views, the competition
  payload and exports for participants never contain private scores, answers or
  the row split.

Submissions created before the upgrade had no stored predictions: their score is
kept as the public score and their private score stays empty, so they do not rank
on a split private leaderboard. **Rescore all submissions** recomputes every
submission with stored predictions.

## Daily submission limits

`competitions.max_daily_submissions` defaults to 5 (20 for practice competitions
and CSV benchmarks). The count is per team when the submitter belongs to a team,
otherwise per participant, per UTC day. Scored CSV submissions and notebook commits
count, and queued or running commits count until they finish. The limit is checked
before scoring or queuing (HTTP 429); uploads rejected by validation and failed or
cancelled commits do not count. The Submissions tab and the commit dialog show the
remaining allowance from `GET /membership`.

## Final submission selection

Participants tick up to `max_final_submissions` (default 2) submissions in the
Submissions tab (`PUT /api/competitions/{id}/submissions/{submission}/final` with
`{"selected": true|false}`). Selections are shared by the whole team and lock at
the end. If an entry has no selection, its best public submissions, up to the
limit, are used. The private leaderboard ranks each team or solo participant by
the best private score among those final submissions (or the public score without
a split); ties go to the earlier submission.

## Metrics

Choose the metric when creating a competition or in **Host → Timeline, limits and
metric**. The UI takes the label and direction from `GET /api/metrics`. Submissions
must have exactly the columns `id,prediction` with one row per answer id; errors name
missing, duplicate or unknown ids and invalid values. Numeric values must be finite
and within ±1e12.

| Name       | Label                    | Better | Formula                                                                     | Predictions / answers                               |
| ---------- | ------------------------ | ------ | --------------------------------------------------------------------------- | --------------------------------------------------- |
| `RMSE`     | RMSE                     | Lower  | √(mean((y − p)²))                                                           | Numbers                                             |
| `MSE`      | MSE                      | Lower  | mean((y − p)²)                                                              | Numbers                                             |
| `MAE`      | MAE                      | Lower  | mean(\|y − p\|)                                                             | Numbers                                             |
| `RMSLE`    | RMSLE                    | Lower  | √(mean((ln(1 + y) − ln(1 + p))²))                                           | Non-negative numbers                                |
| `R2`       | R²                       | Higher | 1 − Σ(y − p)² / Σ(y − ȳ)²; constant answers give 1 if exact, else 0         | Numbers                                             |
| `MAPE`     | MAPE                     | Lower  | mean(\|(y − p) / y\|), a fraction                                           | Numbers; answers nonzero                            |
| `Accuracy` | Accuracy                 | Higher | mean(p = y)                                                                 | Numeric class labels                                |
| `LogLoss`  | Log loss                 | Lower  | −mean(y ln p + (1 − y) ln(1 − p)), p clipped at 1e-15                       | Probabilities in [0, 1]; answers 0 or 1             |
| `F1`       | F1                       | Higher | 2TP / (2TP + FP + FN), positive label 1; 0 when undefined                   | 0 or 1                                              |
| `MacroF1`  | Macro F1                 | Higher | mean over classes in answers and predictions of per-class F1                | Numeric class labels                                |
| `AUC`      | ROC-AUC                  | Higher | (Σ ranks of positives − P(P + 1)/2) / (P·N); tied scores share mean ranks   | Any numeric scores; answers 0 or 1, both classes in each subset |
| `QWK`      | Quadratic weighted kappa | Higher | 1 − Σ w·O / Σ w·E, w = (i − j)² / (N − 1)², E from the rating histograms     | Integer ratings                                     |
| `MAP@K`    | MAP@K                    | Higher | mean over rows of Σₖ P(k)·rel(k) / min(\|relevant\|, K); K defaults to 5    | Space-separated labels, best first; answers nonempty |

RMSE, MAE, Accuracy and binary LogLoss produce exactly the same values as before
the registry. Changing the metric (or K) validates the stored answers for the new
metric and rescores submissions with stored predictions.

## Host tools

The **Host** tab is shown to users who can manage the competition (its creator or
an administrator; legacy competitions without a creator are administrator-only).

| Tool                                  | API                                                       | Audit action               |
| ------------------------------------- | --------------------------------------------------------- | -------------------------- |
| Status, settings and counts           | `GET /api/competitions/{id}/host`                         |                            |
| Timeline, limits, metric and K        | `PUT /api/competitions/{id}/host/settings`                | `competition.settings`     |
| Rules and material changes            | `PUT /api/competitions/{id}/rules`                        | `competition.rules`        |
| Replace answers (same ids), new split | `PUT /api/competitions/{id}/host/solution` (multipart)    | `competition.solution`     |
| Rescore all submissions               | `POST /api/competitions/{id}/host/rescore`                | `competition.rescore`      |
| All submissions (filter, paginate)    | `GET /api/competitions/{id}/host/submissions?q=&final=&team_id=&user_id=` |            |
| Leaderboard CSV export                | `GET /api/competitions/{id}/host/leaderboard.csv?board=public\|private` |              |
| Disqualify a user or team             | `POST /api/competitions/{id}/host/disqualifications`      | `competition.disqualify`   |
| Reinstate                             | `DELETE /api/competitions/{id}/host/disqualifications/{row}` | `competition.reinstate`  |
| Finalize now (after the end)          | `POST /api/competitions/{id}/host/finalize`               | `competition.finalize`     |

Disqualification needs a reason. It applies to a team or to a participant's solo
entry, removes the entry from both leaderboards and exports, and excludes it from
final ranks and medals. After the end, the tab shows a shake-up table comparing
each entry's public and private rank; the private leaderboard shows the same change
column to everyone.

## Finalization and medals

When a competition with a deadline has ended, the first request to the competition,
its leaderboard, membership, host tools or a participant's profile results runs
finalization; **Finalize now** reruns it. Finalization computes the private
leaderboard, replaces the rows in `competition_results` and sets
`competitions.finalized_at`. It is idempotent, and rescoring, disqualification or
reinstatement after the end recompute the results.

`competition_results` has one row per user: competition, rank, number of ranked
teams, medal, score and team. Team placements and medals are stored for every
member of the team. The table is intended for a later tiers and rankings feature.

Medals follow Kaggle's thresholds, where a solo participant counts as a team and
percentages round down:

| Ranked teams | Gold                   | Silver   | Bronze   |
| ------------ | ---------------------- | -------- | -------- |
| 0–99         | Top 10%                | Top 20%  | Top 40%  |
| 100–249      | Top 10                 | Top 20%  | Top 40%  |
| 250–999      | Top 10 + 0.2% of teams | Top 50   | Top 100  |
| 1000+        | Top 10 + 0.2% of teams | Top 5%   | Top 10%  |

Practice competitions and CSV benchmarks award no medals, and disqualified entries
are not ranked. Final rank and medals appear on the private leaderboard and in the
**Competition results** section of public profiles
(`GET /api/profiles/{username}/competitions`).

## Upgrading existing installations

Startup migrations `0005_competition_rules_acceptance`,
`0006_competition_timeline_limits` and `0007_submission_private_scores` add the new
columns; `create_all` creates `submission_predictions`,
`competition_disqualifications` and `competition_results`. Existing users,
competitions, entries, teams, submissions and notebook commits are preserved:

- Entries are marked as accepting rules revision 1.
- Competitions without a deadline get a daily limit of 20; others get 5. Every
  competition allows 2 final submissions.
- Existing scores become public scores; private scores stay empty until the
  predictions are available to rescore, which is not the case for submissions made
  before the upgrade.
- Competitions that already ended are finalized on first access.
