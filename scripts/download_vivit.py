#!/usr/bin/env python3
"""
Download and cache the ViViT model weights from HuggingFace.

Run this script once on a machine with internet access.
After it completes, the seizure detection service will automatically
switch to offline mode on all subsequent runs.

Usage:
    python scripts/download_vivit.py

Requirements:
    pip install transformers torch
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    try:
        from transformers import VivitModel, VivitImageProcessor
    except ImportError:
        print("[ERROR] transformers is not installed.")
        print("        Run: pip install transformers torch")
        return 1

    model_id = "google/vivit-b-16x2-kinetics400"
    print(f"Downloading '{model_id}' from HuggingFace Hub...")
    print("(This is a ~300 MB download. It will be cached locally.)\n")

    try:
        # Download and cache the model
        _ = VivitImageProcessor.from_pretrained(model_id)
        model = VivitModel.from_pretrained(model_id)
        print(f"\n[OK] Model downloaded and cached successfully.")
        print(f"     Parameters: {sum(p.numel() for p in model.parameters()):,}")

        # Verify the hf_utils detection logic
        repo_root = Path(__file__).resolve().parent.parent
        hf_utils = repo_root / "services" / "seizure_detection" / "runtime" / "utils" / "hf_utils.py"
        if hf_utils.exists():
            sys.path.insert(0, str(hf_utils.parent.parent))
            from utils.hf_utils import is_model_cached
            if is_model_cached(model_id):
                print(f"[OK] Cache detection verified — offline mode will activate automatically.")
            else:
                print(f"[WARN] Cache detection could not confirm the model location.")
                print(f"       The model IS downloaded but the detection heuristic may need updating.")
        else:
            print(f"[OK] Cache populated. hf_utils.py will handle offline switching at runtime.")

        print("\nYou may now run the seizure detection service without internet access.")
        return 0

    except Exception as e:
        print(f"\n[ERROR] Download failed: {e}")
        print("        Ensure you have a working internet connection and try again.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
