"""CPU gradient boosting: validation, early stopping, model saving and reloading.

Run from an Arena notebook: %run /opt/arena/examples/xgboost_training.py
This uses generated classification data, not Titanic's hidden test answers.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import xgboost as xgb
from sklearn.datasets import make_classification
from sklearn.model_selection import train_test_split


def train(output_dir="models/xgboost"):
    seed = 42
    features, labels = make_classification(
        n_samples=800, n_features=12, n_informative=8, random_state=seed
    )
    x_train, x_valid, y_train, y_valid = train_test_split(
        features, labels, test_size=0.2, stratify=labels, random_state=seed
    )
    model = xgb.XGBClassifier(
        n_estimators=150,
        max_depth=4,
        learning_rate=0.08,
        tree_method="hist",
        device="cpu",
        n_jobs=2,
        random_state=seed,
        eval_metric="logloss",
        early_stopping_rounds=15,
    )
    model.fit(x_train, y_train, eval_set=[(x_valid, y_valid)], verbose=False)
    probabilities = model.predict_proba(x_valid)[:, 1]
    accuracy = float(np.mean((probabilities >= 0.5) == y_valid))
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    model.save_model(output / "model.ubj")
    restored = xgb.XGBClassifier(n_jobs=2)
    restored.load_model(output / "model.ubj")
    np.testing.assert_allclose(probabilities, restored.predict_proba(x_valid)[:, 1])
    metrics = {
        "framework": "xgboost",
        "version": xgb.__version__,
        "device": "cpu",
        "seed": seed,
        "validation_accuracy": accuracy,
        "best_iteration": model.best_iteration,
        "history": model.evals_result(),
        "reload_verified": True,
    }
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2))
    np.savetxt(
        output / "validation_predictions.csv",
        np.column_stack((y_valid, probabilities)),
        delimiter=",",
        header="actual,probability",
        comments="",
    )
    print(f"XGBoost validation accuracy: {accuracy:.3f}; model reload verified.")
    print(f"Artifacts saved in {output.resolve()}")
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="models/xgboost")
    args = parser.parse_args()
    train(args.output_dir)
