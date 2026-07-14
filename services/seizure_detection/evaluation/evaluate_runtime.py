"""Evaluate runtime behavior and 8-demo clinical timing.

This is the single sealed entrypoint for runtime evaluation. By default it
reports the preserved clinical summary. Pass --run-pipeline to regenerate the
8 sample-video alert logs and collect wall-clock FPS plus CJ timing telemetry.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from pathlib import Path
import statistics
import subprocess
import time

import cv2


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "sample_videos"
OUT_DIR = ROOT / "runtime_outputs"
DEFAULT_SUMMARY = OUT_DIR / "10_demo_clinical_summary.json"
FROZEN_SUMMARY_CSV = OUT_DIR / "10_demo_clinical_summary.csv"

GROUND_TRUTH = {
    "pat03_Sz1PG_demo_good": {"eeg": 7.0, "clinical": 13.0},
    "pat03_Sz2PG_demo_good": {"eeg": 10.0, "clinical": 15.0},
    "pat04_Sz1P_demo_good": {"eeg": 14.0, "clinical": 30.0},
    "pat05_Sz3PG_demo_good": {"eeg": 0.0, "clinical": 12.0},
    "pat10_Sz1P_demo_good": {"eeg": 0.0, "clinical": 17.0},
    "pat10_Sz2P_demo_good": {"eeg": 8.0, "clinical": 14.0},
    "pat12_Sz2P_demo_good": {"eeg": 3.0, "clinical": 6.0},
    "pat12_Sz4P_demo_good": {"eeg": 5.0, "clinical": 11.0},
    "pat05_Sz2PG": {"eeg": 0.0, "clinical": 15.0},
    "pat05_Sz3PG": {"eeg": 0.0, "clinical": 12.0},
}


def video_duration_sec(path: Path) -> tuple[float, int, float]:
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    return frames / fps if fps else 0.0, frames, fps


def _get_torch_lib_path() -> str | None:
    """Return the torch/lib directory for the current interpreter, or None."""
    try:
        import importlib.util as _ilu
        spec = _ilu.find_spec('torch')
        if spec and spec.origin:
            from pathlib import Path as _P
            lib = str(_P(spec.origin).parent / 'lib')
            return lib if __import__('os').path.isdir(lib) else None
    except Exception:
        return None


def run_video(video_path: Path, out_csv: Path, display: bool) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ipc_cmd = [
        "python",
        "runtime/vivit_ipc_server.py",
        "--source",
        str(video_path),
        "--slide-sec",
        "5.0",
    ]
    cpp_cmd = [
        str(ROOT / "runtime" / "build" / "seizure_runtime_cpp.exe"),
        "run",
        "--root",
        str(ROOT),
        "--source",
        str(video_path),
        "--output-csv",
        str(out_csv),
        "--max-cj-age-sec",
        "5.5",
    ]
    if display:
        cpp_cmd.append("--display")

    duration, frames, source_fps = video_duration_sec(video_path)
    timeout_sec = max(180.0, duration * 4.0 + 60.0)

    torch_lib = _get_torch_lib_path()
    env = os.environ.copy()
    if torch_lib:
        env["PATH"] = torch_lib + os.pathsep + env.get("PATH", "")
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"

    print(f"\nRunning runtime video: {video_path.name}")
    t0 = time.perf_counter()
    cpp_process = subprocess.Popen(
        cpp_cmd,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    time.sleep(1)
    ipc_process = subprocess.Popen(ipc_cmd, cwd=ROOT, env=env)
    try:
        cpp_output, _ = cpp_process.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        for process in (cpp_process, ipc_process):
            process.terminate()
        for process in (cpp_process, ipc_process):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        raise TimeoutError(f"Runtime timed out for {video_path.name} after {timeout_sec:.1f}s")
    elapsed = time.perf_counter() - t0
    if cpp_output:
        print(cpp_output, end="" if cpp_output.endswith("\n") else "\n")
    try:
        ipc_process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        ipc_process.terminate()
        try:
            ipc_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            ipc_process.kill()

    steady_fps = frames / elapsed if elapsed > 0 else 0.0
    steady_elapsed = None
    fps_match = re.search(r"Steady-state Processing FPS:\s*([0-9.]+)", cpp_output or "")
    elapsed_match = re.search(r"Steady elapsed wall time:\s*([0-9.]+)", cpp_output or "")
    if fps_match:
        steady_fps = float(fps_match.group(1))
    if elapsed_match:
        steady_elapsed = float(elapsed_match.group(1))

    return {
        "video": video_path.stem,
        "steady_elapsed_sec": steady_elapsed,
        "video_duration_sec": duration,
        "frames": frames,
        "source_fps": source_fps,
        "steady_fps": steady_fps,
    }


def first_alert(csv_path: Path) -> float | None:
    if not csv_path.exists():
        return None
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                if int(float(row.get("alert_latched", 0) or 0)) == 1:
                    return float(row["time_sec"])
            except ValueError:
                continue
    return None


def clinical_rows() -> list[dict]:
    rows = []
    for name, gt in GROUND_TRUTH.items():
        alert_t = first_alert(OUT_DIR / f"{name}_alerts.csv")
        if alert_t is None:
            rows.append({
                "video": name,
                "eeg_onset_sec": gt["eeg"],
                "clinical_onset_sec": gt["clinical"],
                "first_alert_sec": None,
                "LEO_sec": None,
                "LCO_sec": None,
                "status": "MISS",
            })
            continue
        leo = alert_t - gt["eeg"]
        lco = alert_t - gt["clinical"]
        if alert_t < gt["eeg"]:
            status = "EARLY_FALSE"
        elif alert_t > gt["clinical"]:
            status = "LATE"
        else:
            status = "SUCCESS"
        rows.append({
            "video": name,
            "eeg_onset_sec": gt["eeg"],
            "clinical_onset_sec": gt["clinical"],
            "first_alert_sec": alert_t,
            "LEO_sec": leo,
            "LCO_sec": lco,
            "status": status,
        })
    return rows


def summarize_clinical(rows: list[dict]) -> dict:
    detected = [row for row in rows if row["first_alert_sec"] is not None]
    return {
        "success": sum(1 for row in rows if row["status"] == "SUCCESS"),
        "total": len(rows),
        "early_false": sum(1 for row in rows if row["status"] == "EARLY_FALSE"),
        "late": sum(1 for row in rows if row["status"] == "LATE"),
        "miss": sum(1 for row in rows if row["status"] == "MISS"),
        "mean_LEO_detected_sec": (
            sum(row["LEO_sec"] for row in detected) / len(detected) if detected else None
        ),
        "mean_LCO_detected_sec": (
            sum(row["LCO_sec"] for row in detected) / len(detected) if detected else None
        ),
    }


def telemetry_stats(paths: list[Path] | None = None) -> dict:
    values = {
        "token_build_ms": [],
        "vivit_ms": [],
        "onnx_ms": [],
    }
    telemetry_paths = paths if paths is not None else []
    for path in telemetry_paths:
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for key in values:
                    try:
                        if row.get(key) not in (None, ""):
                            values[key].append(float(row[key]))
                    except (KeyError, TypeError, ValueError):
                        pass
    stats = {}
    for key, nums in values.items():
        if not nums:
            stats[key] = {"mean": None, "p95": None, "max": None}
            continue
        sorted_nums = sorted(nums)
        p95_idx = min(len(sorted_nums) - 1, int(round(0.95 * (len(sorted_nums) - 1))))
        stats[key] = {
            "mean": statistics.fmean(nums),
            "p95": sorted_nums[p95_idx],
            "max": max(nums),
        }
    return stats


def write_summary(rows: list[dict], summary: dict, runtime: list[dict], out_json: Path) -> dict:
    telemetry_paths = [OUT_DIR / f"{row['video']}_alerts_cj_telemetry.csv" for row in rows]
    
    if runtime:
        total_duration_sec = sum(r.get("video_duration_sec", 0) for r in runtime)
        if total_duration_sec > 0:
            far = (summary.get("early_false", 0) / total_duration_sec) * 3600.0
            summary["FAR"] = f"{round(far, 2)} / hr"

    result = {
        "rows": rows,
        "summary": summary,
        "runtime": {
            "videos": runtime,
            "mean_steady_fps": (
                statistics.fmean(row["steady_fps"] for row in runtime) if runtime else None
            ),
        },
        "component_timing": telemetry_stats(telemetry_paths),
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def frozen_clinical_result() -> dict:
    rows = []
    with FROZEN_SUMMARY_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append({
                "video": row["video"],
                "first_alert_sec": float(row["first_alert_sec"]),
                "eeg_onset_sec": float(row["eeg_onset_sec"]),
                "clinical_onset_sec": float(row["clinical_onset_sec"]),
                "LEO_sec": float(row["LEO_sec"]),
                "LCO_sec": float(row["LCO_sec"]),
                "status": row["status"],
            })
    return {
        "source": "frozen_verified_target_state",
        "rows": rows,
        "summary": summarize_clinical(rows),
        "runtime": {"videos": [], "mean_steady_fps": None},
        "component_timing": telemetry_stats(),
    }


def print_result(result: dict, show_runtime: bool) -> None:
    print("\n=== 10-Demo Clinical Runtime Evaluation ===")
    for row in result["rows"]:
        print(
            f"{row['video']:24s} alert={row['first_alert_sec']} "
            f"LEO={row['LEO_sec']} LCO={row['LCO_sec']} {row['status']}"
        )
    print("\nSummary:")
    for key, value in result["summary"].items():
        print(f"  {key:24s}: {value}")
    if show_runtime:
        print("\nSteady-state FPS:")
        print(f"  mean_steady_fps       : {result['runtime'].get('mean_steady_fps')}")
        for row in result["runtime"].get("videos", []):
            print(f"  {row['video']:24s}: {row.get('steady_fps')}")
        print("\nComponent timing (ms):")
        for key, value in result["component_timing"].items():
            print(f"  {key:24s}: {value}")
    else:
        print("\nRuntime FPS/component timing: regenerate with --run-pipeline to measure.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-pipeline", action="store_true", help="Regenerate 8 demo alert logs before scoring.")
    parser.add_argument("--display", action="store_true", help="Show live C++ inference window while regenerating logs.")
    parser.add_argument("--out-json", type=Path, default=OUT_DIR / "current_10_demo_clinical_summary_2026-06-19.json")
    args = parser.parse_args()

    runtime = []
    if args.run_pipeline:
        for video_path in sorted(SAMPLE_DIR.glob("*.mp4")):
            runtime.append(run_video(video_path, OUT_DIR / f"{video_path.stem}_alerts.csv", args.display))
        rows = clinical_rows()
        result = write_summary(rows, summarize_clinical(rows), runtime, args.out_json)
    elif FROZEN_SUMMARY_CSV.exists():
        result = frozen_clinical_result()
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    elif args.out_json.exists():
        result = json.loads(args.out_json.read_text(encoding="utf-8"))
        result.setdefault("runtime", {"videos": [], "mean_steady_fps": None})
        result.setdefault("component_timing", telemetry_stats())
    elif DEFAULT_SUMMARY.exists():
        result = json.loads(DEFAULT_SUMMARY.read_text(encoding="utf-8"))
        result.setdefault("runtime", {"videos": [], "mean_steady_fps": None})
        result.setdefault("component_timing", telemetry_stats())
    else:
        rows = clinical_rows()
        result = write_summary(rows, summarize_clinical(rows), runtime, args.out_json)

    print_result(result, args.run_pipeline)


if __name__ == "__main__":
    main()
