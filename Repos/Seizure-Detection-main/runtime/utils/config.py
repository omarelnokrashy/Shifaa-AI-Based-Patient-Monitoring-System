"""YAML configuration loader for the deployable runtime package."""

from pathlib import Path

import yaml


def load_config(path: str) -> dict:
    p = Path(path)
    if not p.is_absolute():
        package_root = Path(__file__).resolve().parents[2]
        candidates = [
            Path.cwd() / p,
            package_root / p,
            package_root / "configs" / p.name,
        ]
        p = next((candidate for candidate in candidates if candidate.exists()), p)
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
