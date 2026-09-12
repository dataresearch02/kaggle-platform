"""CPU binary classification: train, validate, checkpoint and verify restored predictions.

Run from an Arena notebook: %run /opt/arena/examples/pytorch_training.py
Artifacts are saved relative to the notebook working directory.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from sklearn.datasets import make_classification
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from torch import nn


def train(output_dir="models/pytorch"):
    seed = 42
    torch.manual_seed(seed)
    torch.set_num_threads(2)
    features, labels = make_classification(
        n_samples=800, n_features=12, n_informative=8, random_state=seed
    )
    x_train, x_valid, y_train, y_valid = train_test_split(
        features, labels, test_size=0.2, stratify=labels, random_state=seed
    )
    scaler = StandardScaler().fit(x_train)
    train_tensor = torch.tensor(scaler.transform(x_train), dtype=torch.float32)
    valid_tensor = torch.tensor(scaler.transform(x_valid), dtype=torch.float32)
    targets = torch.tensor(y_train, dtype=torch.float32).reshape(-1, 1)

    def network():
        return nn.Sequential(nn.Linear(12, 32), nn.ReLU(), nn.Linear(32, 1))

    model = network()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    criterion = nn.BCEWithLogitsLoss()
    history = []
    for epoch in range(100):
        model.train()
        optimizer.zero_grad()
        loss = criterion(model(train_tensor), targets)
        loss.backward()
        optimizer.step()
        history.append(float(loss.detach()))
        if (epoch + 1) % 25 == 0:
            print(f"Epoch {epoch + 1}: loss={history[-1]:.4f}")
    model.eval()
    with torch.no_grad():
        probabilities = model(valid_tensor).sigmoid().flatten()
    accuracy = float(np.mean((probabilities.numpy() >= 0.5) == y_valid))
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "epochs": 100,
            "seed": seed,
            "scaler_mean": torch.tensor(scaler.mean_),
            "scaler_scale": torch.tensor(scaler.scale_),
        },
        output / "model.pt",
    )
    checkpoint = torch.load(output / "model.pt", map_location="cpu", weights_only=True)
    restored = network()
    restored.load_state_dict(checkpoint["model_state_dict"])
    restored.eval()
    with torch.no_grad():
        restored_probabilities = restored(valid_tensor).sigmoid().flatten()
    torch.testing.assert_close(probabilities, restored_probabilities)
    metrics = {
        "framework": "pytorch",
        "version": str(torch.__version__),
        "device": "cpu",
        "seed": seed,
        "validation_accuracy": accuracy,
        "loss": history,
        "reload_verified": True,
    }
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2))
    np.savetxt(
        output / "validation_predictions.csv",
        np.column_stack((y_valid, probabilities.numpy())),
        delimiter=",",
        header="actual,probability",
        comments="",
    )
    print(f"PyTorch validation accuracy: {accuracy:.3f}; checkpoint reload verified.")
    print(f"Artifacts saved in {output.resolve()}")
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="models/pytorch")
    args = parser.parse_args()
    train(args.output_dir)
