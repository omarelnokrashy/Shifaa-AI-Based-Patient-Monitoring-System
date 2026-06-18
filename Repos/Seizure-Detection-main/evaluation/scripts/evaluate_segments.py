"""
evaluation/scripts/evaluate_segments.py
-----------------------------------------
Compute AUROC / AUPRC / F1 / Precision / Recall on the held-out
exact-count test split using pre-exported score CSV files.

Usage
-----
  python evaluation/scripts/evaluate_segments.py \\
      --scores-csv evaluation/results/official_test_scores.csv \\
      --threshold 0.3081 \\
      --out-json  evaluation/results/segment_metrics.json
"""

import argparse
import json
import csv
from pathlib import Path

import numpy as np
from sklearn.metrics import (
    roc_auc_score, average_precision_score,
    f1_score, precision_score, recall_score, accuracy_score,
    mean_squared_error, confusion_matrix,
)


def load_scores(path: str) -> tuple:
    labels, scores = [], []
    with open(path) as f:
        reader = csv.DictReader(f)
        for r in reader:
            labels.append(int(float(r.get("label", r.get("y", 0)))))
            scores.append(float(r.get("prob", r.get("score", 0))))
    return np.array(labels), np.array(scores)


def evaluate(labels, scores, threshold: float) -> dict:
    preds = (scores >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(labels, preds, labels=[0, 1]).ravel()
    fdr = fp / max(tp + fp, 1)
    return {
        "auroc":     round(float(roc_auc_score(labels, scores)), 4),
        "auprc":     round(float(average_precision_score(labels, scores)), 4),
        "f1":        round(float(f1_score(labels, preds, zero_division=0)), 4),
        "precision": round(float(precision_score(labels, preds, zero_division=0)), 4),
        "recall":    round(float(recall_score(labels, preds, zero_division=0)), 4),
        "accuracy":  round(float(accuracy_score(labels, preds)), 4),
        "fdr":       round(float(fdr), 4),
        "rmse":      round(float(mean_squared_error(labels, scores) ** 0.5), 4),
        "tp":        int(tp),
        "fp":        int(fp),
        "tn":        int(tn),
        "fn":        int(fn),
        "threshold": threshold,
        "n_total":   len(labels),
        "n_positive": int(labels.sum()),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--scores-csv", required=True)
    p.add_argument("--threshold",  type=float, default=0.3081087228480716)
    p.add_argument("--out-json",   default="")
    args = p.parse_args()

    labels, scores = load_scores(args.scores_csv)
    metrics = evaluate(labels, scores, args.threshold)

    print("\n=== Segment-Level Evaluation ===")
    for k, v in metrics.items():
        print(f"  {k:12s}: {v}")

    if args.out_json:
        Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out_json, "w") as f:
            json.dump(metrics, f, indent=2)
        print(f"\nSaved: {args.out_json}")


if __name__ == "__main__":
    main()
