import csv
import io
import math


def score_csv(content: bytes, solution: dict) -> float:
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
        return math.sqrt(
            sum((predictions[k] - v) ** 2 for k, v in solution.items()) / len(solution)
        )
    except (UnicodeError, TypeError, KeyError, csv.Error) as exc:
        raise ValueError("Upload a valid UTF-8 CSV with id,prediction columns") from exc
