"""Copied into the disposable CPU container; never imported by the API."""

import contextlib
import io
import json
import math
import time
import traceback
import secrets
from pathlib import Path


class BoundedLog(io.TextIOBase):
    def __init__(self):
        self.text = ""

    def write(self, value):
        self.text += value[: max(0, 50000 - len(self.text))]
        return len(value)


class Model:
    def __init__(self, info):
        self.info = info
        if info.get("provider_id"):
            self.predict = self.remote
            self.outputs = []
            return
        source = info["source"]
        scope = {"__name__": "arena_benchmark_model"}
        exec(compile(source, "model.py", "exec"), scope)
        self.predict = scope["predict"]
        self.outputs = []

    def remote(self, prompt):
        root = Path("/work/inference")
        root.mkdir(exist_ok=True)
        token = secrets.token_hex(16)
        request = root / f"{token}.request.json"
        temporary = root / f"{token}.tmp"
        temporary.write_text(
            json.dumps({"model_version_id": self.info["version_id"], "prompt": prompt})
        )
        temporary.rename(request)
        response = root / f"{token}.response.json"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if response.exists():
                data = json.loads(response.read_text())
                if data.get("error"):
                    raise ValueError(data["error"])
                return data["output"]
            time.sleep(0.1)
        raise TimeoutError("Model inference request timed out")

    def prompt(self, value):
        result = self.predict(value)
        rendered = json.loads(json.dumps(result, default=str, allow_nan=False))
        if len(json.dumps(rendered)) > 10000:
            raise ValueError("Model output exceeds 10,000 characters")
        if len(self.outputs) >= 100:
            raise ValueError("At most 100 model calls per case")
        self.outputs.append({"input": str(value)[:10000], "output": rendered})
        return result

    __call__ = prompt


def evaluate(snapshot):
    results = []
    logs = BoundedLog()
    with contextlib.redirect_stdout(logs), contextlib.redirect_stderr(logs):
        for model_info in snapshot["models"]:
            for task in snapshot["tasks"]:
                started = time.monotonic()
                row = {
                    "model_version_id": model_info["version_id"],
                    "task_version_id": task["version_id"],
                    "model": model_info["title"],
                    "task": task["title"],
                    "status": "succeeded",
                    "score": None,
                    "cases": [],
                    "error": "",
                }
                try:
                    # Each task/model pair gets fresh model state.
                    model = Model(model_info)
                    scope = {"__name__": "arena_benchmark_task"}
                    exec(compile(task["source"], "task.py", "exec"), scope)
                    for index, case in enumerate(task["cases"]):
                        model.outputs = []
                        tick = time.monotonic()
                        score = None
                        error = ""
                        status = "succeeded"
                        try:
                            value = scope["evaluate"](model, case)
                            if isinstance(value, dict):
                                value = value["score"]
                            if isinstance(value, (tuple, list)) and len(value) == 2:
                                value = value[0] / value[1]
                            if (
                                not isinstance(value, (int, float, bool))
                                or not math.isfinite(float(value))
                                or not 0 <= value <= 1
                            ):
                                raise ValueError(
                                    "Return bool, a 0–1 score, {'score': 0–1}, or (passed, total)"
                                )
                            score = float(value)
                        except AssertionError as exc:
                            score, error = 0.0, str(exc)[:2000]
                        except Exception as exc:
                            status, error = (
                                "failed",
                                f"{type(exc).__name__}: {exc}"[:2000],
                            )
                        row["cases"].append(
                            {
                                "index": index,
                                "input": case,
                                "score": score,
                                "status": status,
                                "error": error,
                                "outputs": model.outputs,
                                "duration_ms": round(
                                    (time.monotonic() - tick) * 1000, 2
                                ),
                            }
                        )
                    if any(c["status"] != "succeeded" for c in row["cases"]):
                        row["status"], row["error"] = (
                            "failed",
                            "One or more evaluation cases failed",
                        )
                    else:
                        row["score"] = sum(c["score"] for c in row["cases"]) / len(
                            row["cases"]
                        )
                except Exception as exc:
                    row["status"], row["error"] = (
                        "failed",
                        f"{type(exc).__name__}: {exc}"[:2000],
                    )
                    traceback.print_exc()
                row["duration_ms"] = round((time.monotonic() - started) * 1000, 2)
                results.append(row)
    return {"results": results, "logs": logs.text}


if __name__ == "__main__":
    snapshot = json.loads(Path("/work/snapshot.json").read_text())
    result = evaluate(snapshot)
    data = json.dumps(result, allow_nan=False)
    if len(data.encode()) > 10 * 1024 * 1024:
        raise ValueError("Benchmark results exceed 10 MB; reduce cases or model output")
    Path("/work/results.json").write_text(data)
