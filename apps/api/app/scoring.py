"""Metric registry and strict, pure-Python scoring of `id,prediction` CSV files.

Each metric declares its label, whether higher or lower scores are better, how
prediction and answer values are validated, and how a score is computed. Scores
are computed separately on the public and private leaderboard rows.
"""

import csv
import hashlib
import io
import math
from dataclasses import dataclass
from typing import Callable

LIMIT = 1e12
USAGES = ("Public", "Private")


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError("must be a number") from None
    if not math.isfinite(result) or abs(result) > LIMIT:
        raise ValueError("must be finite and between -1e12 and 1e12")
    return result


def probability(value):
    result = number(value)
    if not 0 <= result <= 1:
        raise ValueError("must be a probability between 0 and 1")
    return result


def binary(value):
    result = number(value)
    if result not in (0, 1):
        raise ValueError("must be 0 or 1")
    return result


def integer(value):
    result = number(value)
    if not result.is_integer():
        raise ValueError("must be an integer rating")
    return result


def non_negative(value):
    result = number(value)
    if result < 0:
        raise ValueError("must be zero or greater")
    return result


def non_zero(value):
    result = number(value)
    if result == 0:
        raise ValueError("must not be zero")
    return result


def labels(value):
    """Space-separated labels. Stored float answers such as 3.0 become "3"."""
    if isinstance(value, list):
        return list(dict.fromkeys(str(token) for token in value))
    if isinstance(value, float):
        value = str(int(value)) if value.is_integer() else repr(value)
    if value is None:
        raise ValueError("must be space-separated labels")
    tokens = str(value).split()
    return list(dict.fromkeys(tokens))


def ranked_labels(value):
    """Predicted labels in order; repeats keep their positions but score once."""
    if value is None:
        raise ValueError("must be space-separated labels")
    return str(value).split()


def answer_labels(value):
    result = labels(value)
    if not result:
        raise ValueError("must list at least one relevant label")
    return result


def mse(pairs, k):
    return sum((p - a) ** 2 for a, p in pairs) / len(pairs)


def rmse(pairs, k):
    return math.sqrt(mse(pairs, k))


def mae(pairs, k):
    return sum(abs(p - a) for a, p in pairs) / len(pairs)


def rmsle(pairs, k):
    return math.sqrt(
        sum((math.log1p(p) - math.log1p(a)) ** 2 for a, p in pairs) / len(pairs)
    )


def r2(pairs, k):
    mean = sum(a for a, _ in pairs) / len(pairs)
    residual = sum((a - p) ** 2 for a, p in pairs)
    total = sum((a - mean) ** 2 for a, _ in pairs)
    if total == 0:  # Constant answers: perfect predictions score 1, others 0.
        return 1.0 if residual == 0 else 0.0
    return 1 - residual / total


def mape(pairs, k):
    return sum(abs((a - p) / a) for a, p in pairs) / len(pairs)


def accuracy(pairs, k):
    return sum(p == a for a, p in pairs) / len(pairs)


def log_loss(pairs, k):
    return -sum(
        a * math.log(max(1e-15, p)) + (1 - a) * math.log(max(1e-15, 1 - p))
        for a, p in pairs
    ) / len(pairs)


def f1_for(pairs, label):
    tp = sum(a == label and p == label for a, p in pairs)
    fp = sum(a != label and p == label for a, p in pairs)
    fn = sum(a == label and p != label for a, p in pairs)
    return 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0.0


def f1(pairs, k):
    return f1_for(pairs, 1)


def macro_f1(pairs, k):
    classes = sorted({a for a, _ in pairs} | {p for _, p in pairs})
    return sum(f1_for(pairs, label) for label in classes) / len(classes)


def roc_auc(pairs, k):
    positives = sum(a == 1 for a, _ in pairs)
    negatives = len(pairs) - positives
    if not positives or not negatives:
        raise ValueError(
            "ROC-AUC needs at least one positive and one negative answer in every "
            "leaderboard subset"
        )
    order = sorted(range(len(pairs)), key=lambda index: pairs[index][1])
    ranks = [0.0] * len(pairs)
    start = 0
    while start < len(order):
        end = start
        while (
            end + 1 < len(order) and pairs[order[end + 1]][1] == pairs[order[start]][1]
        ):
            end += 1
        for position in range(start, end + 1):  # Tied scores share their mean rank.
            ranks[order[position]] = (start + end) / 2 + 1
        start = end + 1
    positive_ranks = sum(rank for rank, (a, _) in zip(ranks, pairs) if a == 1)
    return (positive_ranks - positives * (positives + 1) / 2) / (positives * negatives)


def quadratic_weighted_kappa(pairs, k):
    values = [int(value) for pair in pairs for value in pair]
    low, size = min(values), max(values) - min(values) + 1
    if size == 1:
        return 1.0
    observed = [[0] * size for _ in range(size)]
    for a, p in pairs:
        observed[int(a) - low][int(p) - low] += 1
    actual = [sum(row) for row in observed]
    predicted = [sum(row[j] for row in observed) for j in range(size)]
    weight = lambda i, j: (i - j) ** 2 / (size - 1) ** 2
    disagreement = sum(
        weight(i, j) * observed[i][j] for i in range(size) for j in range(size)
    )
    expected = sum(
        weight(i, j) * actual[i] * predicted[j] / len(pairs)
        for i in range(size)
        for j in range(size)
    )
    return 1 - disagreement / expected if expected else 1.0


def map_at_k(pairs, k):
    total = 0.0
    for actual, predicted in pairs:
        hits, score, seen = 0, 0.0, set()
        for index, label in enumerate(predicted[:k]):
            if label in actual and label not in seen:
                hits += 1
                score += hits / (index + 1)
            seen.add(label)
        total += score / min(len(actual), k)
    return total / len(pairs)


@dataclass(frozen=True)
class Metric:
    name: str
    label: str
    title: str
    direction: str  # "higher" or "lower" is better.
    prediction: Callable
    answer: Callable
    compute: Callable
    formula: str
    input: str
    uses_k: bool = False

    @property
    def higher_is_better(self):
        return self.direction == "higher"

    def display(self, k=None):
        return f"MAP@{k or DEFAULT_K}" if self.uses_k else self.label

    def describe(self, k=None):
        return {
            "name": self.name,
            "label": self.display(k),
            "title": self.title,
            "direction": self.direction,
            "formula": self.formula,
            "input": self.input,
            "uses_k": self.uses_k,
        }


DEFAULT_K = 5
METRICS = {
    metric.name: metric
    for metric in (
        Metric(
            "RMSE",
            "RMSE",
            "Root mean squared error",
            "lower",
            number,
            number,
            rmse,
            "sqrt(mean((y - p)^2))",
            "Numeric predictions",
        ),
        Metric(
            "MSE",
            "MSE",
            "Mean squared error",
            "lower",
            number,
            number,
            mse,
            "mean((y - p)^2)",
            "Numeric predictions",
        ),
        Metric(
            "MAE",
            "MAE",
            "Mean absolute error",
            "lower",
            number,
            number,
            mae,
            "mean(|y - p|)",
            "Numeric predictions",
        ),
        Metric(
            "RMSLE",
            "RMSLE",
            "Root mean squared logarithmic error",
            "lower",
            non_negative,
            non_negative,
            rmsle,
            "sqrt(mean((ln(1 + y) - ln(1 + p))^2))",
            "Non-negative numeric predictions",
        ),
        Metric(
            "R2",
            "R²",
            "Coefficient of determination",
            "higher",
            number,
            number,
            r2,
            "1 - sum((y - p)^2) / sum((y - mean(y))^2)",
            "Numeric predictions",
        ),
        Metric(
            "MAPE",
            "MAPE",
            "Mean absolute percentage error (fraction)",
            "lower",
            number,
            non_zero,
            mape,
            "mean(|(y - p) / y|)",
            "Numeric predictions; answers must be nonzero",
        ),
        Metric(
            "Accuracy",
            "Accuracy",
            "Classification accuracy",
            "higher",
            number,
            number,
            accuracy,
            "mean(p == y)",
            "Numeric class labels",
        ),
        Metric(
            "LogLoss",
            "Log loss",
            "Binary log loss",
            "lower",
            probability,
            binary,
            log_loss,
            "-mean(y ln(p) + (1 - y) ln(1 - p)), p clipped to 1e-15",
            "Probability of class 1 between 0 and 1",
        ),
        Metric(
            "F1",
            "F1",
            "Binary F1 score (positive label 1)",
            "higher",
            binary,
            binary,
            f1,
            "2 TP / (2 TP + FP + FN)",
            "Binary labels 0 or 1",
        ),
        Metric(
            "MacroF1",
            "Macro F1",
            "Macro-averaged F1 score",
            "higher",
            number,
            number,
            macro_f1,
            "mean over classes c of 2 TP_c / (2 TP_c + FP_c + FN_c)",
            "Numeric class labels",
        ),
        Metric(
            "AUC",
            "ROC-AUC",
            "Area under the ROC curve (binary)",
            "higher",
            number,
            binary,
            roc_auc,
            "(sum of positive ranks - P(P + 1)/2) / (P N), tied scores share mean ranks",
            "Numeric scores; higher means more likely class 1",
        ),
        Metric(
            "QWK",
            "Quadratic weighted kappa",
            "Quadratic weighted kappa",
            "higher",
            integer,
            integer,
            quadratic_weighted_kappa,
            "1 - sum(w O) / sum(w E), w_ij = (i - j)^2 / (N - 1)^2",
            "Integer ratings",
        ),
        Metric(
            "MAP@K",
            "MAP@K",
            "Mean average precision at K",
            "higher",
            ranked_labels,
            answer_labels,
            map_at_k,
            "mean over rows of sum_k P(k) rel(k) / min(|relevant|, K)",
            "Space-separated labels, best first; only the first K count",
            uses_k=True,
        ),
    )
}


def get_metric(name):
    metric = METRICS.get(name)
    if metric is None:
        raise ValueError("Unsupported evaluation metric")
    return metric


def metric_k(metric, k):
    return (k or DEFAULT_K) if metric.uses_k else None


def examples(ids):
    ids = sorted(ids)
    return ", ".join(ids[:3]) + (" …" if len(ids) > 3 else "")


def read_csv(content, allow_usage=False):
    """Rows of (id, value, usage) from an id,prediction[,Usage] CSV."""
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        header = reader.fieldnames or []
        usage = allow_usage and header == ["id", "prediction", "Usage"]
        if header != ["id", "prediction"] and not usage:
            raise ValueError(
                "CSV must have exactly these columns: id,prediction"
                + (" (optionally followed by Usage)" if allow_usage else "")
            )
        rows, seen = [], set()
        for line, row in enumerate(reader, start=2):
            if None in row or None in row.values():
                raise ValueError(f"Malformed CSV row on line {line}")
            if row["id"] in seen:
                raise ValueError(f"Duplicate id {row['id']!r} on line {line}")
            seen.add(row["id"])
            rows.append((row["id"], row["prediction"], row.get("Usage")))
        return rows
    except (UnicodeError, TypeError, KeyError, csv.Error) as exc:
        raise ValueError("Upload a valid UTF-8 CSV with id,prediction columns") from exc


def match_ids(found, expected, noun="Submission"):
    missing, extra = set(expected) - set(found), set(found) - set(expected)
    if missing:
        raise ValueError(
            f"{noun} is missing {len(missing)} required id(s): {examples(missing)}"
        )
    if extra:
        raise ValueError(f"{noun} has {len(extra)} unknown id(s): {examples(extra)}")


def convert(values, check, what):
    result = {}
    for key, value in values.items():
        try:
            result[key] = check(value)
        except ValueError as exc:
            raise ValueError(f"{what} for id {key!r} {exc}") from None
    return result


def read_predictions(content, solution, metric):
    rows = read_csv(content)
    match_ids([row[0] for row in rows], solution)
    return convert(
        {key: value for key, value, _ in rows}, metric.prediction, "Prediction"
    )


def read_answers(content, ids, metric):
    """Validate a host answer CSV. Returns (answers, usage or None)."""
    rows = read_csv(content, allow_usage=True)
    match_ids([row[0] for row in rows], ids, "Answer file")
    if not rows:
        raise ValueError("Evaluation answers cannot be empty")
    answers = convert({key: value for key, value, _ in rows}, metric.answer, "Answer")
    if rows[0][2] is None:
        return answers, None
    usage = {}
    for key, _, value in rows:
        normalized = (value or "").strip().capitalize()
        if normalized not in USAGES:
            raise ValueError(f"Usage for id {key!r} must be Public or Private")
        usage[key] = normalized
    return answers, usage


def storable(answers):
    """JSON-ready answers: label lists are stored space-separated."""
    return {
        key: " ".join(value) if isinstance(value, list) else value
        for key, value in answers.items()
    }


def normalize_answers(solution, metric):
    """Stored answers converted for a (possibly different) metric."""
    if not solution:
        raise ValueError("Evaluation answers cannot be empty")
    return convert(solution, metric.answer, "Stored answer")


def assign_usage(ids, fraction):
    """Deterministic Public/Private split: rows ordered by the SHA-256 of their id."""
    ids = list(ids)
    if len(ids) < 2:
        return {}
    count = min(max(round(len(ids) * fraction), 1), len(ids) - 1)
    ordered = sorted(ids, key=lambda key: (hashlib.sha256(key.encode()).digest(), key))
    public = set(ordered[:count])
    return {key: "Public" if key in public else "Private" for key in ids}


def split(solution, usage):
    """(public ids, private ids); private is None without a real two-way split."""
    usage = usage or {}
    private = [key for key in solution if usage.get(key) == "Private"]
    public = [key for key in solution if usage.get(key) != "Private"]
    if not private or not public:
        return list(solution), None
    return public, private


def validate_split(solution, usage, metric, k=None):
    """Answers must be scorable on each subset, e.g. ROC-AUC needs both classes."""
    answers = normalize_answers(solution, metric)
    for ids in split(answers, usage):
        if ids:
            metric.compute(
                [(answers[key], answers[key]) for key in ids], metric_k(metric, k)
            )


def score_rows(answers, predictions, ids, metric, k):
    return metric.compute(
        [(answers[key], predictions[key]) for key in ids], metric_k(metric, k)
    )


def evaluate(content, solution, metric_name="RMSE", usage=None, k=None):
    """Validate a submission and return (public score, private score or None)."""
    metric = get_metric(metric_name)
    if not solution:
        raise ValueError("Evaluation answers cannot be empty")
    predictions = read_predictions(content, solution, metric)
    answers = normalize_answers(solution, metric)
    public, private = split(answers, usage)
    return (
        score_rows(answers, predictions, public, metric, k),
        score_rows(answers, predictions, private, metric, k) if private else None,
    )


def score_csv(content: bytes, solution: dict, metric: str = "RMSE", k=None) -> float:
    """Score every answer row, ignoring any leaderboard split."""
    return evaluate(content, solution, metric, None, k)[0]
