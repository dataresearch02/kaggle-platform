import csv
import io
import math


def score_csv(content: bytes, solution: dict, metric: str = "RMSE") -> float:
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        if reader.fieldnames != ["id", "prediction"]:
            raise ValueError("CSV must have exactly these columns: id,prediction")
        predictions = {}
        for row in reader:
            if None in row or row.get("id") in predictions:
                raise ValueError("Duplicate IDs or malformed CSV rows")
            value = float(row["prediction"])
            if not math.isfinite(value) or abs(value) > 1e12:
                raise ValueError(
                    "Predictions must be finite and between -1e12 and 1e12"
                )
            predictions[row["id"]] = value
        if predictions.keys() != solution.keys():
            raise ValueError("Submission IDs must exactly match the sample submission")
        if not solution:
            raise ValueError("Evaluation answers cannot be empty")
        if metric == "MAE":
            return sum(abs(predictions[k] - v) for k, v in solution.items()) / len(
                solution
            )
        if metric == "Accuracy":
            return sum(predictions[k] == v for k, v in solution.items()) / len(solution)
        if metric == "LogLoss":
            if any(v not in (0, 1) for v in solution.values()) or any(
                p < 0 or p > 1 for p in predictions.values()
            ):
                raise ValueError(
                    "Binary log loss requires labels 0/1 and probabilities between 0 and 1"
                )
            return -sum(
                v * math.log(max(1e-15, predictions[k]))
                + (1 - v) * math.log(max(1e-15, 1 - predictions[k]))
                for k, v in solution.items()
            ) / len(solution)
        if metric != "RMSE":
            raise ValueError("Unsupported evaluation metric")
        return math.sqrt(
            sum((predictions[k] - v) ** 2 for k, v in solution.items()) / len(solution)
        )
    except (UnicodeError, TypeError, KeyError, csv.Error) as exc:
        raise ValueError("Upload a valid UTF-8 CSV with id,prediction columns") from exc
