"""
Abnormal-only fixed-split training on all labelled datasets currently available.

Datasets:
  - PTB-XL
  - CINC2020
  - CODE-15

Classes:
  0 = AF
  1 = IAVB
  2 = SB
  3 = STach

Leakage controls:
  - PTB-XL records duplicated inside CINC2020 are grouped by the same PTB-XL id.
  - CODE-15 samples are grouped by patient_id, so exams from the same patient
    cannot cross train/validation/test.
"""

from __future__ import annotations

import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import train_fixed_split as fixed
from model import build_model, count_parameters


ABNORMAL_CLASS_NAMES = ["AF", "IAVB", "SB", "STach"]
FIVE_TO_ABNORMAL = {
    1: 0,  # AF
    2: 1,  # IAVB
    3: 2,  # SB
    4: 3,  # STach
}
ALL_DATASETS = {
    "ptbxl": Path("preprocessed_ptbxl_attention"),
    "cinc2020": Path("preprocessed_cinc2020_attention"),
    "code15": Path("preprocessed_code15_attention"),
}


def load_ptbxl_or_cinc(base_dir: Path, name: str, rel_path: Path):
    data, refs = fixed.load_dataset(base_dir, name, rel_path)
    abnormal_refs = []
    for ref in refs:
        if ref.label == 0:
            continue
        abnormal_refs.append(
            fixed.SampleRef(
                global_index=ref.global_index,
                dataset=ref.dataset,
                local_index=ref.local_index,
                label=FIVE_TO_ABNORMAL[ref.label],
                group_id=ref.group_id,
                record=ref.record,
            )
        )
    return data, abnormal_refs


def load_code15(base_dir: Path, rel_path: Path):
    ds_dir = base_dir / rel_path
    signals = np.load(ds_dir / "signals.npy", mmap_mode="r")
    labels = np.load(ds_dir / "labels.npy", mmap_mode="r")
    qrs7 = np.load(ds_dir / "qrs7_features.npy", mmap_mode="r")
    metadata = pd.read_csv(ds_dir / "metadata.csv")

    refs = []
    for local_index, row in metadata.iterrows():
        original_label = int(labels[local_index])
        if original_label == 0 or original_label < 0:
            continue
        patient_id = int(row["patient_id"])
        exam_id = int(row["exam_id"])
        refs.append(
            fixed.SampleRef(
                global_index=-1,
                dataset="code15",
                local_index=int(local_index),
                label=FIVE_TO_ABNORMAL[original_label],
                group_id=f"code15_patient:{patient_id}",
                record=f"code15_exam:{exam_id}",
            )
        )
    return {"signals": signals, "labels": labels, "qrs7": qrs7}, refs


def make_group_split_allow_mixed_classes(refs: list[fixed.SampleRef], seed: int):
    """Group split for patient/record groups that may contain multiple classes."""
    group_label_counts: dict[str, Counter] = defaultdict(Counter)
    for ref in refs:
        group_label_counts[ref.group_id][ref.label] += 1

    groups = np.array(sorted(group_label_counts))
    group_labels = []
    for group in groups:
        counts = group_label_counts[group]
        max_count = max(counts.values())
        primary = min(label for label, count in counts.items() if count == max_count)
        group_labels.append(primary)
    group_labels = np.array(group_labels)

    train_groups, temp_groups, _, temp_y = train_test_split(
        groups,
        group_labels,
        test_size=0.20,
        random_state=seed,
        stratify=group_labels,
    )
    val_groups, test_groups = train_test_split(
        temp_groups,
        test_size=0.50,
        random_state=seed,
        stratify=temp_y,
    )

    split_by_group = {}
    for group in train_groups:
        split_by_group[group] = "train"
    for group in val_groups:
        split_by_group[group] = "val"
    for group in test_groups:
        split_by_group[group] = "test"

    split_indices = {"train": [], "val": [], "test": []}
    for ref in refs:
        split_indices[split_by_group[ref.group_id]].append(ref.global_index)
    return split_indices


def save_group_summary(out_dir: Path, refs: list[fixed.SampleRef]) -> None:
    group_to_labels: dict[str, set[int]] = defaultdict(set)
    group_to_n = Counter()
    for ref in refs:
        group_to_labels[ref.group_id].add(ref.label)
        group_to_n[ref.group_id] += 1
    summary = {
        "n_groups": len(group_to_labels),
        "n_mixed_class_groups": sum(1 for labels in group_to_labels.values() if len(labels) > 1),
        "max_samples_per_group": max(group_to_n.values()),
    }
    (out_dir / "group_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main() -> None:
    fixed.CLASS_NAMES = ABNORMAL_CLASS_NAMES
    args = fixed.parse_args()
    fixed.seed_everything(args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "config.json").write_text(
        json.dumps({**vars(args), "task": "abnormal_only_all_datasets_4class"}, default=str, indent=2),
        encoding="utf-8",
    )

    datasets = {}
    refs: list[fixed.SampleRef] = []
    for name, rel_path in ALL_DATASETS.items():
        if name == "code15":
            data, ds_refs = load_code15(args.base_dir, rel_path)
        else:
            data, ds_refs = load_ptbxl_or_cinc(args.base_dir, name, rel_path)
        datasets[name] = data
        refs.extend(ds_refs)
    refs = fixed.relabel_global_indices(refs)

    split_indices = make_group_split_allow_mixed_classes(refs, args.seed)
    fixed.assert_no_leakage(refs, split_indices)
    fixed.save_splits(args.output_dir, refs, split_indices)
    save_group_summary(args.output_dir / "splits", refs)

    train_loader = fixed.make_loader(
        datasets, refs, split_indices["train"], args.batch_size, True, args.num_workers
    )
    val_loader = fixed.make_loader(
        datasets, refs, split_indices["val"], args.batch_size, False, args.num_workers
    )
    test_loader = fixed.make_loader(
        datasets, refs, split_indices["test"], args.batch_size, False, args.num_workers
    )

    device = torch.device(args.device)
    model = build_model(n_leads=12, n_classes=len(ABNORMAL_CLASS_NAMES), qrs_aux_dim=64, device=str(device))
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="max", factor=0.5, patience=3, min_lr=1e-6
    )
    criterion = torch.nn.CrossEntropyLoss(
        weight=fixed.class_weights_from_indices(refs, split_indices["train"], str(device))
    )

    start_epoch = 1
    best_metric = -math.inf
    best_epoch = 0
    if args.resume is not None:
        ckpt = torch.load(args.resume, map_location=device)
        model.load_state_dict(ckpt["model_state_dict"])
        optimizer.load_state_dict(ckpt["optimizer_state_dict"])
        if ckpt.get("scheduler_state_dict") is not None:
            scheduler.load_state_dict(ckpt["scheduler_state_dict"])
        start_epoch = int(ckpt["epoch"]) + 1
        best_metric = float(ckpt.get("best_metric", -math.inf))

    metadata = {
        "task": "abnormal_only_all_datasets_4class",
        "label_mapping": {"AF": ["AF"], "IAVB": ["IAVB"], "SB": ["SB"], "STach": ["STach"]},
        "n_parameters": count_parameters(model),
        "device": str(device),
        "datasets": list(ALL_DATASETS),
        "class_names": ABNORMAL_CLASS_NAMES,
    }
    (args.output_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2), flush=True)

    epochs_without_improvement = 0
    for epoch in range(start_epoch, args.epochs + 1):
        t0 = time.time()
        train_metrics = fixed.run_epoch(model, train_loader, criterion, device, optimizer=optimizer)
        val_metrics = fixed.run_epoch(model, val_loader, criterion, device, optimizer=None)
        scheduler.step(val_metrics["macro_f1"])

        improved = val_metrics["macro_f1"] > best_metric
        if improved:
            best_metric = val_metrics["macro_f1"]
            best_epoch = epoch
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1

        row = {
            "epoch": epoch,
            "lr": optimizer.param_groups[0]["lr"],
            "train_loss": train_metrics["loss"],
            "train_accuracy": train_metrics["accuracy"],
            "train_macro_f1": train_metrics["macro_f1"],
            "train_weighted_f1": train_metrics["weighted_f1"],
            "val_loss": val_metrics["loss"],
            "val_accuracy": val_metrics["accuracy"],
            "val_macro_f1": val_metrics["macro_f1"],
            "val_weighted_f1": val_metrics["weighted_f1"],
            "best_val_macro_f1": best_metric,
            "best_epoch": best_epoch,
            "epoch_seconds": time.time() - t0,
        }
        fixed.append_epoch_logs(args.output_dir, row)
        print(json.dumps(row), flush=True)

        checkpoint_extra = {"epoch_metrics": row}
        fixed.save_checkpoint(
            args.output_dir / "checkpoints" / "last.pt",
            model,
            optimizer,
            scheduler,
            epoch,
            best_metric,
            args,
            checkpoint_extra,
        )
        if improved:
            fixed.save_checkpoint(
                args.output_dir / "checkpoints" / "best.pt",
                model,
                optimizer,
                scheduler,
                epoch,
                best_metric,
                args,
                checkpoint_extra,
            )

        if args.patience > 0 and epochs_without_improvement >= args.patience:
            print(f"Early stopping at epoch {epoch}.", flush=True)
            break

    best_path = args.output_dir / "checkpoints" / "best.pt"
    if best_path.exists():
        ckpt = torch.load(best_path, map_location=device)
        model.load_state_dict(ckpt["model_state_dict"])

    labels, preds, probs = fixed.predict_split(model, test_loader, device)
    report = fixed.evaluate_predictions(labels, preds, probs)
    fixed.save_test_outputs(args.output_dir, labels, preds, probs, report)
    print(json.dumps({"final_test": report["overall"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
