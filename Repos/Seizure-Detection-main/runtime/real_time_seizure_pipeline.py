"""Deployable entrypoint backed by the validated production inference engine."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PACKAGE_ROOT.parent
for root in (str(WORKSPACE_ROOT), str(PACKAGE_ROOT)):
    if root not in sys.path:
        sys.path.insert(0, root)

from runtime.utils.config import load_config
from runtime.utils.paths import resolve_path, resolve_weight


MODE_THRESHOLDS = {
    "safety": 0.88,
    "monitor": 0.49,
    "screening": 0.12,
}


def _finite_or_none(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and out not in (float("inf"), float("-inf")) else None


def bind_deployment_series_gate(live):
    """Use the deployable package's frozen CJ + VSViG gate in the shared engine."""

    def deployment_series_gate_signal(cj_prob, vsvig_ap, cj_age_sec, alert_active=False):
        cj_prob = _finite_or_none(cj_prob)
        vsvig_ap = _finite_or_none(vsvig_ap)
        cj_age_sec = _finite_or_none(cj_age_sec)

        max_age = (
            float(getattr(live, "CJ_ALERT_MAX_RESULT_AGE_SEC", 60.0))
            if alert_active
            else float(getattr(live, "CJ_MAX_RESULT_AGE_SEC", 15.0))
        )
        if cj_prob is None or cj_age_sec is None or cj_age_sec > max_age:
            if vsvig_ap is None:
                return 0.0, "CJ_PENDING"
            return max(0.0, vsvig_ap), "CJ_PENDING" if cj_prob is None else "VSViG_AP"

        cj_prob = max(0.0, min(1.0, cj_prob))
        if vsvig_ap is not None:
            vsvig_ap = max(0.0, vsvig_ap)

        if cj_prob >= 0.50:
            return cj_prob, "CJ"

        gate = float(getattr(live, "CJ_GATE", 0.20))
        alpha = float(getattr(live, "CJ_ALPHA", 0.30))
        if cj_prob >= gate:
            vsvig_term = cj_prob if vsvig_ap is None else vsvig_ap
            score = alpha * cj_prob + (1.0 - alpha) * vsvig_term
            return max(0.0, score), "BLEND"

        return cj_prob, "CJ_LOW"

    live.series_gate_signal = deployment_series_gate_signal


def parse_args():
    parser = argparse.ArgumentParser(description="Real-time seizure detection pipeline")
    parser.add_argument("--source", default="", help="Camera index, video path, or RTSP URL")
    parser.add_argument("--source-list", default="", help="Optional text file with one video path/source per line for persistent batch inference.")
    parser.add_argument("--output", default="", help="Optional annotated AVI output path")
    parser.add_argument("--mode", default="monitor", choices=list(MODE_THRESHOLDS))
    parser.add_argument("--config", default=str(PACKAGE_ROOT / "configs" / "default.yaml"))
    parser.add_argument("--bed-roi", default="", help="Optional ROI: x1,y1,x2,y2")
    parser.add_argument("--alert-log", default="", help="Optional per-frame CSV alert log")
    parser.add_argument("--alert-log-dir", default="", help="Directory for per-source alert logs when using --source-list.")
    parser.add_argument("--no-display", action="store_true")
    parser.add_argument("--no-output", action="store_true")
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--patient-fps", type=float, default=5.0)
    parser.add_argument("--alert-hold", type=float, default=30.0)
    parser.add_argument("--use-amp", action="store_true", help="Enable mixed precision. Disabled by default for stable VSViG probabilities.")
    parser.add_argument("--disable-cj-amp", action="store_true", help="Disable mixed precision for the async CJ/ViViT worker.")
    parser.add_argument("--disable-pose-amp", action="store_true", help="Disable mixed precision for OpenPose.")
    parser.add_argument("--disable-cuda-streams", action="store_true", help="Disable separate CUDA streams for main inference and async CJ.")
    parser.add_argument("--fast-skip-decode", action="store_true", help="Use cap.grab() on non-inference frames when display/output are disabled.")
    parser.add_argument("--sync-alert-log", action="store_true", help="Write alert CSV rows synchronously instead of using the background CSV writer.")
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--profile-out", default="")
    parser.add_argument("--disable-cj-async", action="store_true")
    parser.add_argument("--disable-live-vsvig", action="store_true")
    return parser.parse_args()


def _load_sources(args) -> list[str]:
    sources: list[str] = []
    if args.source:
        sources.append(args.source)
    if args.source_list:
        list_path = Path(args.source_list)
        for line in list_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                sources.append(line)
    if not sources:
        raise SystemExit("Provide --source or --source-list.")
    return sources


def _safe_stem(source: str, index: int) -> str:
    text = str(source)
    if text.isdigit():
        return f"camera_{text}"
    path = Path(text)
    stem = path.stem or f"source_{index:03d}"
    parent = path.parent.name
    prefix = f"{parent}_" if parent else ""
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in f"{prefix}{stem}")
    return safe or f"source_{index:03d}"


def main():
    args = parse_args()
    sources = _load_sources(args)
    batch_mode = len(sources) > 1
    cfg = load_config(args.config)

    pose_weights = resolve_weight(cfg, "model_weights_dir", "pose_checkpoint", "pose.pth")
    vsvig_weights = resolve_weight(cfg, "model_weights_dir", "vsvig_checkpoint", "model_paper_finetuned.pth")
    dy_order = resolve_weight(cfg, "model_weights_dir", "vsvig_dy_order", "dy_point_order.pt")
    cj_seed123 = resolve_weight(cfg, "model_weights_dir", "cj_checkpoint_seed123", "cj_fullfit_distilled_w0p5_seed123.pt")
    cj_seed789 = resolve_weight(cfg, "model_weights_dir", "cj_checkpoint_seed789", "cj_fullfit_distilled_w0p5_seed789.pt")
    cj_repo = resolve_path(cfg.get("cj_repo", "vendor/joint-attention-seizure-detection"))
    os.environ["ALERT_MODE"] = args.mode
    os.environ["ENABLE_CJ_ASYNC"] = "0" if args.disable_cj_async else "1"
    os.environ["ENABLE_LIVE_VSVIG"] = "0" if args.disable_live_vsvig else "1"
    os.environ["CJ_CHECKPOINT"] = f"{cj_seed123},{cj_seed789}"
    os.environ["CJ_PAPER_REPO"] = str(cj_repo)
    os.environ["CJ_GATE_MODE"] = "blend_if_suspicious"
    os.environ["CJ_GATE"] = str(cfg.get("gate_lower_bound", 0.20))
    os.environ["CJ_ALPHA"] = str(cfg.get("gate_alpha", 0.30))
    os.environ["CJ_THRESHOLD"] = str(MODE_THRESHOLDS[args.mode])
    os.environ["SEIZURE_DT"] = str(MODE_THRESHOLDS[args.mode])
    os.environ["USE_AMP"] = "1" if args.use_amp else "0"
    os.environ["CJ_USE_AMP"] = "0" if args.disable_cj_amp else ("1" if bool(cfg.get("cj_use_amp", True)) else "0")
    os.environ["POSE_USE_AMP"] = "0" if args.disable_pose_amp else ("1" if bool(cfg.get("pose_use_amp", True)) else "0")
    os.environ["CUDA_STREAMS"] = "0" if args.disable_cuda_streams else ("1" if bool(cfg.get("cuda_streams", True)) else "0")
    os.environ["FAST_SKIP_DECODE"] = "1" if args.fast_skip_decode else "0"
    os.environ["ASYNC_ALERT_LOG"] = "0" if args.sync_alert_log else "1"
    os.environ["PATIENT_BRANCH_FPS"] = str(max(0.1, args.patient_fps))
    os.environ["SEIZURE_ALERT_HOLD_SEC"] = str(max(0.0, args.alert_hold))
    os.environ["POSE_CONFIDENCE_GATE"] = str(cfg.get("pose_conf_gate", 0.10))
    os.environ["POSE_REUSE_MAX_SEC"] = str(cfg.get("pose_reuse_max_sec", 10.0))
    os.environ["DY_POINT_ORDER"] = str(dy_order)
    os.environ["MAX_FRAMES"] = str(max(0, args.max_frames))
    os.environ["DISPLAY_UI"] = "0" if args.no_display else "1"
    os.environ["WRITE_OUTPUT"] = "0" if args.no_output or not args.output else "1"
    os.environ["ALERT_LOG"] = args.alert_log
    os.environ["BED_ROI"] = args.bed_roi
    os.environ["PROFILE_PIPELINE"] = "1" if args.profile else "0"
    os.environ["PROFILE_OUT"] = args.profile_out
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    from runtime import inference as live
    bind_deployment_series_gate(live)

    live.MODEL_WEIGHTS = str(vsvig_weights)
    live.POSE_WEIGHTS = str(pose_weights)
    live.DY_POINT_ORDER = str(dy_order)
    live.CJ_CHECKPOINT = f"{cj_seed123},{cj_seed789}"
    live.CJ_PAPER_REPO = str(cj_repo)
    live.FAST_SKIP_DECODE = args.fast_skip_decode

    if batch_mode:
        alert_dir = Path(args.alert_log_dir or args.alert_log or (PACKAGE_ROOT / "runtime_outputs" / "batch_alert_logs"))
        alert_dir.mkdir(parents=True, exist_ok=True)
    else:
        alert_dir = None

    print("Seizure detection deployment runtime")
    print(f"  source count: {len(sources)}")
    print(f"  mode: {args.mode}")
    print(f"  output AVI: {os.environ['WRITE_OUTPUT'] == '1'}")
    print(f"  pose weights: {live.POSE_WEIGHTS}")
    print(f"  VSViG weights: {live.MODEL_WEIGHTS}")
    print(f"  CJ checkpoints: {live.CJ_CHECKPOINT}")
    print(f"  persistent process: {'on' if batch_mode else 'single source'}")

    for index, source in enumerate(sources, 1):
        safe = _safe_stem(source, index)
        live.VIDEO_PATH = int(source) if str(source).isdigit() else source
        if batch_mode:
            live.ALERT_LOG = str(alert_dir / f"{index:03d}_{safe}_alerts.csv")
            if args.no_output or not args.output:
                live.OUTPUT_PATH = str(PACKAGE_ROOT / "runtime_outputs" / f"{index:03d}_{safe}_output.avi")
            else:
                output_dir = Path(args.output)
                output_dir.mkdir(parents=True, exist_ok=True)
                live.OUTPUT_PATH = str(output_dir / f"{index:03d}_{safe}_output.avi")
        else:
            live.ALERT_LOG = args.alert_log
            live.OUTPUT_PATH = args.output or str(PACKAGE_ROOT / "runtime_outputs" / "output_inference.avi")

        print(f"\n[RUN {index}/{len(sources)}]")
        print(f"  source: {live.VIDEO_PATH}")
        print(f"  alert log: {live.ALERT_LOG or '(off)'}")
        live.main()


if __name__ == "__main__":
    main()
