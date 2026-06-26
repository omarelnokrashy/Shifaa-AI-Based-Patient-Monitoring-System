"""
evaluate.py — Standalone Evaluation Module
============================================
Computes the full suite of classification metrics for a trained ECGClassifier
on any labelled split (validation or held-out test set).

Metrics produced
----------------
  Overall
    accuracy          — fraction of correctly classified samples
    macro F1          — unweighted mean F1 across all classes
    weighted F1       — F1 weighted by class support
    Cohen's kappa     — agreement corrected for chance
    Matthews CC       — balanced metric robust to class imbalance

  Per-class  (one row per arrhythmia)
    precision, recall, F1, support, AUROC, Average Precision

  Confusion matrix   — raw counts and row-normalised (recall) version

Usage
-----
  # Minimal — just pass model + arrays
  from evaluate import evaluate_split
  report = evaluate_split(model, signals, labels, qrs7, device="cuda")

  # Save everything to disk
  report = evaluate_split(
      model, signals, labels, qrs7,
      device="cuda",
      split_name="test",
      output_dir="./results",
      class_names=["NSR", "AF", "IAVB", "SB", "STach"],
  )
  # Writes:
  #   results/test_metrics.json
  #   results/test_confusion_matrix.csv
  #   results/test_per_class.csv
  #   results/test_predictions.csv

Integration with train.py
--------------------------
  See "CHANGES TO TRAINING CODE" section at the bottom of this file.
"""

import json
import csv
import os
from pathlib import Path
from typing import Optional

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    confusion_matrix,
    cohen_kappa_score,
    matthews_corrcoef,
    roc_auc_score,
    average_precision_score,
    classification_report,
)

# Default class labels matching the paper
DEFAULT_CLASS_NAMES = [
    "NSR",    # 0 — Normal Sinus Rhythm
    "AF",     # 1 — Atrial Fibrillation
    "IAVB",   # 2 — First-Degree AV Block
    "SB",     # 3 — Sinus Bradycardia
    "STach",  # 4 — Sinus Tachycardia
]


# ---------------------------------------------------------------------------
# Core inference pass
# ---------------------------------------------------------------------------

@torch.no_grad()
def run_inference(
    model: torch.nn.Module,
    signals: np.ndarray,
    qrs7: Optional[np.ndarray],
    device: str = "cpu",
    batch_size: int = 64,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Run model over the full split in batches.

    Args:
        model      : trained ECGClassifier (already on device or will be moved)
        signals    : (N, T, C) float32 ECG signals
        qrs7       : (N, 7)    float32 auxiliary features, or None
        device     : "cpu" | "cuda"
        batch_size : inference batch size (larger = faster, more memory)

    Returns:
        probs : (N, n_classes) softmax probabilities
        preds : (N,)           argmax predictions
    """
    model.eval()
    model.to(device)

    sig_t = torch.tensor(signals, dtype=torch.float32)
    q7_t  = torch.tensor(qrs7,    dtype=torch.float32) if qrs7 is not None \
            else torch.zeros(len(signals), 7, dtype=torch.float32)

    dataset = TensorDataset(sig_t, q7_t)
    loader  = DataLoader(dataset, batch_size=batch_size, shuffle=False)

    all_probs = []
    for sig_b, q7_b in loader:
        sig_b = sig_b.to(device)
        q7_b  = q7_b.to(device) if model.use_aux else None
        logits, _ = model(sig_b, q7_b)
        all_probs.append(F.softmax(logits, dim=-1).cpu().numpy())

    probs = np.concatenate(all_probs, axis=0)   # (N, C)
    preds = probs.argmax(axis=-1)               # (N,)
    return probs, preds


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def compute_metrics(
    labels: np.ndarray,
    preds:  np.ndarray,
    probs:  np.ndarray,
    class_names: list[str],
) -> dict:
    """
    Compute the full metric suite from ground-truth labels, hard predictions,
    and softmax probability scores.

    Args:
        labels       : (N,) integer ground-truth class indices
        preds        : (N,) integer predicted class indices
        probs        : (N, C) softmax probability matrix
        class_names  : list of C human-readable class names

    Returns:
        Nested dict with keys:
            "overall"    → dict of scalar metrics
            "per_class"  → dict[class_name] → dict of per-class metrics
            "confusion"  → {"raw": ndarray (C,C), "normalised": ndarray (C,C)}
            "report"     → sklearn classification_report string
    """
    n_classes  = len(class_names)
    labels_oh  = np.eye(n_classes)[labels]           # one-hot for AUROC

    # ── Overall ──────────────────────────────────────────────────────────
    acc     = float(accuracy_score(labels, preds))
    macro_f1 = float(f1_score(labels, preds, average="macro",    zero_division=0))
    wtd_f1   = float(f1_score(labels, preds, average="weighted", zero_division=0))
    kappa    = float(cohen_kappa_score(labels, preds))
    mcc      = float(matthews_corrcoef(labels, preds))

    # Multi-class AUROC (one-vs-rest, macro)
    try:
        auroc_macro = float(roc_auc_score(
            labels_oh, probs, multi_class="ovr", average="macro"))
    except ValueError:
        auroc_macro = float("nan")   # fails if a class has no positive samples

    overall = {
        "accuracy":         acc,
        "macro_f1":         macro_f1,
        "weighted_f1":      wtd_f1,
        "cohen_kappa":      kappa,
        "matthews_cc":      mcc,
        "auroc_macro_ovr":  auroc_macro,
        "n_samples":        int(len(labels)),
    }

    # ── Per-class ─────────────────────────────────────────────────────────
    prec_list = precision_score(labels, preds, average=None, zero_division=0)
    rec_list  = recall_score   (labels, preds, average=None, zero_division=0)
    f1_list   = f1_score       (labels, preds, average=None, zero_division=0)
    support   = np.bincount(labels, minlength=n_classes)

    per_class = {}
    for i, name in enumerate(class_names):
        # Per-class AUROC and Average Precision (binary: this class vs rest)
        try:
            cls_auroc = float(roc_auc_score(labels_oh[:, i], probs[:, i]))
        except ValueError:
            cls_auroc = float("nan")
        try:
            cls_ap = float(average_precision_score(labels_oh[:, i], probs[:, i]))
        except ValueError:
            cls_ap = float("nan")

        per_class[name] = {
            "precision":       float(prec_list[i]),
            "recall":          float(rec_list[i]),
            "f1":              float(f1_list[i]),
            "support":         int(support[i]),
            "auroc":           cls_auroc,
            "avg_precision":   cls_ap,
        }

    # ── Confusion matrix ─────────────────────────────────────────────────
    cm_raw  = confusion_matrix(labels, preds, labels=list(range(n_classes)))
    # Row-normalise → recall per class (each row sums to 1)
    row_sum = cm_raw.sum(axis=1, keepdims=True).clip(min=1)
    cm_norm = cm_raw.astype(float) / row_sum

    # sklearn plain-text report
    report = classification_report(
        labels, preds,
        target_names=class_names,
        zero_division=0,
    )

    return {
        "overall":   overall,
        "per_class": per_class,
        "confusion": {"raw": cm_raw, "normalised": cm_norm},
        "report":    report,
    }


# ---------------------------------------------------------------------------
# Pretty printing
# ---------------------------------------------------------------------------

def print_report(metrics: dict, split_name: str = "Evaluation"):
    """
    Print a formatted report to stdout.

    Args:
        metrics    : dict returned by compute_metrics()
        split_name : label shown in the header ("Validation" / "Test")
    """
    ov = metrics["overall"]
    pc = metrics["per_class"]
    cm = metrics["confusion"]["raw"]

    w = 66
    print(f"\n{'═' * w}")
    print(f"  {split_name.upper()} RESULTS  ({ov['n_samples']} samples)")
    print(f"{'═' * w}")

    # Overall
    print(f"\n  {'Metric':<28}  {'Value':>10}")
    print(f"  {'─' * 40}")
    rows = [
        ("Accuracy",         f"{ov['accuracy']:.4f}"),
        ("Macro F1",         f"{ov['macro_f1']:.4f}"),
        ("Weighted F1",      f"{ov['weighted_f1']:.4f}"),
        ("Cohen's Kappa",    f"{ov['cohen_kappa']:.4f}"),
        ("Matthews CC",      f"{ov['matthews_cc']:.4f}"),
        ("AUROC (macro OvR)",f"{ov['auroc_macro_ovr']:.4f}"
                             if not np.isnan(ov['auroc_macro_ovr']) else "  n/a"),
    ]
    for name, val in rows:
        print(f"  {name:<28}  {val:>10}")

    # Per-class
    print(f"\n  {'Class':<8}  {'Prec':>7}  {'Rec':>7}  {'F1':>7}  "
          f"{'AUROC':>7}  {'AP':>7}  {'N':>6}")
    print(f"  {'─' * 60}")
    for name, m in pc.items():
        auroc_s = f"{m['auroc']:.4f}" if not np.isnan(m['auroc']) else "   n/a"
        ap_s    = f"{m['avg_precision']:.4f}" if not np.isnan(m['avg_precision']) else "   n/a"
        print(f"  {name:<8}  {m['precision']:>7.4f}  {m['recall']:>7.4f}  "
              f"{m['f1']:>7.4f}  {auroc_s:>7}  {ap_s:>7}  {m['support']:>6}")

    # Confusion matrix
    class_names = list(pc.keys())
    col_w = max(len(n) for n in class_names) + 2
    header = " " * (col_w + 2) + "".join(f"{n:>{col_w}}" for n in class_names)
    print(f"\n  Confusion matrix (raw counts — rows=true, cols=pred):")
    print(f"  {header}")
    for i, row_name in enumerate(class_names):
        row = "".join(f"{cm[i, j]:>{col_w}}" for j in range(len(class_names)))
        print(f"  {row_name:<{col_w}}  {row}")

    # sklearn report
    print(f"\n  Classification Report:\n")
    for line in metrics["report"].splitlines():
        print(f"    {line}")

    print(f"\n{'═' * w}\n")


# ---------------------------------------------------------------------------
# Disk I/O helpers
# ---------------------------------------------------------------------------

def _ensure_dir(path: str):
    Path(path).mkdir(parents=True, exist_ok=True)


def save_metrics_json(metrics: dict, path: str):
    """Serialise overall + per-class metrics to JSON (confusion matrix excluded)."""
    serialisable = {
        "overall":   metrics["overall"],
        "per_class": metrics["per_class"],
    }
    with open(path, "w") as f:
        json.dump(serialisable, f, indent=2)


def save_confusion_csv(metrics: dict, path: str, class_names: list[str]):
    """Write raw confusion matrix to CSV."""
    cm = metrics["confusion"]["raw"]
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["true \\ pred"] + class_names)
        for i, row_name in enumerate(class_names):
            writer.writerow([row_name] + cm[i].tolist())


def save_per_class_csv(metrics: dict, path: str):
    """Write per-class metrics table to CSV."""
    pc = metrics["per_class"]
    fieldnames = ["class", "precision", "recall", "f1",
                  "auroc", "avg_precision", "support"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for name, m in pc.items():
            writer.writerow({"class": name, **m})


def save_predictions_csv(
    labels: np.ndarray,
    preds:  np.ndarray,
    probs:  np.ndarray,
    path:   str,
    class_names: list[str],
):
    """Write per-sample ground-truth, prediction, and class probabilities to CSV."""
    with open(path, "w", newline="") as f:
        prob_headers = [f"prob_{n}" for n in class_names]
        writer = csv.writer(f)
        writer.writerow(["sample_idx", "true_label", "true_class",
                         "pred_label", "pred_class", "correct"] + prob_headers)
        for i, (true, pred, prob_row) in enumerate(zip(labels, preds, probs)):
            writer.writerow([
                i,
                int(true), class_names[true],
                int(pred), class_names[pred],
                int(true == pred),
                *[f"{p:.6f}" for p in prob_row],
            ])


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def evaluate_split(
    model:        torch.nn.Module,
    signals:      np.ndarray,
    labels:       np.ndarray,
    qrs7:         Optional[np.ndarray] = None,
    *,
    device:       str             = "cpu",
    batch_size:   int             = 64,
    split_name:   str             = "Evaluation",
    class_names:  list[str]       = DEFAULT_CLASS_NAMES,
    output_dir:   Optional[str]   = None,
    verbose:      bool            = True,
) -> dict:
    """
    Full evaluation pipeline for one split.

    Args:
        model       : trained ECGClassifier
        signals     : (N, T, C) preprocessed ECG signals
        labels      : (N,) integer ground-truth class indices
        qrs7        : (N, 7) Pan-Tompkins features, or None
        device      : "cpu" | "cuda"
        batch_size  : inference batch size
        split_name  : label for printed headers and output filenames
                      (e.g. "Validation", "Test")
        class_names : list of C human-readable class names
        output_dir  : if provided, saves four files here:
                        {split_name}_metrics.json
                        {split_name}_confusion_matrix.csv
                        {split_name}_per_class.csv
                        {split_name}_predictions.csv
        verbose     : if True, prints the full formatted report

    Returns:
        dict with keys:
            "overall"    — scalar metrics dict
            "per_class"  — per-class metrics dict
            "confusion"  — {"raw": ndarray, "normalised": ndarray}
            "report"     — sklearn classification_report string
            "probs"      — (N, C) softmax probability matrix
            "preds"      — (N,) hard predictions
    """
    # 1. Inference
    probs, preds = run_inference(model, signals, qrs7,
                                 device=device, batch_size=batch_size)

    # 2. Metrics
    metrics = compute_metrics(labels, preds, probs, class_names)
    metrics["probs"] = probs
    metrics["preds"] = preds

    # 3. Print
    if verbose:
        print_report(metrics, split_name)

    # 4. Save
    if output_dir is not None:
        _ensure_dir(output_dir)
        prefix = os.path.join(output_dir, split_name.lower().replace(" ", "_"))

        save_metrics_json(
            metrics, f"{prefix}_metrics.json")
        save_confusion_csv(
            metrics, f"{prefix}_confusion_matrix.csv", class_names)
        save_per_class_csv(
            metrics, f"{prefix}_per_class.csv")
        save_predictions_csv(
            labels, preds, probs, f"{prefix}_predictions.csv", class_names)

        if verbose:
            print(f"  Saved to: {output_dir}/")
            for ext in ["metrics.json", "confusion_matrix.csv",
                        "per_class.csv", "predictions.csv"]:
                print(f"    {split_name.lower()}_{ext}")

    return metrics


# ---------------------------------------------------------------------------
# CHANGES TO TRAINING CODE  (train.py)
# ---------------------------------------------------------------------------
#
# The existing train.py evaluate() function is a lightweight loop used only
# during the CV training loop for early stopping and fold scoring.
# Keep it as-is. Use evaluate_split() from this file for post-training
# validation and final test-set evaluation.
#
# ── 1. Imports to add at top of train.py ──────────────────────────────────
#
#   from evaluate import evaluate_split, DEFAULT_CLASS_NAMES
#
# ── 2. After each CV fold (inside train()) ────────────────────────────────
#
#   Replace the final evaluate() call at the end of each fold with:
#
#       report = evaluate_split(
#           model,
#           signals[val_idx], labels[val_idx],
#           qrs7[val_idx] if qrs7 is not None else None,
#           device=device,
#           split_name=f"Fold_{fold+1}_Val",
#           output_dir=f"./results/fold_{fold+1}",   # optional
#           verbose=verbose,
#       )
#       fold_results.append({
#           "fold":        fold + 1,
#           "acc":         report["overall"]["accuracy"],
#           "f1":          report["overall"]["macro_f1"],
#           "kappa":       report["overall"]["cohen_kappa"],
#           "mcc":         report["overall"]["matthews_cc"],
#           "auroc":       report["overall"]["auroc_macro_ovr"],
#           "cm":          report["confusion"]["raw"],
#           "model_state": copy.deepcopy(model.state_dict()),
#       })
#
# ── 3. After training finishes — evaluate on held-out test set ────────────
#
#   Load the best fold's weights (or retrain on all CV data), then:
#
#       test_report = evaluate_split(
#           model,
#           test_signals, test_labels, test_qrs7,
#           device=device,
#           split_name="Test",
#           output_dir="./results",
#           verbose=True,
#       )
#
# ── 4. If you switch from CV to a fixed train/val/test split ─────────────
#
#   Remove the StratifiedKFold loop entirely and call:
#
#       val_report  = evaluate_split(model, val_signals,  val_labels,
#                                    val_qrs7,  split_name="Validation")
#       test_report = evaluate_split(model, test_signals, test_labels,
#                                    test_qrs7, split_name="Test",
#                                    output_dir="./results")
#
# ---------------------------------------------------------------------------
