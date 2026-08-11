# Release Verifier User-Profile Path Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the documented `work\release-smoke` verification target usable when the repository is below `%USERPROFILE%`, without weakening protection for concrete product, user-data, repository, or build paths.

**Architecture:** Keep the verifier's existing strict `work`-root containment and reparse-point checks. Remove only the overly broad `%USERPROFILE%` ancestor from the symmetric overlap list, prove the documented preflight path turns RED to GREEN, retain negative containment tests, then run and independently review the complete isolated release workflow.

**Tech Stack:** PowerShell 7.5.5, Windows PowerShell 5.1 for the established installed-tree manifest algorithm, Python 3/pytest, Inno Setup 7.0.2, Git.

## Global Constraints

- Ordinary and upgrade test roots remain strict descendants of the repository-owned `work` directory.
- The installer, `%APPDATA%`, `%LOCALAPPDATA%`, DesktopCompanion data/install locations, recorded install locations, and repository metadata/source/build directories remain protected.
- Reparse components remain forbidden and recursive removal remains constrained to the verifier-owned `work` root.
- Do not modify application runtime code, pet behavior, installer contents, or the existing DesktopCompanion installation.
- Do not push or upload any source, evidence, or installer.
- If a different verifier defect appears, require safe rollback and diagnose it separately before another production run.

---

### Task 1: Correct the verifier's user-profile overlap rule

**Files:**
- Create: `tests/test_release_verifier_path_safety.py`
- Modify: `scripts/verify_release.ps1:2434-2454`

**Interfaces:**
- Consumes: `scripts/verify_release.ps1 -Installer <existing-file> -TestDir <path> -PreflightOnly`
- Produces: a preflight contract that accepts a documented strict child of repository `work` below `%USERPROFILE%`, while rejecting paths outside or equal to `work`

- [ ] **Step 1: Add a production-boundary preflight test**

```python
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
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_release_verifier_path_safety.py -q
```

Expected: the documented-work-target case fails with `Test directory overlaps protected path: ... <-> C:\Users\admin`; both negative cases pass.

- [ ] **Step 3: Apply the minimal verifier correction**

In `$protectedPaths`, remove only this entry:

```powershell
    $env:USERPROFILE,
```

Do not change `Assert-TestRoot`, `Test-PathsOverlap`, `Assert-NoReparseComponents`, the remaining protected paths, or cleanup allowed roots.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_release_verifier_path_safety.py -q
```

Expected: `3 passed`; no test or upgrade install directory is created.

- [ ] **Step 5: Run script and repository checks**

Run:

```powershell
& .\work\tools\pwsh-7.5.5\pwsh.exe -NoLogo -NoProfile -NonInteractive -File .\scripts\verify_release.ps1 `
    -Installer .\artifacts\桌面灵伴安装程序.exe `
    -TestDir (Join-Path $PWD 'work\release-smoke') `
    -PreflightOnly
& .\.venv\Scripts\python.exe -m py_compile tests\test_release_verifier_path_safety.py
git diff --check
```

Expected: preflight exit `0` with `PREFLIGHT PASSED`; Python compilation and diff check exit `0`; `work\release-smoke` and `work\release-smoke-upgrade` remain absent.

- [ ] **Step 6: Commit the correction**

```powershell
git add -- scripts\verify_release.ps1 tests\test_release_verifier_path_safety.py
git commit -m "fix: allow verifier work root below user profile"
```

Expected: one focused commit containing only the verifier and its path-safety tests.

- [ ] **Step 7: Obtain independent code review**

The reviewer must verify the positive and negative tests, confirm only `%USERPROFILE%` left the symmetric list, and confirm all concrete protected paths and cleanup containment remain unchanged. Do not begin production verification until the review verdict has no Critical or Important findings.

---

### Task 2: Execute and close the isolated release gate

**Files:**
- Modify: `.superpowers/sdd/task-11-report.md` (ignored local evidence)
- Modify: `.superpowers/sdd/progress.md` (ignored local ledger)
- Modify: `artifacts/v4-runtime-qa/release-verification.txt` (ignored local evidence)
- Create: `artifacts/v4-runtime-qa/verify-release-command.txt`
- Create: `artifacts/v4-runtime-qa/verify-release.stdout.log`
- Create: `artifacts/v4-runtime-qa/verify-release.stderr.log`
- Create: `artifacts/v4-runtime-qa/verify-release.exit-code.txt`

**Interfaces:**
- Consumes: reviewed `scripts/verify_release.ps1`, installer SHA-256 `7DAC07ABF9B196F31BC42D90DDCC5036F00141E99BC5DACA26D6ACF8FDFF70EE`, test root `work\release-smoke`
- Produces: evidence-backed ordinary install/self-test/uninstall and upgrade preservation/self-test/uninstall verification with restored protected state

- [ ] **Step 1: Capture immutable pre-run state**

Run Windows PowerShell 5.1 with `.superpowers\sdd\task-11-snapshot-installed-tree.ps1` to capture the current installed tree using the established ordinal input and `Sort-Object FullName` behavior. Also record:

```powershell
Get-CimInstance Win32_Process -Filter "Name='DesktopCompanion.exe'"
Get-FileHash -Algorithm SHA256 -LiteralPath '.\artifacts\桌面灵伴安装程序.exe'
git status --short
```

Expected: no DesktopCompanion process; installer hash exactly `7DAC07ABF9B196F31BC42D90DDCC5036F00141E99BC5DACA26D6ACF8FDFF70EE`; installed-tree count/digest `615` / `406CEB9714FF7419C60E33D2E5F470EB43BE0CC51578FC81DFD54C0081A0704E`; tracked worktree clean.

- [ ] **Step 2: Run the original production verifier once and capture native evidence**

Run:

```powershell
& .\work\tools\pwsh-7.5.5\pwsh.exe -NoLogo -NoProfile -NonInteractive -File .\scripts\verify_release.ps1 `
    -Installer .\artifacts\桌面灵伴安装程序.exe `
    -TestDir (Join-Path $PWD 'work\release-smoke')
```

Capture the exact command, start/end timestamps, stdout, stderr, and native exit code in the four QA files listed above.

Expected exit `0` and output containing all of:

```text
PREFLIGHT PASSED
ORDINARY VERIFY: install=0 self-test=0
UPGRADE VERIFY: settings-preserved=true
UPGRADE UNINSTALL VERIFY: process/run/uninstall/install/settings/log cleanup=true
RELEASE VERIFY PASSED: ordinary install/self-test/uninstall and upgrade preservation
```

- [ ] **Step 3: Verify rollback and isolation after the run**

Confirm all of the following with read-only checks:

```powershell
Test-Path -LiteralPath '.\work\release-smoke'
Test-Path -LiteralPath '.\work\release-smoke-upgrade'
Get-ChildItem -LiteralPath '.\work' -Directory -Filter 'release-verify-*'
Get-CimInstance Win32_Process -Filter "Name='DesktopCompanion.exe'"
git status --short
git diff --check
```

Expected: both test roots absent; zero `release-verify-*` backups; zero DesktopCompanion processes; tracked tree clean; diff check exit `0`. Recompute the existing installed-tree manifest using Windows PowerShell 5.1 and require byte-for-byte equality with the pre-run manifest, count `615`, and digest `406CEB9714FF7419C60E33D2E5F470EB43BE0CC51578FC81DFD54C0081A0704E`.

- [ ] **Step 4: Update local QA evidence and ledger**

Record exact command/output hashes, installer hash, state transitions, cleanup results, installed-tree comparison, and the absence of push/upload commands in `.superpowers/sdd/task-11-report.md` and `artifacts/v4-runtime-qa/release-verification.txt`. Change `.superpowers/sdd/progress.md` Task 11 from `in progress` to `complete` only if every expected assertion above passed.

- [ ] **Step 5: Obtain independent final review**

The reviewer must inspect the raw command/stdout/stderr/exit evidence, independently recompute the installer hash and installed-tree manifest, confirm the isolated roots/backups/processes are absent, verify protected registry/data restoration evidence, and return `Task11 complete: yes` with no Critical or Important issue.

- [ ] **Step 6: Final local integrity check**

Run:

```powershell
git status --short
git diff --check
git log -1 --oneline
```

Expected: tracked worktree clean, diff check exit `0`, no push/upload, and the release-verifier fix commit present locally.
