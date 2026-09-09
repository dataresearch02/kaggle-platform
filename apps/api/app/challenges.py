"""Validate public features and private answers before publishing a challenge."""

import csv
import io

from .scoring import score_csv


def validate_challenge(test_content, answer_content):
    try:
        test_text = test_content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(test_text))
        headers = reader.fieldnames or []
        if (
            "id" not in headers
            or len(headers) < 2
            or len(set(headers)) != len(headers)
            or any(not h.strip() for h in headers)
        ):
            raise ValueError(
                "Test CSV needs unique headers: id and at least one feature"
            )
        ids = set()
        for row in reader:
            if (
                None in row
                or None in row.values()
                or not row["id"].strip()
                or row["id"] in ids
            ):
                raise ValueError(
                    "Test CSV needs nonempty unique IDs and consistently sized rows"
                )
            ids.add(row["id"])
        if not ids:
            raise ValueError("Test CSV must contain data rows")
        # Reuse scoring validation for exact IDs, duplicate rows and finite bounds.
        score_csv(answer_content, dict.fromkeys(ids, 0))
        answers = csv.DictReader(io.StringIO(answer_content.decode("utf-8-sig")))
        solution = {row["id"]: float(row["prediction"]) for row in answers}
        return test_text, solution
    except (UnicodeError, csv.Error, TypeError, KeyError) as exc:
        raise ValueError("Upload valid UTF-8 test and answer CSV files") from exc
