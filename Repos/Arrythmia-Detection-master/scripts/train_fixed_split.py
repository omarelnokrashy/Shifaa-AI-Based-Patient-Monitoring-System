"""
Fixed train/validation/test training for the attention ECG model.

Uses the preprocessed PTB-XL and CINC2020 arrays, creates an 80/10/10
stratified group split, and saves all logs, splits, checkpoints, and final
test metrics. Groups prevent duplicated PTB-XL records from crossing splits
when the same record appears in both standalone PTB-XL and CINC2020.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    classification_report,
    cohen_kappa_score,
    confusion_matrix,
    f1_score,
    matthews_corrcoef,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

from model import build_model, count_parameters


CLASS_NAMES = ["NSR", "AF", "IAVB", "SB", "STach"]
DEFAULT_DATASETS = {
    "ptbxl": Path("preprocessed_ptbxl_attention"),
    "cinc2020": Path("preprocessed_cinc2020_attention"),
}


@dataclass(frozen=True)
class SampleRef:
    global_index: int
    dataset: str
    local_index: int
    label: int
    group_id: str
    record: str


class CombinedECGDataset(Dataset):
    def __init__(self, datasets: dict[str, dict[str, np.ndarray]], refs: list[SampleRef]):
        self.datasets = datasets
        self.refs = refs

    def __len__(self) -> int:
        return len(self.refs)

    def __getitem__(self, idx: int):
        ref = self.refs[idx]
        data = self.datasets[ref.dataset]
        signal = torch.from_numpy(np.array(data["signals"][ref.local_index], dtype=np.float32, copy=True))
        qrs7 = torch.from_numpy(np.array(data["qrs7"][ref.local_index], dtype=np.float32, copy=True))
        label = torch.tensor(ref.label, dtype=torch.long)
        return signal, qrs7, label


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True


def canonical_group_id(dataset: str, metadata_row: pd.Series) -> str:
    if dataset == "ptbxl":
        ecg_id = int(metadata_row["ecg_id"])
        return f"ptbxl:{ecg_id:05d}"

    record = str(metadata_row["record"])
    record_name = Path(record).name

    # CINC2020's PTB-XL subset uses names like HR00001. Group them with the
    # standalone PTB-XL ecg_id so the duplicate cannot leak across splits.
    if "\\ptb-xl\\" in record.lower() or "/ptb-xl/" in record.lower():
        match = re.search(r"HR(\d+)$", record_name, flags=re.IGNORECASE)
        if match:
            return f"ptbxl:{int(match.group(1)):05d}"

    return f"{dataset}:{record_name}"


def load_dataset(base_dir: Path, name: str, rel_path: Path) -> tuple[dict[str, np.ndarray], list[SampleRef]]:
    ds_dir = base_dir / rel_path
    signals = np.load(ds_dir / "signals.npy", mmap_mode="r")
    labels = np.load(ds_dir / "labels.npy", mmap_mode="r")
    qrs7 = np.load(ds_dir / "qrs7_features.npy", mmap_mode="r")
    metadata = pd.read_csv(ds_dir / "metadata.csv")

    refs: list[SampleRef] = []
    for local_index, row in metadata.iterrows():
        label = int(labels[local_index])
        if label < 0:
            continue
        record = str(row.get("path", row.get("record", local_index)))
        refs.append(
            SampleRef(
                global_index=-1,
                dataset=name,
                local_index=int(local_index),
                label=label,
                group_id=canonical_group_id(name, row),
                record=record,
            )
        )

    data = {"signals": signals, "labels": labels, "qrs7": qrs7}
    return data, refs


def relabel_global_indices(refs: Iterable[SampleRef]) -> list[SampleRef]:
    out = []
    for i, ref in enumerate(refs):
        out.append(
            SampleRef(
                global_index=i,
                dataset=ref.dataset,
                local_index=ref.local_index,
                label=ref.label,
                group_id=ref.group_id,
                record=ref.record,
            )
        )
    return out


def make_fixed_splits(refs: list[SampleRef], seed: int) -> dict[str, list[int]]:
    group_to_labels: dict[str, set[int]] = {}
    for ref in refs:
        group_to_labels.setdefault(ref.group_id, set()).add(ref.label)

    conflicting = {gid: labels for gid, labels in group_to_labels.items() if len(labels) > 1}
    if conflicting:
        examples = list(conflicting.items())[:5]
        raise RuntimeError(f"Found groups with conflicting labels, examples: {examples}")

    groups = np.array(sorted(group_to_labels))
    group_labels = np.array([next(iter(group_to_labels[g])) for g in groups])

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


def save_splits(out_dir: Path, refs: list[SampleRef], split_indices: dict[str, list[int]]) -> None:
    split_dir = out_dir / "splits"
    split_dir.mkdir(parents=True, exist_ok=True)
    np.savez(
        split_dir / "split_indices.npz",
        train=np.array(split_indices["train"], dtype=np.int64),
        val=np.array(split_indices["val"], dtype=np.int64),
        test=np.array(split_indices["test"], dtype=np.int64),
    )

    index_to_split = {
        idx: split for split, indices in split_indices.items() for idx in indices
    }
    with (split_dir / "split_manifest.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "split",
                "global_index",
                "dataset",
                "local_index",
                "label",
                "class_name",
                "group_id",
                "record",
            ],
        )
        writer.writeheader()
        for ref in refs:
            writer.writerow(
                {
                    "split": index_to_split[ref.global_index],
                    "global_index": ref.global_index,
                    "dataset": ref.dataset,
                    "local_index": ref.local_index,
                    "label": ref.label,
                    "class_name": CLASS_NAMES[ref.label],
                    "group_id": ref.group_id,
                    "record": ref.record,
                }
            )

    summary = {}
    for split, indices in split_indices.items():
        labels = np.array([refs[i].label for i in indices])
        summary[split] = {
            "n_samples": int(len(indices)),
            "class_counts": {
                CLASS_NAMES[i]: int((labels == i).sum()) for i in range(len(CLASS_NAMES))
            },
            "n_groups": int(len({refs[i].group_id for i in indices})),
        }
    (split_dir / "split_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def assert_no_leakage(refs: list[SampleRef], split_indices: dict[str, list[int]]) -> None:
    split_groups = {
        split: {refs[i].group_id for i in indices}
        for split, indices in split_indices.items()
    }
    overlaps = {
        "train_val": split_groups["train"] & split_groups["val"],
        "train_test": split_groups["train"] & split_groups["test"],
        "val_test": split_groups["val"] & split_groups["test"],
    }
    bad = {k: sorted(v)[:10] for k, v in overlaps.items() if v}
    if bad:
        raise RuntimeError(f"Group leakage detected: {bad}")


def make_loader(
    datasets: dict[str, dict[str, np.ndarray]],
    refs: list[SampleRef],
    indices: list[int],
    batch_size: int,
    train: bool,
    num_workers: int,
) -> DataLoader:
    split_refs = [refs[i] for i in indices]
    dataset = CombinedECGDataset(datasets, split_refs)
    if train:
        labels = np.array([ref.label for ref in split_refs], dtype=np.int64)
        class_counts = np.bincount(labels, minlength=len(CLASS_NAMES)).clip(min=1)
        sample_weights = 1.0 / class_counts[labels]
        sampler = WeightedRandomSampler(sample_weights, len(sample_weights), replacement=True)
        return DataLoader(
            dataset,
            batch_size=batch_size,
            sampler=sampler,
            num_workers=num_workers,
            pin_memory=torch.cuda.is_available(),
        )
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=torch.cuda.is_available(),
    )


def class_weights_from_indices(refs: list[SampleRef], indices: list[int], device: str) -> torch.Tensor:
    labels = np.array([refs[i].label for i in indices], dtype=np.int64)
    counts = np.bincount(labels, minlength=len(CLASS_NAMES)).astype(np.float32)
    weights = counts.sum() / (len(CLASS_NAMES) * np.clip(counts, 1.0, None))
    return torch.tensor(weights, dtype=torch.float32, device=device)


def run_epoch(model, loader, criterion, device, optimizer=None) -> dict:
    is_train = optimizer is not None
    model.train(is_train)
    total_loss = 0.0
    all_labels = []
    all_preds = []

    for signals, qrs7, labels in loader:
        signals = signals.to(device, non_blocking=True)
        qrs7 = qrs7.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)

        with torch.set_grad_enabled(is_train):
            logits, _ = model(signals, qrs7)
            loss = criterion(logits, labels)
            if is_train:
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()

        total_loss += float(loss.item()) * labels.size(0)
        all_labels.extend(labels.detach().cpu().numpy())
        all_preds.extend(logits.argmax(dim=-1).detach().cpu().numpy())

    labels_np = np.array(all_labels)
    preds_np = np.array(all_preds)
    return {
        "loss": total_loss / max(1, len(loader.dataset)),
        "accuracy": float(accuracy_score(labels_np, preds_np)),
        "macro_f1": float(f1_score(labels_np, preds_np, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(labels_np, preds_np, average="weighted", zero_division=0)),
    }


@torch.no_grad()
def predict_split(model, loader, device) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    model.eval()
    all_labels = []
    all_probs = []
    for signals, qrs7, labels in loader:
        signals = signals.to(device, non_blocking=True)
        qrs7 = qrs7.to(device, non_blocking=True)
        logits, _ = model(signals, qrs7)
        all_probs.append(F.softmax(logits, dim=-1).cpu().numpy())
        all_labels.extend(labels.numpy())
    probs = np.concatenate(all_probs, axis=0)
    labels = np.array(all_labels, dtype=np.int64)
    preds = probs.argmax(axis=1)
    return labels, preds, probs


def evaluate_predictions(labels: np.ndarray, preds: np.ndarray, probs: np.ndarray) -> dict:
    labels_oh = np.eye(len(CLASS_NAMES))[labels]
    cm = confusion_matrix(labels, preds, labels=list(range(len(CLASS_NAMES))))
    support = np.bincount(labels, minlength=len(CLASS_NAMES))
    precision = precision_score(labels, preds, average=None, zero_division=0)
    recall = recall_score(labels, preds, average=None, zero_division=0)
    f1 = f1_score(labels, preds, average=None, zero_division=0)

    per_class = {}
    for i, name in enumerate(CLASS_NAMES):
        try:
            auroc = float(roc_auc_score(labels_oh[:, i], probs[:, i]))
        except ValueError:
            auroc = float("nan")
        try:
            avg_precision = float(average_precision_score(labels_oh[:, i], probs[:, i]))
        except ValueError:
            avg_precision = float("nan")
        per_class[name] = {
            "precision": float(precision[i]),
            "recall": float(recall[i]),
            "f1": float(f1[i]),
            "support": int(support[i]),
            "auroc": auroc,
            "avg_precision": avg_precision,
        }

    try:
        auroc_macro = float(roc_auc_score(labels_oh, probs, multi_class="ovr", average="macro"))
    except ValueError:
        auroc_macro = float("nan")

    return {
        "overall": {
            "accuracy": float(accuracy_score(labels, preds)),
            "macro_f1": float(f1_score(labels, preds, average="macro", zero_division=0)),
            "weighted_f1": float(f1_score(labels, preds, average="weighted", zero_division=0)),
            "cohen_kappa": float(cohen_kappa_score(labels, preds)),
            "matthews_cc": float(matthews_corrcoef(labels, preds)),
            "auroc_macro_ovr": auroc_macro,
            "n_samples": int(len(labels)),
        },
        "per_class": per_class,
        "confusion_matrix": cm.tolist(),
        "classification_report": classification_report(
            labels, preds, labels=list(range(len(CLASS_NAMES))), target_names=CLASS_NAMES, zero_division=0
        ),
    }


def save_test_outputs(out_dir: Path, labels: np.ndarray, preds: np.ndarray, probs: np.ndarray, report: dict) -> None:
    results_dir = out_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "test_metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    pd.DataFrame(report["confusion_matrix"], index=CLASS_NAMES, columns=CLASS_NAMES).to_csv(
        results_dir / "test_confusion_matrix.csv"
    )
    pd.DataFrame.from_dict(report["per_class"], orient="index").to_csv(results_dir / "test_per_class.csv")
    pred_df = pd.DataFrame(probs, columns=[f"prob_{name}" for name in CLASS_NAMES])
    pred_df.insert(0, "pred", preds)
    pred_df.insert(0, "label", labels)
    pred_df.to_csv(results_dir / "test_predictions.csv", index=False)


def save_checkpoint(path: Path, model, optimizer, scheduler, epoch: int, best_metric: float, args, extra: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "epoch": epoch,
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "scheduler_state_dict": scheduler.state_dict() if scheduler is not None else None,
            "best_metric": best_metric,
            "args": vars(args),
            "class_names": CLASS_NAMES,
            **extra,
        },
        path,
    )


def append_epoch_logs(out_dir: Path, row: dict) -> None:
    logs_dir = out_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    csv_path = logs_dir / "epoch_logs.csv"
    jsonl_path = logs_dir / "epoch_logs.jsonl"
    write_header = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(row)
    with jsonl_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=Path("runs") / "fixed_ptbxl_cinc2020")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--resume", type=Path, default=None)
    parser.add_argument("--base-dir", type=Path, default=Path.cwd())
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    seed_everything(args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "config.json").write_text(json.dumps(vars(args), default=str, indent=2), encoding="utf-8")

    datasets = {}
    refs: list[SampleRef] = []
    for name, rel_path in DEFAULT_DATASETS.items():
        data, ds_refs = load_dataset(args.base_dir, name, rel_path)
        datasets[name] = data
        refs.extend(ds_refs)
    refs = relabel_global_indices(refs)

    split_indices = make_fixed_splits(refs, args.seed)
    assert_no_leakage(refs, split_indices)
    save_splits(args.output_dir, refs, split_indices)

    train_loader = make_loader(datasets, refs, split_indices["train"], args.batch_size, True, args.num_workers)
    val_loader = make_loader(datasets, refs, split_indices["val"], args.batch_size, False, args.num_workers)
    test_loader = make_loader(datasets, refs, split_indices["test"], args.batch_size, False, args.num_workers)

    device = torch.device(args.device)
    model = build_model(n_leads=12, n_classes=len(CLASS_NAMES), qrs_aux_dim=64, device=str(device))
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="max", factor=0.5, patience=3, min_lr=1e-6
    )
    criterion = nn.CrossEntropyLoss(weight=class_weights_from_indices(refs, split_indices["train"], str(device)))

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
        "n_parameters": count_parameters(model),
        "device": str(device),
        "datasets": list(DEFAULT_DATASETS),
        "class_names": CLASS_NAMES,
    }
    (args.output_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2), flush=True)

    epochs_without_improvement = 0
    for epoch in range(start_epoch, args.epochs + 1):
        t0 = time.time()
        train_metrics = run_epoch(model, train_loader, criterion, device, optimizer=optimizer)
        val_metrics = run_epoch(model, val_loader, criterion, device, optimizer=None)
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
        append_epoch_logs(args.output_dir, row)
        print(json.dumps(row), flush=True)

        checkpoint_extra = {"epoch_metrics": row}
        save_checkpoint(
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
            save_checkpoint(
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

    labels, preds, probs = predict_split(model, test_loader, device)
    report = evaluate_predictions(labels, preds, probs)
    save_test_outputs(args.output_dir, labels, preds, probs, report)
    print(json.dumps({"final_test": report["overall"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
