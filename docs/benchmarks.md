# Arena benchmarks

Arena's task-based workflow follows the task/collection/model distinction in
[Kaggle's benchmark documentation](https://www.kaggle.com/docs/benchmarks).
A task defines a Python evaluation; a benchmark collects task versions and model
versions and compares their results. Existing CSV prediction benchmarks remain
available under **Benchmarks → CSV benchmarks** and their original API routes.

## Local workflow

1. Open **Benchmarks → Create task**. Define `evaluate(model, case)` and a JSON
   array of evaluation cases. Python and `.ipynb` imports are supported; notebook
   import extracts code cells. Return a boolean, a finite score from 0 to 1,
   `{"score": value}`, or `(passed, total)`. Assertion failures score zero;
   execution errors are recorded separately and do not become successful scores.
2. Register a model using `POST /api/benchmark-hub/assets/model` with a `title`, and Python `source`. For a local model, implement `predict(prompt)` in Python. The benchmark Create menu contains only benchmarks and tasks.
   The scientific runtime includes PyTorch, XGBoost, NumPy, pandas and scikit-learn.
   Local models can train or infer in their Python implementation. The default
   echo function is explicitly a workflow baseline, not a trained AI model.
3. Create a benchmark and select task/model versions. You can use your own private
   assets or reusable public ones. A public benchmark requires public assets.
4. Click **Run evaluation**. Open **Results** for history, task scores, per-case
   inputs and model outputs, latency, error messages and logs. The leaderboard
   supports JSON and CSV download.

A task can call `model.prompt(value)` multiple times. Local model inputs and
outputs can be JSON-serializable values. API provider inputs and outputs are text.
Cases may contain inline evaluation data; external dataset files and model weights
are not automatically mounted into benchmark containers.

Example task:

```python
def evaluate(model, case) -> bool:
    answer = model.prompt(case["prompt"])
    return str(answer).strip().lower() == case["expected"].lower()
```

Example cases:

```json
[{ "prompt": "Return only the capital of France.", "expected": "Paris" }]
```

The API is rooted at `/api/benchmark-hub`: `assets`, `collections`, `providers`,
`collections/{id}/runs`, `runs/{id}`, and `collections/{id}/leaderboard`.
Cookie authentication and existing scoped API-token authentication apply. Only
owners edit resources and launch/cancel runs; public benchmarks can be viewed
without signing in. Copy Link respects visibility and does not grant private access.

## Configuring API models

Arena accepts administrator-configured chat-completions endpoints. A local
[vLLM compatible server](https://docs.vllm.ai/en/latest/serving/openai_compatible_server/)
or a hosted service exposing that protocol can be used. This is not access to
Kaggle's model proxy, hosted models, or free API quotas.

Set these values in the local `.env` (never commit credentials):

```dotenv
BENCHMARK_PROVIDERS_JSON='[{"id":"my-model","label":"My model","model":"model-name","url":"https://provider.example/v1/chat/completions","key_env":"BENCHMARK_API_KEY","max_tokens":1024}]'
BENCHMARK_API_KEY=your-provider-key
```

For an unauthenticated local endpoint, omit `key_env`. Both `api` and
`evaluation-worker` receive the provider list; inference runs in the worker. Restart
those services after changing configuration, allowing active evaluations to finish
first. The model creation sidebar's **Execution** selector then lists providers.
Changing a provider's endpoint, model, or token limit requires saving a new model
version before another evaluation; credential rotation does not.

Only configured endpoints are contacted. Task containers do not receive keys or
network access: they exchange bounded inference requests with a worker broker.
Requests use `model`, one user `messages` entry, `temperature: 0`, and `max_tokens`;
responses must contain `choices[0].message.content`. Provider errors, missing
credentials, unsupported responses and timeouts become evaluation errors.
Provider calls may incur normal provider charges. Each run allows at most 128
brokered calls, with 45-second request timeouts and bounded output sizes.

## Reproducibility and persistence

- Task/model edits create immutable versions with source, cases and a SHA-256
  digest. Benchmarks pin versions explicitly; saving a new task does not silently
  change existing benchmarks.
- Each run stores a full version snapshot and a configuration fingerprint. The
  current leaderboard uses the latest completed matrix for that exact configuration;
  old results remain in history. Scores are averaged per task, then equally across
  tasks. A model needs every task to complete successfully before it receives a rank.
- Task/model source and cases, collection configuration, status, results and logs
  persist in PostgreSQL. Execution workspaces live at
  `${DATA_ROOT}/platform/evaluations/benchmark-<run-id>-<random>/` and contain
  `snapshot.json`, `runner.py`, `results.json` and any runtime-produced files.
  Normal container removal does not remove those files.
- A worker restart marks interrupted runs failed with an explicit retry message.
  Cancellation removes the disposable container and prevents late result writes.
- Team/user notebook publishing remains separate from benchmark model registration.
  Importing notebook source does not publish it as competition code.

## Local execution limits and scope

The initial local runner uses one concurrent benchmark job, offline non-root
containers, a read-only root filesystem, two CPU cores, 2 GB memory and a
five-minute whole-run timeout. Each owner can queue up to three jobs. Each run
supports 20 tasks, 10 models and up to 1,000 model/case evaluations, subject to
those execution limits. Source is limited to 100 KB per version and results to
10 MB per run. Run workspaces remain available for inspection; disk quotas and
automatic retention cleanup are not implemented yet.

This implements Arena's task-based evaluation workflow, not full compatibility
with `kaggle_benchmarks` decorators or Kaggle task files. Multimodal provider calls,
streaming, tool calling, hosted judge models, research compute grants, GPU runners,
and automatic model-weight downloads are not included. Python tasks can implement
custom scoring within the local runtime. Reproducibility still depends on task
code, package/runtime versions and the behavior of remote model providers.
