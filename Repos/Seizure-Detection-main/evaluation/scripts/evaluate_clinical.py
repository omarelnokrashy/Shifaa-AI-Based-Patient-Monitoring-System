"""Summarize clinical event timing from an event CSV or JSON artifact."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def _to_float(value):
    if value in ("", None):
        return None
    return float(value)


def load_rows(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            if "rows" in data:
                return data["rows"]
            for key in ("events", "event_rows"):
                if key in data and isinstance(data[key], list):
                    return data[key]
        if isinstance(data, list):
            return data
        raise SystemExit(f"Could not find event rows in JSON: {path}")

    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def summarize(rows: list[dict]) -> dict:
    detected = []
    for row in rows:
        flag = row.get("detected", True)
        is_detected = flag if isinstance(flag, bool) else str(flag).lower() in ("true", "1", "yes")
        leo = _to_float(row.get("leo_sec"))
        lco = _to_float(row.get("lco_sec"))
        if is_detected and leo is not None and lco is not None:
            detected.append({**row, "leo_sec": leo, "lco_sec": lco})

    early_requested = [row for row in detected if row["leo_sec"] > 0 and row["lco_sec"] < 0]
    return {
        "events_total": len(rows),
        "events_detected_with_timing": len(detected),
        "mean_leo_sec": sum(row["leo_sec"] for row in detected) / len(detected) if detected else None,
        "mean_lco_sec": sum(row["lco_sec"] for row in detected) / len(detected) if detected else None,
        "early_positive_leo_negative_lco_count": len(early_requested),
        "early_positive_leo_negative_lco": [
            {
                "patient_id": row.get("patient_id") or row.get("patient"),
                "seizure_id": row.get("seizure_id") or row.get("seizure"),
                "video_path": row.get("video_path") or row.get("video"),
                "first_alert_sec": _to_float(row.get("first_alert_sec")),
                "leo_sec": row["leo_sec"],
                "lco_sec": row["lco_sec"],
            }
            for row in early_requested
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", required=True, help="Event CSV/JSON with leo_sec and lco_sec columns.")
    parser.add_argument("--out-json", default="")
    args = parser.parse_args()

    result = summarize(load_rows(Path(args.events)))
    print(json.dumps(result, indent=2))

    if args.out_json:
        out = Path(args.out_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
