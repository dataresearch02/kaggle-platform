# Platform completion plan

The requested implementation covers the four priorities and the remaining
feature gaps in `logic-review.md`. Existing public examples stay public; new
content should become private by default. Each change needs server enforcement,
a usable UI, persistence, and workflow verification before it is complete.

- [x] Privacy: datasets and notebooks; explicit publication; sharing and revocation.
- [ ] Version history: immutable notebook and dataset snapshots; restore and pinned inputs.
- [ ] Competition evaluation: selectable metrics; public/private scores; submission limits; final selection.
- [ ] Teams: team-owned submissions and leaderboard, membership rules and shared resources.
- [ ] Evaluation workers: independent job containers, durable queue, cancellation, recovery and limits.
- [ ] Compute: CPU/GPU configuration, availability checks and usage tracking.
- [ ] Storage: multiple files, artifact versions, safe previews/downloads, dataset/model attachments.
- [ ] Accounts: recovery, verification, roles and moderation.
- [ ] Community: notifications, following, profiles and reputation.
- [ ] Learning: graded exercises, hints and assessments.
- [ ] Automation: scheduled notebooks and supported API credentials.
- [ ] Operations: migrations, backup/restore verification, observability and deployment readiness.

GPU execution needs GPU hardware and a configured container runtime; configuration
alone does not count as a verified GPU implementation. OpenShift deployment stays
deferred until local container acceptance, as requested.

## Implemented in the local CPU increment

Notebook save history and restore UI; private dataset/notebook access and sharing;
RMSE/MAE/Accuracy/binary LogLoss; team-owned submission history and leaderboard;
a separate CPU evaluation worker with cancellation and restart recovery; immutable
supplemental dataset/model file versions and downloads. Model URLs are optional.

The broader checklist remains open where features are only partially implemented.
GPU execution is explicitly deferred, not counted as completed. See
[local CPU behavior and limits](local-cpu.md) for acceptance scope.
