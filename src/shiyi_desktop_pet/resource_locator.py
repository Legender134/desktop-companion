from pathlib import Path
import sys


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    path = base / "resources" / name
    if not path.is_file():
        raise FileNotFoundError(f"Missing desktop-pet resource: {path}")
    return path
