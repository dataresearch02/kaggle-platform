# Main workflow review

Review date: 2026-09-10. Scope: the current local container product and the workflows
requested in this project. This is a functional review, not certification of
Kaggle feature parity or a production security audit.

## Outcome

The main local workflow is implemented: register, join a competition, inspect its
inputs, create or fork code, save private competition work, commit a snapshot,
execute it with test features, validate predictions, calculate RMSE, and publish
only the evaluated snapshot. Ownership, draft expiry, persistence and community
features have automated coverage.

Two publication issues, one mobile navigation issue and an interactive execution race were addressed in this review. A saved competition
draft could be submitted again without `competition_id`, causing the generic
save path to overwrite its evaluated publication. Repeated saves now check the
stored competition context and existing competition links before writing files
or publications. Missing or changed context returns HTTP 409. The regression test
failed before the change and passes after it; ordinary saves still preserve the
last evaluated public snapshot.

The legacy `/api/notebooks` and competition resource listings also returned
`Notebook.code`, which a save could update independently of the published
snapshot. They now serialize code from the publication when one exists; public
competition resources also enforce notebook visibility. The regression verifies
that anonymous callers cannot retrieve unevaluated edits through these routes.

On mobile, the open notebook side panel hides the main editor and its toolbar,
including the old panel toggle. The panel now has its own close button. Selecting
a table-of-contents heading also closes the panel on small screens so the target
heading is visible. An older runtime test was updated to account for owned code
opening directly in the editor.

A live sample run stalled awaiting output. Interactive execution sent code as
soon as the WebSocket opened, unlike the commit runner which first confirmed
both shell and IOPub readiness. The editor and commit runner now share the same
bounded handshake using a silent empty-code probe, avoiding execution before
output subscription readiness. The live audit found that the original kernel-info
probe did not reliably produce both replies. Retries resend only the empty probe,
never user code; the probe does not add execution history.

The multi-notebook sample test still exposed startup readiness failures after
that change. The scientific image was measured using 32 OpenBLAS threads per
kernel, while a user's container has a two-CPU allocation and a 256-PID limit.
The image now defaults OpenBLAS, OpenMP, MKL and NumExpr pools to two threads.
The rebuilt image reports two OpenBLAS threads. New containers use this default;
existing running notebooks were not interrupted. Resource exhaustion was a
suspected contributor. With the new defaults, the complete four-notebook sample
workflow passed in 23.4 seconds, including CSV downloads and actual scoring.
This resolves the reproduced workflow failure; it is not a general load test.

## Coverage and limits

| Area                          | Assessment                                                                                                                                                                                                                                     |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Accounts and ownership        | Authentication, private work visibility, owner-only updates/deletion and personal event filtering have API coverage.                                                                                                                           |
| Competition overview and data | Structured metadata, membership gates, documented file trees and previews are covered. Catalog datasets are public; linking one does not make its source private.                                                                              |
| General privacy controls      | Competition drafts and forks have private working copies. Saving a new notebook outside a competition currently publishes its initial snapshot, and uploaded catalog datasets are public. General private/public settings are not implemented. |
| Notebook lifecycle            | Temporary drafts expire/discard; saved competition work persists privately. Forks preserve published content and attribution.                                                                                                                  |
| Evaluation and publication    | Real container tests exercise execution, missing-output failure, scoring and publication. Later private edits preserve public outputs. The bypass described above is fixed.                                                                    |
| Submissions                   | CSV IDs and finite predictions are validated; scores and personal history persist. The scorer currently supports RMSE.                                                                                                                         |
| Teams                         | Creation, invite codes, membership, captain transfer and leaving persist. Scores remain individual; team score aggregation is not implemented.                                                                                                 |
| Discussion and comments       | Replies, reactions and ownership checks have API and browser coverage. Moderation workflows are not part of this review.                                                                                                                       |
| Models and benchmarks         | Models are reference cards. Benchmarks score prediction CSVs; they are not hardware timing or general model execution services.                                                                                                                |
| Active Events                 | Tracks queued/running notebook evaluations only. It does not yet track synchronous uploads, interactive kernels, or scheduled runs.                                                                                                            |
| Persistence                   | PostgreSQL, uploads, Hub state and notebook workspaces use host bind mounts. API/frontend recreation is checked separately below. Full backup restoration and host/disk failure recovery are not tested here.                                  |
| Runtime isolation             | Each user gets a container. Commits use a fresh kernel/directory inside that user's existing container, which the user can access. This does not provide a tamper-resistant, independent evaluation environment.                               |
| Deployment                    | Current single API worker/local Compose design is appropriate for local testing. Multi-replica scheduling, quotas/rate limits, and production operations need a separate readiness review.                                                     |

## Validation

- 92 API tests passed after the fix, including the new bypass regression.
- 12 browser tests passed for the main pages, ownership, submissions, teams,
  discussions, navigation and Active Events.
- Frontend production build passed (existing bundle-size warning remains).
- API/frontend container recreation preserved the checked database counts:
  56 users, 55 notebooks, 15 datasets and 3 competitions before and after.
  These counts include test-created records. The application health check passed.
- All seven live workflows passed across the final verification runs: publication
  and forking, private competition commits, competition draft creation, native
  execution/sanitization/restart, draft save/discard, mobile panel/console/inputs,
  and the four-notebook sample workflow. Six passed together; the sample test
  passed separately after the scientific thread-pool fix.
- The final readiness-probe adjustment also passed the 10 targeted editor/commit
  API tests. The full API suite had passed all 92 tests before that adjustment.
- API/web images and the scientific runtime image were rebuilt. Existing running
  notebook containers retain their previous thread settings until restarted.
