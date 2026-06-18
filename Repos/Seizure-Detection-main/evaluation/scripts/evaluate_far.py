"""Compute false-alert rate from one or more deployment alert CSV logs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


MODE_THRESHOLDS = {
    "safety": 0.88,
    "monitor": 0.49,
    "screening": 0.12,
}
ALERT_GAP_SEC = 30.0


def load_alert_log(path: str) -> list[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                rows.append({
                    "time_sec": float(row.get("time_sec", 0) or 0),
                    "seizure_signal": float(row.get("seizure_signal", 0) or 0),
                    "status": row.get("status", "NORMAL"),
                })
            except ValueError:
                continue
    return rows


def count_events(rows: list[dict], threshold: float) -> tuple[int, list[float]]:
    events = []
    last_event_t = None
    for row in rows:
        if row["seizure_signal"] < threshold:
            continue
        t = row["time_sec"]
        if last_event_t is None or t - last_event_t > ALERT_GAP_SEC:
            events.append(t)
        last_event_t = t
    return len(events), events


def summarize_one(path: str, modes: list[str], threshold_override: float | None = None) -> dict:
    rows = load_alert_log(path)
    if not rows:
        duration_sec = 0.0
    else:
        duration_sec = max(row["time_sec"] for row in rows) - min(row["time_sec"] for row in rows)
    hours = max(duration_sec / 3600.0, 1e-9)
    per_mode = {}
    for mode in modes:
        threshold = MODE_THRESHOLDS[mode] if threshold_override is None else float(threshold_override)
        n_events, event_times = count_events(rows, threshold)
        per_mode[mode] = {
            "threshold": threshold,
            "false_alerts": n_events,
            "FAR_per_hour": n_events / hours,
            "event_times_sec": event_times,
            "peak_signal": max((row["seizure_signal"] for row in rows), default=0.0),
        }
    return {
        "path": path,
        "monitoring_sec": duration_sec,
        "per_mode": per_mode,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("logs", nargs="+", help="Alert log CSV files")
    parser.add_argument("--mode", nargs="+", default=["safety", "monitor", "screening"],
                        choices=list(MODE_THRESHOLDS))
    parser.add_argument("--threshold-override", type=float, default=None,
                        help="Evaluate all selected modes at this explicit signal threshold.")
    parser.add_argument("--out-json", default="")
    args = parser.parse_args()

    per_log = [summarize_one(path, args.mode, args.threshold_override) for path in args.logs]
    total_sec = sum(item["monitoring_sec"] for item in per_log)
    total_h = max(total_sec / 3600.0, 1e-9)

    aggregate = {}
    for mode in args.mode:
        events = sum(item["per_mode"][mode]["false_alerts"] for item in per_log)
        threshold = MODE_THRESHOLDS[mode] if args.threshold_override is None else float(args.threshold_override)
        aggregate[mode] = {
            "threshold": threshold,
            "false_alerts": events,
            "FAR_per_hour": events / total_h,
            "peak_signal": max((item["per_mode"][mode]["peak_signal"] for item in per_log), default=0.0),
        }
        print(
            f"[{mode:10s}] thr={threshold:.2f} "
            f"false_alerts={events:3d} FAR={events / total_h:.3f}/h over {total_h:.3f} h"
        )

    result = {
        "total_monitoring_h": total_h,
        "logs": per_log,
        "per_mode": aggregate,
    }

    if args.out_json:
        out = Path(args.out_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
