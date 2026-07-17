from pathlib import Path
import sys


def resource_root() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    root = base / "resources"
    if not root.is_dir():
        raise FileNotFoundError(f"Missing desktop-pet resource directory: {root}")
    return root


def resource_path(name: str) -> Path:
    path = resource_root() / name
    if not path.is_file():
        raise FileNotFoundError(f"Missing desktop-pet resource: {path}")
    return path
