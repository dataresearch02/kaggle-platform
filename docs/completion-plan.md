# Platform completion plan

The requested implementation covers the four priorities and the remaining
feature gaps in `logic-review.md`. Existing public examples stay public; new
content should become private by default. Each change needs server enforcement,
a usable UI, persistence, and workflow verification before it is complete.

- [x] Privacy: datasets and notebooks; explicit publication; sharing and revocation.
- [x] Version history: immutable notebook saves with restore; numbered dataset and model versions that notebooks pin or follow ([datasets](datasets.md), [models](models.md)).
- [x] Competition evaluation: selectable metrics; public/private scores; submission limits; final selection ([competitions](competitions.md)).
- [ ] Teams: team-owned submissions and leaderboard, membership rules and deadlines, shared daily limits and final selections are implemented; shared resources remain.
- [ ] Evaluation workers: independent job containers, durable queue, cancellation, recovery and limits.
- [x] Compute: CPU/GPU selection per session, run and attempt; availability checks; GPU usage tracking, weekly quotas and capacity ([compute](compute.md)).
- [x] Storage: multi-file versions, safe bounded previews and downloads, resumable chunked uploads, per-user quotas, dataset/model notebook attachments ([datasets](datasets.md)). Object storage is not used; files stay on the shared volume.
- [ ] Accounts: recovery and verification. Roles, suspension, reports, moderation and the audit log are implemented ([administration](administration.md)).
- [x] Community: forums, notifications, following, votes, activity feeds, search, profiles with medals, tiers and rankings ([community](community.md)).
- [x] Learning: course authoring, graded exercises, hints and certificates ([learn](learn.md)). Quizzes and timed assessments are not implemented.
- [ ] Automation: background Save & Run All and scheduled notebooks are implemented ([compute](compute.md)); supported API credentials beyond expiring account tokens remain.
- [ ] Operations: backup/restore verification, observability and deployment readiness. Additive startup schema migrations are implemented.

GPU execution needs GPU hardware and a configured container runtime; configuration
alone does not count as a verified GPU implementation. GPU selection, quotas and
capacity are implemented and covered by API tests with mocked Kubernetes and Hub
calls; execution on the target cluster's GPU still needs the acceptance run in
[the OpenShift GPU guide](openshift-gpu.md).

## Implemented in the local CPU increment

Notebook save history and restore UI; private dataset/notebook access and sharing;
a metric registry with public/private leaderboards, daily limits, final selection,
rules acceptance, timelines, host tools and medals; site forums, votes, mentions, notifications,
follows, activity feeds, site search, tiers and rankings; team-owned submission history and leaderboard;
a separate CPU evaluation worker with cancellation and restart recovery; numbered
dataset versions and model variations with versions, previews, chunked uploads and
storage quotas. Model URLs are optional.

The broader checklist remains open where features are only partially implemented.
See [learn](learn.md) and [compute](compute.md) for the Learn & compute milestone, and
[local CPU behavior and limits](local-cpu.md) for acceptance scope.
