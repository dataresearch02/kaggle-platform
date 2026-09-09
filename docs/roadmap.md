# Feature roadmap

The objective is coverage of Kaggle's major product areas. This roadmap distinguishes working local features from future platform capabilities.

| Area         | Implemented so far                                                                                                                                                                               | Remaining work                                                                                                                 |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| Accounts     | Registration, login/logout, persistent sessions                                                                                                                                                  | Email verification/recovery, OAuth, profiles, roles, organizations, rate limits                                                |
| Datasets     | Public CSV upload/download, metadata, licenses, tags, preview, title search                                                                                                                      | Object storage, versioning, larger formats, private access, collaborators, data APIs                                           |
| Competitions | Seeded challenge, join, CSV submissions, RMSE validation, best-score leaderboard, submission history                                                                                             | Organizer CRUD, artifact pipeline, metric registry, rules acceptance, deadlines UI, teams, private leaderboard, limits, awards |
| Notebooks    | Public templates, embedded JupyterLab via JupyterHub, Arena sign-in, per-user DockerSpawner sessions, multi-cell editing/execution, saved outputs, persistent working copies, start/stop, export | Revisions, automatic dataset mounting, collaboration, working-copy publishing, per-user domains, idle cleanup                  |
| Training     | Interactive scientific Python experiments in per-user CPU notebook containers with resource limits                                                                                               | Durable background jobs, stronger hostile-workload isolation, GPU scheduling, usage quotas, checkpoints, cancellation          |
| Models       | Public reference cards, framework/license metadata, reference links                                                                                                                              | Artifact upload/versioning, model provenance, inference, evaluations                                                           |
| Learning     | Seeded courses, code examples, per-user lesson completion                                                                                                                                        | Course authoring, exercises, grading, assessments, certificates                                                                |
| Community    | Discussion topics and replies                                                                                                                                                                    | Votes, follows, notifications, moderation, reporting, reputation                                                               |
| Discovery    | Overview counts and title search                                                                                                                                                                 | Pagination, ranked search, tags/facets, activity feeds, recommendations                                                        |
| Operations   | Compose, health checks, persistent volumes, API tests, frontend build                                                                                                                            | Migrations, CI/CD, observability, backups, role-based admin, security testing                                                  |

## Milestone 2 — durable data and administration

Introduce Alembic migrations and repeatable database upgrades, an organizer/admin role, competition CRUD with stored artifacts, S3-compatible dataset storage and versioning, private/public visibility and authorization, paginated APIs, account recovery, and rate limits. Exit criterion: an organizer can publish a new challenge and another user can complete it without code or database changes.

## Milestone 3 — managed execution and training

Implement durable job states and a separate worker service. Start with a fixed CPU training template to validate logs, output artifacts, resource/time limits, cancellation and failure recovery. Interactive notebook sessions now exist through JupyterHub; add the network/domain isolation, lifecycle policies and quotas required for untrusted workloads. Add GPU pools and quotas after the CPU path is reliable. Exit criterion: a user can train and save a model entirely in the platform; one user's job cannot access another user's data or platform credentials.

## Milestone 4 — competition integrity and model lifecycle

Support metric plugins, evaluation workers, public/private splits, daily submission limits, teams, rules acceptance, audit events, model registry artifacts and reproducible versions. Exit criterion: run a complete hosted competition with private final scoring and immutable submission provenance.

## Milestone 5 — learning and community at scale

Add authoring and graded exercises, profiles, reputation, votes, notifications, moderation, search indexing and collaboration. Complete responsive/accessibility audits and end-to-end regression coverage. Exit criterion: administrators can operate the community, publish learning content and handle abuse without direct database edits.

## Milestone 6 — production operations

Establish HTTPS and managed secrets, migrations and rollback, CI image scanning/digest updates, object-storage backups and restore tests, metrics/tracing, compute cost controls, load testing, disaster recovery and deployment manifests for the chosen cloud. Validate privacy, retention and upload licensing rules for the intended audience before opening registration publicly.
