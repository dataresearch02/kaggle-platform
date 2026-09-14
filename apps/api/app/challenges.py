"""Validate public features and private answers before publishing a challenge."""

import csv
import io

from .scoring import read_answers


def validate_challenge(test_content, answer_content, metric):
    """Returns (test CSV text, answers, usage or None) for the chosen metric."""
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
        ids = []
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
            ids.append(row["id"])
        if not ids:
            raise ValueError("Test CSV must contain data rows")
        # Exact IDs, duplicate rows, value types and an optional Usage column.
        answers, usage = read_answers(answer_content, ids, metric)
        return test_text, {key: answers[key] for key in ids}, usage
    except (UnicodeError, csv.Error, TypeError, KeyError) as exc:
        raise ValueError("Upload valid UTF-8 test and answer CSV files") from exc
