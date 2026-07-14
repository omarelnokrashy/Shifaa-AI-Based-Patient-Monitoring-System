"""
HuggingFace offline/online mode management.

Implements smart detection:
  - If the target model is already cached locally → enforce offline mode
    so no network calls are ever made (required for air-gapped hospital deployments).
  - If the model has NOT been cached yet → allow online download on first run,
    then the cache is populated and subsequent runs use offline mode.

Usage (must be called BEFORE importing transformers):
    from runtime.utils.hf_utils import configure_hf_mode
    configure_hf_mode("google/vivit-b-16x2-kinetics400")
"""

from __future__ import annotations

import os
from pathlib import Path


def _model_id_to_cache_key(model_id: str) -> str:
    """Convert a HuggingFace model ID to its cache directory name."""
    # e.g. "google/vivit-b-16x2-kinetics400" → "models--google--vivit-b-16x2-kinetics400"
    return "models--" + model_id.replace("/", "--")


def is_model_cached(model_id: str) -> bool:
    """Return True if the model's snapshot directory exists and is non-empty in the HF cache."""
    hf_home = Path(
        os.environ.get("HF_HOME", "")
        or os.environ.get("HUGGINGFACE_HUB_CACHE", "")
        or Path.home() / ".cache" / "huggingface"
    )
    cache_key = _model_id_to_cache_key(model_id)

    # Try both the hub/ subdirectory (hub library layout) and the root (legacy layout)
    candidate_dirs = [
        hf_home / "hub" / cache_key,
        hf_home / cache_key,
    ]
    for d in candidate_dirs:
        if d.exists():
            # A freshly created but empty directory does not count
            try:
                if any(d.iterdir()):
                    return True
            except PermissionError:
                pass
    return False


def configure_hf_mode(model_id: str) -> bool:
    """
    Configure HuggingFace environment variables based on whether ``model_id``
    is already cached locally.

    Always disables telemetry.

    Returns:
        True  — offline mode enabled (model was found in cache).
        False — online mode enabled (model will be downloaded on first use).
    """
    # Always suppress telemetry regardless of online/offline status
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

    if is_model_cached(model_id):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        return True
    else:
        # Clear any stale offline flags that would block the first-time download
        os.environ.pop("HF_HUB_OFFLINE", None)
        os.environ.pop("TRANSFORMERS_OFFLINE", None)
        return False
