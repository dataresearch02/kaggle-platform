import math

import pytest

from app.scoring import (
    METRICS,
    assign_usage,
    evaluate,
    get_metric,
    read_answers,
    score_csv,
    split,
)


def csv_of(values):
    return (
        "id,prediction\n" + "".join(f"{k},{v}\n" for k, v in values.items())
    ).encode()


def score(metric, answers, predictions, k=None):
    ids = [str(index) for index in range(len(answers))]
    return score_csv(
        csv_of(dict(zip(ids, predictions))), dict(zip(ids, answers)), metric, k
    )


@pytest.mark.parametrize(
    "metric,answers,predictions,expected",
    [
        # Errors 1, -2, 0 and 3.
        ("RMSE", [1, 2, 3, 4], [2, 0, 3, 7], math.sqrt(14 / 4)),
        ("MSE", [1, 2, 3, 4], [2, 0, 3, 7], 14 / 4),
        ("MAE", [1, 2, 3, 4], [2, 0, 3, 7], 6 / 4),
        # ln(1 + 0) vs ln(1 + e - 1): one squared log error of 1 over two rows.
        ("RMSLE", [0, 3], [math.e - 1, 3], math.sqrt(1 / 2)),
        # Mean 2; residual 1 + 0 + 1 = 2; total 1 + 0 + 1 = 2.
        ("R2", [1, 2, 3], [2, 2, 2], 0.0),
        ("R2", [1, 2, 3], [1, 2, 4], 1 - 1 / 2),
        ("R2", [5, 5], [5, 5], 1.0),
        ("R2", [5, 5], [4, 5], 0.0),
        # |(2 - 1)/2| = 0.5 and |(4 - 5)/4| = 0.25.
        ("MAPE", [2, 4], [1, 5], 0.375),
        ("Accuracy", [1, 0, 2, 2], [1, 1, 2, 0], 0.5),
        ("LogLoss", [1, 0], [0.5, 0.5], math.log(2)),
        ("LogLoss", [1, 0], [1, 0], 0.0),
        # TP 2, FP 1, FN 1: 4 / (4 + 1 + 1).
        ("F1", [1, 1, 1, 0, 0], [1, 1, 0, 1, 0], 4 / 6),
        ("F1", [0, 0], [0, 0], 0.0),
        # Class 0: TP1 FP0 FN1 -> 2/3; class 1: TP1 FP1 FN0 -> 2/3; class 2: 1.
        ("MacroF1", [0, 0, 1, 2], [0, 1, 1, 2], (2 / 3 + 2 / 3 + 1) / 3),
        # Pairs (pos, neg): 0.8>0.1, 0.8>0.4, 0.35<0.4, 0.35>0.1 -> 3 / 4.
        ("AUC", [0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8], 0.75),
        # A positive tied with a negative counts half: (1 + 0.5) / 2.
        ("AUC", [0, 1, 1], [0.5, 0.5, 0.9], 0.75),
        ("AUC", [1, 0], [0.2, 0.7], 0.0),
        ("QWK", [1, 2, 3], [1, 2, 3], 1.0),
        ("QWK", [1, 1], [1, 1], 1.0),
    ],
)
def test_metric_values(metric, answers, predictions, expected):
    assert score(metric, answers, predictions) == pytest.approx(expected)


def test_quadratic_weighted_kappa_hand_calculation():
    # Answers 0,1,2,2 and predictions 0,1,2,0 over ratings 0..2 (N = 3).
    # Weights w_ij = (i - j)^2 / 4; observed disagreement: w_20 = 1 for one row.
    # Histograms: answers [1, 1, 2], predictions [2, 1, 1]; E_ij = a_i p_j / 4.
    # sum w E = (w_01*1*1 + w_02*1*1 + w_10*1*2 + w_12*1*1 + w_20*2*2 + w_21*2*1) / 4
    #         = (0.25 + 1 + 0.5 + 0.25 + 4 + 0.5) / 4 = 6.5 / 4.
    expected = 1 - 1 / (6.5 / 4)
    assert score("QWK", [0, 1, 2, 2], [0, 1, 2, 0]) == pytest.approx(expected)


def test_map_at_k():
    answers = {"a": "1 2", "b": "3", "c": "4 5 6"}
    predictions = {"a": "1 9 2", "b": "9 3", "c": ""}
    # a: (1/1 + 2/3) / 2; b: (1/2) / 1; c: 0.
    expected = ((1 + 2 / 3) / 2 + 0.5 + 0) / 3
    assert score_csv(csv_of(predictions), answers, "MAP@K") == pytest.approx(expected)
    # With K = 1 only the first label counts: a: 1/1 / min(2, 1); b: 0; c: 0.
    assert score_csv(csv_of(predictions), answers, "MAP@K", 1) == pytest.approx(1 / 3)
    # Repeated labels are not counted twice.
    repeated = score_csv(csv_of({"a": "1 1 2"}), {"a": "1 2"}, "MAP@K")
    assert repeated == pytest.approx((1 + 2 / 3) / 2)


def test_legacy_metrics_are_unchanged():
    content = b"id,prediction\n7,230\n8,90.5\n9,301\n"
    answers = {"7": 240, "8": 100, "9": 300}
    errors = [230 - 240, 90.5 - 100, 301 - 300]
    assert score_csv(content, answers) == math.sqrt(sum(e**2 for e in errors) / 3)
    assert score_csv(content, answers, "MAE") == sum(abs(e) for e in errors) / 3
    assert score_csv(b"id,prediction\na,1\nb,0\n", {"a": 1, "b": 1}, "Accuracy") == 0.5


@pytest.mark.parametrize(
    "metric,content,message",
    [
        ("RMSE", b"id,prediction\n1,3\n", "missing 2 required id"),
        ("RMSE", b"id,prediction\n1,3\n2,4\n3,5\n4,1\n", "unknown id"),
        ("RMSE", b"id,prediction\n1,3\n1,4\n2,1\n3,1\n", "Duplicate id"),
        ("RMSE", b"id,prediction\n1,abc\n2,1\n3,1\n", "must be a number"),
        ("LogLoss", b"id,prediction\n1,1.5\n2,0\n3,1\n", "probability"),
        ("F1", b"id,prediction\n1,0.5\n2,0\n3,1\n", "must be 0 or 1"),
        ("QWK", b"id,prediction\n1,1.5\n2,0\n3,1\n", "integer"),
        ("RMSLE", b"id,prediction\n1,-1\n2,0\n3,1\n", "zero or greater"),
        ("RMSE", b"id,value\n1,1\n2,1\n3,1\n", "exactly these columns"),
    ],
)
def test_submission_validation_messages(metric, content, message):
    with pytest.raises(ValueError, match=message):
        score_csv(content, {"1": 1, "2": 0, "3": 1}, metric)


def test_registry_describes_every_metric():
    assert {
        "RMSE",
        "MSE",
        "MAE",
        "RMSLE",
        "R2",
        "MAPE",
        "Accuracy",
        "LogLoss",
        "F1",
        "MacroF1",
        "AUC",
        "QWK",
        "MAP@K",
    } == set(METRICS)
    for metric in METRICS.values():
        assert metric.direction in ("higher", "lower")
        assert metric.describe()["label"]
    assert get_metric("MAP@K").display(3) == "MAP@3"
    with pytest.raises(ValueError):
        get_metric("Unknown")


def test_public_and_private_subsets():
    answers = {"a": 1, "b": 2, "c": 3, "d": 4}
    usage = {"a": "Public", "b": "Public", "c": "Private", "d": "Private"}
    content = b"id,prediction\na,1\nb,4\nc,3\nd,4\n"
    public, private = evaluate(content, answers, "MAE", usage)
    assert (public, private) == (1.0, 0.0)
    # Without both kinds of rows everything is public.
    assert evaluate(content, answers, "MAE", {"a": "Private"})[1] is not None
    assert evaluate(content, answers, "MAE", {})[1] is None
    assert split(answers, {key: "Private" for key in answers}) == (list(answers), None)


def test_usage_column_and_deterministic_fraction():
    answers, usage = read_answers(
        b"id,prediction,Usage\na,1,Public\nb,0,private\n", ["a", "b"], get_metric("F1")
    )
    assert answers == {"a": 1.0, "b": 0.0} and usage == {"a": "Public", "b": "Private"}
    ids = [str(n) for n in range(100)]
    first = assign_usage(ids, 0.3)
    assert first == assign_usage(list(reversed(ids)), 0.3)
    assert list(first.values()).count("Public") == 30
    assert set(assign_usage(["x", "y"], 0.01).values()) == {"Public", "Private"}
    with pytest.raises(ValueError, match="Public or Private"):
        read_answers(b"id,prediction,Usage\na,1,Both\n", ["a"], get_metric("F1"))
    with pytest.raises(ValueError, match="positive and one negative"):
        evaluate(
            b"id,prediction\na,1\nb,0\n",
            {"a": 1, "b": 1},
            "AUC",
        )
