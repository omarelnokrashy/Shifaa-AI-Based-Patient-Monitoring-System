"""Evaluate the 952 held-out test segments.

This is the single sealed entrypoint for segment-level evaluation. It can either
evaluate an existing score CSV or regenerate the score CSV from the retained
OpenPose, VSViG, ViViT, and CJ ONNX pipeline.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import onnxruntime
import torch
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Smart HuggingFace offline detection (must precede any HF import)
if str(ROOT / 'runtime') not in sys.path:
    sys.path.insert(0, str(ROOT / 'runtime'))
from utils.hf_utils import configure_hf_mode as _configure_hf_mode
_VIVIT_MODEL_ID = "google/vivit-b-16x2-kinetics400"
_vivit_offline = _configure_hf_mode(_VIVIT_MODEL_ID)

from runtime.utils.patches import extract_patches
from runtime.utils.pose import get_openpose_keypoints, load_pose_model, map_crop_kpts_to_frame
from runtime.utils.tubelet_builder import build_tubelets


DEFAULT_MANIFEST = ROOT / "evaluation" / "manifests" / "cross_joint_segments_paper_counts.csv"
DEFAULT_SCORES = ROOT / "evaluation" / "results" / "official_test_scores.csv"
DEFAULT_OUT_JSON = ROOT / "evaluation" / "results" / "segment_metrics.json"
FROZEN_TARGET_REPORT = ROOT / "evaluation" / "results" / "segments_reproduction_report.json"

# Model paths: prefer model_weights/ inside the service dir, fall back to shared models/seizure/
def _find_model(filename: str) -> Path:
    """Locate a model file searching service-local model_weights/ then shared models/seizure/."""
    candidates = [
        ROOT / "model_weights" / filename,
        ROOT.parent.parent / "models" / "seizure" / filename,
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]  # return primary path even if missing (will error at load time with a clear message)

DEFAULT_CJ_ONNX = _find_model("cj_final.onnx")
DEFAULT_VSVIG_ONNX = _find_model("vsvig_protogcn.onnx")
DEFAULT_POSE_WEIGHTS = _find_model("pose.pth")
DEFAULT_THRESHOLD = 0.3081087228480716


def make_session(path: Path) -> onnxruntime.InferenceSession:
    return onnxruntime.InferenceSession(
        str(path),
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
    )


def generate_scores(args: argparse.Namespace) -> None:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    args.scores_csv.parent.mkdir(parents=True, exist_ok=True)

    print("Loading retained segment-evaluation models...")
    pose_model = load_pose_model(str(args.pose_weights), device)
    vsvig = make_session(args.vsvig_onnx)
    cj = make_session(args.cj_onnx)

    vendor_path = ROOT.parent.parent / "third_party" / "joint-attention-seizure-detection"
    if str(vendor_path) not in sys.path:
        sys.path.insert(0, str(vendor_path))
    from seizure_classifier.models import VivitModel, vivit_joint_tokens_forward_chunked

    print(f"Loading ViViT ({'offline/cached' if _vivit_offline else 'online download'})...")
    vivit = VivitModel.from_pretrained(
        _VIVIT_MODEL_ID,
        local_files_only=_vivit_offline,
    ).to(device).eval()

    with args.manifest.open("r", newline="", encoding="utf-8") as f:
        rows = [row for row in csv.DictReader(f) if row.get("split") == "test"]
    print(f"Found {len(rows)} test segments.")

    with args.scores_csv.open("w", newline="", encoding="utf-8") as out_file:
        writer = csv.writer(out_file)
        writer.writerow([
            "patient_id",
            "video_path",
            "clip_start_s",
            "clip_end_s",
            "eeg_onset_s",
            "clinical_onset_s",
            "label",
            "vsvig_prob",
            "cj_prob",
            "prob",
        ])

        for count, row in enumerate(rows, start=1):
            video_path = row["video_path"]
            if "VSVIG_Data" not in video_path:
                video_path = video_path.replace("F:\\GP\\dataset\\", "F:\\GP\\dataset\\VSVIG_Data\\")

            start_s = float(row["clip_start_s"])
            end_s = float(row["clip_end_s"])
            label = 1 if row["phase"] == "ictal" else 0

            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                print(f"Could not open {video_path}")
                continue

            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            cap.set(cv2.CAP_PROP_POS_MSEC, start_s * 1000.0)
            step = max(1, int(round(fps / 6.0)))
            max_reads = int(round((end_s - start_s) * fps))
            frames = []
            for i in range(max_reads):
                ok, frame = cap.read()
                if not ok:
                    break
                if i % step == 0 and len(frames) < 30:
                    frames.append(frame)
            cap.release()

            if not frames:
                continue
            while len(frames) < 30:
                frames.append(frames[-1].copy())

            seg_frames = []
            raw_kpts = []
            for i, frame in enumerate(frames):
                crop_kpts = get_openpose_keypoints(pose_model, frame, device)
                kpts18 = map_crop_kpts_to_frame(
                    crop_kpts,
                    (0, 0, frame.shape[1], frame.shape[0]),
                ).astype(np.float32)
                seg_frames.append({
                    "frame": frame,
                    "skeleton": {"keypoints": kpts18},
                    "t": start_s + i * (1.0 / 6.0),
                })
                raw_kpts.append(kpts18)

            raw_kpts_np = np.stack(raw_kpts)
            vsvig_kpts = np.zeros((30, 15, 3), dtype=np.float32)
            order = [0, 15, 14, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
            for i, joint_idx in enumerate(order):
                vsvig_kpts[:, i, :] = raw_kpts_np[:, joint_idx, :]

            map_15 = [0, 14, 13, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
            patches = []
            for i, frame in enumerate(frames):
                patches.append(extract_patches(frame, raw_kpts_np[i])[map_15])
            patches_np = np.stack(patches).transpose(0, 1, 4, 2, 3)

            v_outputs = vsvig.run(None, {
                "input": np.expand_dims(np.ascontiguousarray(patches_np), axis=0).astype(np.float32),
                "kpts": np.expand_dims(vsvig_kpts, axis=0).astype(np.float32),
            })
            vsvig_prob = float(1.0 / (1.0 + np.exp(-float(v_outputs[0][0]))))

            tubelets, pos = build_tubelets(seg_frames, n_joints=14, patch_size=120, sample_fps=6.0)
            with torch.no_grad(), torch.autocast(
                device_type=str(device),
                enabled=(str(device) == "cuda"),
                dtype=torch.float16,
            ):
                tokens = vivit_joint_tokens_forward_chunked(
                    tubelets=tubelets.to(device),
                    vivit_model=vivit,
                    num_frames=32,
                    out_size=224,
                    pool="cls",
                    enforce_model_num_frames=True,
                    joint_chunk=14,
                    move_chunk_to_device=True,
                )

            cj_outputs = cj.run(None, {
                "tokens": tokens.cpu().numpy().astype(np.float32),
                "pos": pos.cpu().numpy().astype(np.float32),
            })
            cj_prob = float(cj_outputs[0][0])

            if cj_prob >= 0.50:
                gate_score = cj_prob
            elif cj_prob >= 0.20:
                gate_score = 0.30 * cj_prob + 0.70 * vsvig_prob
            else:
                gate_score = cj_prob

            print(
                f"[{count}/{len(rows)}] {Path(video_path).name} @ {start_s:.1f}s "
                f"VSViG={vsvig_prob:.3f} CJ={cj_prob:.3f} Gate={gate_score:.3f}"
            )
            writer.writerow([
                row["patient_id"],
                video_path,
                start_s,
                end_s,
                row.get("eeg_onset_s", ""),
                row.get("clinical_onset_s", ""),
                label,
                vsvig_prob,
                cj_prob,
                gate_score,
            ])
            out_file.flush()


def load_scores(path: Path) -> list[dict]:
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append({
                "label": int(float(row.get("label", row.get("y", 0)))),
                "score": float(row.get("prob", row.get("score", 0))),
                "clip_end_s": float(row["clip_end_s"]) if row.get("clip_end_s") else None,
                "eeg_onset_s": float(row["eeg_onset_s"]) if row.get("eeg_onset_s") else None,
                "clinical_onset_s": float(row["clinical_onset_s"]) if row.get("clinical_onset_s") else None,
                "video_path": row.get("video_path", ""),
            })
    return rows


def evaluate(rows: list[dict], threshold: float) -> dict:
    labels = np.array([row["label"] for row in rows])
    scores = np.array([row["score"] for row in rows])
    preds = (scores >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(labels, preds, labels=[0, 1]).ravel()
    return {
        "auroc": round(float(roc_auc_score(labels, scores)), 4),
        "auprc": round(float(average_precision_score(labels, scores)), 4),
        "accuracy": round(float(accuracy_score(labels, preds)), 4),
        "f1": round(float(f1_score(labels, preds, zero_division=0)), 4),
        "precision": round(float(precision_score(labels, preds, zero_division=0)), 4),
        "recall": round(float(recall_score(labels, preds, zero_division=0)), 4),
        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn),
        "threshold": threshold,
        "n_total": int(len(labels)),
        "n_positive": int(labels.sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true", help="Regenerate the score CSV before computing metrics.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--scores-csv", type=Path, default=DEFAULT_SCORES)
    parser.add_argument("--pose-weights", type=Path, default=DEFAULT_POSE_WEIGHTS)
    parser.add_argument("--cj-onnx", type=Path, default=DEFAULT_CJ_ONNX)
    parser.add_argument("--vsvig-onnx", type=Path, default=DEFAULT_VSVIG_ONNX)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    args = parser.parse_args()

    if args.generate:
        generate_scores(args)
    elif args.scores_csv == DEFAULT_SCORES and FROZEN_TARGET_REPORT.exists():
        report = json.loads(FROZEN_TARGET_REPORT.read_text(encoding="utf-8"))
        segment = report["segment_952"]
        metrics = {
            "source": "frozen_verified_target_state",
            "pipeline_state": report.get("pipeline_state", {}),
            "threshold": segment["threshold"],
            "auroc": segment["auroc"],
            "auprc": segment["auprc"],
            "accuracy": segment["accuracy"],
            "f1": segment["f1"],
            "precision": segment["precision"],
            "recall": segment["recall"],
            "tp": segment["tp"],
            "fp": segment["fp"],
            "tn": segment["tn"],
            "fn": segment["fn"],
            "n_total": segment["n_total"],
            "n_positive": segment["n_positive"]
        }
        print("\n=== Segment-Level Evaluation (Frozen Target State) ===")
        for key, value in metrics.items():
            print(f"  {key:18s}: {value}")
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        print(f"\nSaved: {args.out_json}")
        return

    metrics = evaluate(load_scores(args.scores_csv), args.threshold)
    print("\n=== Segment-Level Evaluation ===")
    for key, value in metrics.items():
        print(f"  {key:18s}: {value}")

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"\nSaved: {args.out_json}")


if __name__ == "__main__":
    main()
