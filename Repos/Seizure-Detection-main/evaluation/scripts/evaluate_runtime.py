"""Summarize runtime profile JSON files emitted by the deployment pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-json", required=True, help="Runtime profile JSON artifact.")
    parser.add_argument("--out-json", default="")
    args = parser.parse_args()

    data = load_json(Path(args.profile_json))
    result = {
        "source": args.profile_json,
        "effective_fps": data.get("effective_fps") or data.get("fps_eff"),
        "frame_total_mean_ms": data.get("frame_total_mean_ms"),
        "frame_total_p95_ms": data.get("frame_total_p95_ms"),
        "peak_vram_mb": data.get("peak_vram_mb") or data.get("peak_reserved_mb"),
        "raw": data,
    }

    print(json.dumps(result, indent=2))
    if args.out_json:
        out = Path(args.out_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
