$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptRoot '..')).Path
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$spec = Join-Path $repoRoot 'packaging\DesktopCompanion.spec'
$exe = Join-Path $repoRoot 'dist\DesktopCompanion\DesktopCompanion.exe'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Missing build interpreter: $python"
}

Push-Location $repoRoot
try {
    & $python -m pytest -q --ignore=tests/integration/test_frozen_smoke.py
    if ($LASTEXITCODE -ne 0) {
        throw 'Source test suite failed'
    }

    & $python -m PyInstaller --noconfirm --clean $spec
    if ($LASTEXITCODE -ne 0) {
        throw 'PyInstaller build failed'
    }

    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
        throw "PyInstaller did not produce the expected executable: $exe"
    }

    # PowerShell does not reliably attach redirected standard handles when it
    # invokes a Windows-subsystem executable directly. ProcessStartInfo does,
    # matching subprocess.run(capture_output=True) in the frozen smoke test.
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $exe
    $startInfo.Arguments = '--self-test'
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    try {
        [void]$process.Start()
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(20000)) {
            $process.Kill($true)
            throw 'Frozen self-test timed out'
        }
        $selfTestJson = $stdoutTask.GetAwaiter().GetResult().Trim()
        $selfTestError = $stderrTask.GetAwaiter().GetResult().Trim()
        if ($process.ExitCode -ne 0) {
            throw "Frozen self-test failed: $selfTestError"
        }
    }
    finally {
        $process.Dispose()
    }
    try {
        $selfTestReport = $selfTestJson | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Frozen self-test did not produce valid JSON: $selfTestJson"
    }
    if (-not $selfTestReport.ok -or -not $selfTestReport.webp_plugin) {
        throw "Frozen self-test reported failure: $selfTestJson"
    }
    Write-Output $selfTestJson
}
finally {
    Pop-Location
}
