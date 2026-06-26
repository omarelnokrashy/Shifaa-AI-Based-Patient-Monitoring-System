"""Path helpers for deployment files and workspace-backed model assets."""

from pathlib import Path


DEPLOYMENT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = DEPLOYMENT_ROOT.parent


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = [
        DEPLOYMENT_ROOT / path,
        Path.cwd() / path,
        PROJECT_ROOT / path,
    ]
    return next((candidate for candidate in candidates if candidate.exists()), candidates[0])


def resolve_weight(cfg: dict, directory_key: str, filename_key: str, default_filename: str) -> Path:
    base = resolve_path(cfg.get(directory_key, "model_weights"))
    filename = cfg.get(filename_key, default_filename)
    path = Path(filename)
    if path.is_absolute():
        return path
    candidates = [
        base / path,
        DEPLOYMENT_ROOT / "model_weights" / path,
        PROJECT_ROOT / "weights" / path,
        PROJECT_ROOT / "weights" / "pose" / path,
        PROJECT_ROOT / "weights" / "vsvig" / path,
        PROJECT_ROOT / "weights" / "cross_joint" / "checkpoints" / path,
    ]
    return next((candidate for candidate in candidates if candidate.exists()), candidates[0])
