import json
import subprocess
from pathlib import Path


def test_frozen_exe_self_test(repo_root: Path):
    exe = repo_root / "dist" / "ShiyiDesktopPet" / "ShiyiDesktopPet.exe"
    assert exe.is_file(), f"missing frozen executable: {exe}"
    result = subprocess.run(
        [exe, "--self-test"], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["webp_plugin"] is True
    assert report["atlas"]["frames"] == 74
