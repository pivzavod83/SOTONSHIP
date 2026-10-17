"""Reproduce synthetic GCN weights, XGBoost trees and held-out calibration.

Training is deliberately NOT a corpus benchmark. No 94%/18% or production bug
probabilities are claimed. XGBoost and sklearn are training-only dependencies.
On macOS install libomp before training (portable inference does not need it).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]


def main():
    rng = np.random.default_rng(411)
    # Synthetic local neighborhoods, with shared semantic type and varied scale,
    # rounding, branches, external calls and structural residual. Graph adjacency
    # smoothing is the same two-hop transform used in inference.
    samples = 2400
    raw = np.column_stack([rng.integers(0, 2, samples) for _ in range(8)]).astype(float)
    raw[:, 3] = rng.integers(0, 9, samples) / 8
    raw[:, 7] = rng.uniform(0, 1, samples)
    raw[:, :3] = np.eye(3)[rng.integers(0, 3, samples)]
    neighbors = raw[rng.integers(0, samples, samples)]
    smooth = (raw + neighbors) / 2
    # Learn a structural embedding objective with a common financial-scalar axis.
    target = np.column_stack([smooth[:, :3].sum(axis=1), smooth[:, 3:],
                              smooth[:, 0] + smooth[:, 2], 1 - smooth[:, 6]])
    w1 = rng.normal(0.1, 0.2, (8, 12))
    w2 = rng.normal(0, 0.2, (12, 8))
    for _ in range(600):
        pre = smooth @ w1
        hidden = np.maximum(pre, 0)
        predicted = hidden @ w2
        gradient = 2 * (predicted - target) / samples
        grad2 = hidden.T @ gradient
        grad1 = smooth.T @ ((gradient @ w2.T) * (pre > 0))
        w1 -= 0.025 * grad1
        w2 -= 0.025 * grad2
    vectors = np.maximum(smooth @ w1, 0) @ w2
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    values = np.concatenate([raw, vectors], axis=1)
    # Generated labels intentionally reflect a demo risk policy with observation
    # noise. Calibrating on held-out synthetic rows does not validate real code.
    logits = -3 + 3.4 * raw[:, 1] + 2.5 * raw[:, 6] + 1.2 * raw[:, 5] - 1.2 * raw[:, 4]
    probabilities = 1 / (1 + np.exp(-logits))
    labels = rng.binomial(1, probabilities)
    split = 1600
    learner = XGBClassifier(n_estimators=24, max_depth=3, learning_rate=0.12,
                            n_jobs=1, random_state=411, base_score=0.5)
    learner.fit(values[:split], labels[:split])
    calibration_split = 2000
    margin = learner.predict(values[split:calibration_split], output_margin=True)
    calibration = LogisticRegression().fit(margin.reshape(-1, 1), labels[split:calibration_split])
    predicted = calibration.predict_proba(learner.predict(values[calibration_split:], output_margin=True).reshape(-1, 1))[:, 1]
    trees = [json.loads(tree) for tree in learner.get_booster().get_dump(dump_format="json")]
    artifact = {"formatVersion": 1, "architecture": "two-layer normalized-adjacency GCN 8->12->8, ReLU",
                "W1": w1.tolist(), "W2": w2.tolist(),
                "riskClassifier": {"type": "XGBoost binary:logistic", "baseMargin": 0.0, "trees": trees,
                    "calibration": {"method": "held-out synthetic Platt logistic",
                                    "slope": float(calibration.coef_[0, 0]), "intercept": float(calibration.intercept_[0])}},
                "provenance": {"modelId": "cobol_java_gnn_v1", "status": "AI-authored synthetic demonstration model",
                    "trainingSeed": 411, "syntheticRows": samples, "gnnTrainingEpochs": 600,
                    "gnnObjective": "synthetic neighborhood structural/type projection MSE",
                    "classificationLabels": "sampled from documented generated risk policy, not real defects",
                    "split": {"training": 1600, "calibration": 400, "test": 400},
                    "syntheticTestMetrics": {"brierScore": float(brier_score_loss(labels[calibration_split:], predicted)),
                                              "rocAuc": float(roc_auc_score(labels[calibration_split:], predicted))},
                    "limitations": ["No labelled real COBOL/Java alignment corpus; cosine is not an accuracy measure.",
                                    "Node scores are calibrated on synthetic data only and are not validated production probabilities.",
                                    "No measured 94% vs 18% alignment claim."]}}
    destination = ROOT / "ml_engine/models/cobol_java_gnn_v1.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(artifact, indent=2) + "\n")
    learner.get_booster().save_model(ROOT / "ml_engine/models/risk_xgboost_v1.json")
    print(json.dumps({"artifact": str(destination), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                      "syntheticTestMetrics": artifact["provenance"]["syntheticTestMetrics"]}))


if __name__ == "__main__":
    main()
