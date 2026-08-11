import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFIER = REPO_ROOT / "scripts" / "verify_release.ps1"
WORK_ROOT = REPO_ROOT / "work"


def _powershell() -> str:
    bundled = REPO_ROOT / "work" / "tools" / "pwsh-7.5.5" / "pwsh.exe"
    if bundled.is_file():
        return str(bundled)
    executable = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
    if executable is None:
        pytest.skip("PowerShell is required for release-verifier path tests")
    return executable


def _run_preflight(test_dir: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["USERPROFILE"] = str(REPO_ROOT.parent)
    return subprocess.run(
        [
            _powershell(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(VERIFIER),
            "-Installer",
            str(VERIFIER),
            "-TestDir",
            str(test_dir),
            "-PreflightOnly",
        ],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=60,
        check=False,
    )


@pytest.mark.skipif(os.name != "nt", reason="release verifier is Windows-only")
def test_documented_work_target_is_allowed_below_user_profile() -> None:
    test_dir = WORK_ROOT / f"pytest-release-smoke-{uuid4().hex}"
    result = _run_preflight(test_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PREFLIGHT PASSED" in result.stdout
    assert not test_dir.exists()


@pytest.mark.skipif(os.name != "nt", reason="release verifier is Windows-only")
@pytest.mark.parametrize("test_dir", [REPO_ROOT / "release-smoke", WORK_ROOT])
def test_preflight_rejects_targets_not_strictly_below_work(test_dir: Path) -> None:
    result = _run_preflight(test_dir)

    assert result.returncode != 0
    assert "must be a strict child of verifier-owned work root" in (
        result.stdout + result.stderr
    )
