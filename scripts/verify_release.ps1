[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Installer,

    [Parameter(Mandatory = $true)]
    [string]$TestDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot '..'))
$workRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot 'work'))
$installerPath = (Resolve-Path -LiteralPath $Installer -ErrorAction Stop).Path
$testDirPath = [System.IO.Path]::GetFullPath($TestDir)
$upgradeDirPath = [System.IO.Path]::GetFullPath("$testDirPath-upgrade")
$verificationId = [guid]::NewGuid().ToString('N')
$backupRoot = Join-Path $workRoot "release-verify-$verificationId"
$registryBackupPath = Join-Path $backupRoot 'registry-state.clixml'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'

$runKeyPath = 'Software\Microsoft\Windows\CurrentVersion\Run'
$runValueName = 'ShiyiDesktopPet'
$uninstallKeyPath = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{5F4B3AD9-7C91-4E2D-A4C4-70C5C4F5A211}_is1'
$roamingPath = [System.IO.Path]::GetFullPath((Join-Path $env:APPDATA 'ShiyiDesktopPet'))
$localPath = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'ShiyiDesktopPet'))

function Test-DescendantPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root,
        [switch]$AllowEqual
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $fullRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    if ($AllowEqual -and $fullPath.Equals($fullRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    return $fullPath.StartsWith(
        "$fullRoot$([System.IO.Path]::DirectorySeparatorChar)",
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

function Assert-SafeRecursiveTarget {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$AllowedRoots,
        [Parameter(Mandatory = $true)][string]$Purpose,
        [switch]$AllowEqual
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $safeRoot = $null
    foreach ($candidate in $AllowedRoots) {
        $fullCandidate = [System.IO.Path]::GetFullPath($candidate)
        if (Test-DescendantPath -Path $fullPath -Root $fullCandidate -AllowEqual:$AllowEqual) {
            $safeRoot = $fullCandidate
            break
        }
    }
    if ($null -eq $safeRoot) {
        throw "Refusing recursive $Purpose outside allowed roots: $fullPath"
    }
    if (Test-Path -LiteralPath $fullPath) {
        $item = Get-Item -LiteralPath $fullPath -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing recursive $Purpose through a reparse point: $fullPath"
        }
    }
    Write-Host "SAFE PATH CHECK [$Purpose]: $fullPath <= $safeRoot"
    return $fullPath
}

function Remove-SafeTree {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$AllowedRoots,
        [Parameter(Mandatory = $true)][string]$Purpose,
        [switch]$AllowEqual
    )

    $fullPath = Assert-SafeRecursiveTarget -Path $Path -AllowedRoots $AllowedRoots -Purpose $Purpose -AllowEqual:$AllowEqual
    if (Test-Path -LiteralPath $fullPath) {
        Remove-Item -LiteralPath $fullPath -Recurse -Force
    }
}

function Assert-TestRoot {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $volumeRoot = [System.IO.Path]::GetPathRoot($fullPath).TrimEnd('\', '/')
    if ($fullPath.Equals($volumeRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Test directory cannot be a volume root: $fullPath"
    }
    foreach ($protected in @($repoRoot, $workRoot, $env:USERPROFILE, $env:APPDATA, $env:LOCALAPPDATA)) {
        if ($protected -and $fullPath.Equals(
            [System.IO.Path]::GetFullPath($protected).TrimEnd('\', '/'),
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Test directory cannot be a protected root: $fullPath"
        }
    }
    Write-Output "SAFE TEST ROOT: $fullPath"
}

function Get-DirectoryFingerprint {
    param([Parameter(Mandatory = $true)][string]$Path)

    $root = [System.IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $lines = [System.Collections.Generic.List[string]]::new()
    foreach ($item in @(Get-ChildItem -LiteralPath $root -Force -Recurse | Sort-Object FullName)) {
        $relative = $item.FullName.Substring($root.Length).TrimStart('\', '/')
        if ($item.PSIsContainer) {
            $lines.Add("D|$relative")
        }
        else {
            $fileHash = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash
            $lines.Add("F|$relative|$($item.Length)|$fileHash")
        }
    }
    $payload = [System.Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return [System.Convert]::ToHexString($sha.ComputeHash($payload))
    }
    finally {
        $sha.Dispose()
    }
}

function Read-RegistryNode {
    param([Parameter(Mandatory = $true)][Microsoft.Win32.RegistryKey]$Key)

    $values = @(
        foreach ($name in $Key.GetValueNames()) {
            [pscustomobject]@{
                Name = $name
                Kind = $Key.GetValueKind($name).ToString()
                Value = $Key.GetValue(
                    $name,
                    $null,
                    [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
                )
            }
        }
    )
    $children = @(
        foreach ($name in $Key.GetSubKeyNames()) {
            $child = $Key.OpenSubKey($name, $false)
            try {
                [pscustomobject]@{
                    Name = $name
                    Node = Read-RegistryNode -Key $child
                }
            }
            finally {
                $child.Dispose()
            }
        }
    )
    return [pscustomobject]@{ Values = $values; Children = $children }
}

function Get-RegistryTreeSnapshot {
    param([Parameter(Mandatory = $true)][string]$SubKey)

    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::CurrentUser,
        [Microsoft.Win32.RegistryView]::Default
    )
    try {
        $key = $base.OpenSubKey($SubKey, $false)
        if ($null -eq $key) {
            return [pscustomobject]@{ Exists = $false; Node = $null }
        }
        try {
            return [pscustomobject]@{ Exists = $true; Node = Read-RegistryNode -Key $key }
        }
        finally {
            $key.Dispose()
        }
    }
    finally {
        $base.Dispose()
    }
}

function Get-RegistryValueSnapshot {
    param(
        [Parameter(Mandatory = $true)][string]$SubKey,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::CurrentUser,
        [Microsoft.Win32.RegistryView]::Default
    )
    try {
        $key = $base.OpenSubKey($SubKey, $false)
        if ($null -eq $key) {
            return [pscustomobject]@{ Exists = $false; Kind = $null; Value = $null }
        }
        try {
            if ($Name -notin $key.GetValueNames()) {
                return [pscustomobject]@{ Exists = $false; Kind = $null; Value = $null }
            }
            return [pscustomobject]@{
                Exists = $true
                Kind = $key.GetValueKind($Name).ToString()
                Value = $key.GetValue(
                    $Name,
                    $null,
                    [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
                )
            }
        }
        finally {
            $key.Dispose()
        }
    }
    finally {
        $base.Dispose()
    }
}

function Remove-RegistryTree {
    param([Parameter(Mandatory = $true)][string]$SubKey)

    $separator = $SubKey.LastIndexOf('\')
    $parentPath = $SubKey.Substring(0, $separator)
    $leaf = $SubKey.Substring($separator + 1)
    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::CurrentUser,
        [Microsoft.Win32.RegistryView]::Default
    )
    try {
        $parent = $base.OpenSubKey($parentPath, $true)
        if ($null -ne $parent) {
            try {
                $parent.DeleteSubKeyTree($leaf, $false)
            }
            finally {
                $parent.Dispose()
            }
        }
    }
    finally {
        $base.Dispose()
    }
}

function Remove-RegistryValue {
    param(
        [Parameter(Mandatory = $true)][string]$SubKey,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::CurrentUser,
        [Microsoft.Win32.RegistryView]::Default
    )
    try {
        $key = $base.OpenSubKey($SubKey, $true)
        if ($null -ne $key) {
            try {
                $key.DeleteValue($Name, $false)
            }
            finally {
                $key.Dispose()
            }
        }
    }
    finally {
        $base.Dispose()
    }
}

function Write-RegistryNode {
    param(
        [Parameter(Mandatory = $true)][Microsoft.Win32.RegistryKey]$Key,
        [Parameter(Mandatory = $true)]$Node
    )

    foreach ($value in $Node.Values) {
        $kind = [Microsoft.Win32.RegistryValueKind]::$($value.Kind)
        $Key.SetValue($value.Name, $value.Value, $kind)
    }
    foreach ($child in $Node.Children) {
        $childKey = $Key.CreateSubKey($child.Name, $true)
        try {
            Write-RegistryNode -Key $childKey -Node $child.Node
        }
        finally {
            $childKey.Dispose()
        }
    }
}

function Restore-RegistryTree {
    param(
        [Parameter(Mandatory = $true)][string]$SubKey,
        [Parameter(Mandatory = $true)]$Snapshot
    )

    Remove-RegistryTree -SubKey $SubKey
    if (-not $Snapshot.Exists) {
        return
    }
    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::CurrentUser,
        [Microsoft.Win32.RegistryView]::Default
    )
    try {
        $key = $base.CreateSubKey($SubKey, $true)
        try {
            Write-RegistryNode -Key $key -Node $Snapshot.Node
        }
        finally {
            $key.Dispose()
        }
    }
    finally {
        $base.Dispose()
    }
}

function Restore-RegistryValue {
    param(
        [Parameter(Mandatory = $true)][string]$SubKey,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Snapshot
    )

    Remove-RegistryValue -SubKey $SubKey -Name $Name
    if (-not $Snapshot.Exists) {
        return
    }
    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::CurrentUser,
        [Microsoft.Win32.RegistryView]::Default
    )
    try {
        $key = $base.CreateSubKey($SubKey, $true)
        try {
            $kind = [Microsoft.Win32.RegistryValueKind]::$($Snapshot.Kind)
            $key.SetValue($Name, $Snapshot.Value, $kind)
        }
        finally {
            $key.Dispose()
        }
    }
    finally {
        $base.Dispose()
    }
}

function Invoke-CapturedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [int]$TimeoutSeconds = 120
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true
    foreach ($argument in $Arguments) {
        $startInfo.ArgumentList.Add($argument)
    }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    try {
        [void]$process.Start()
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            $process.Kill($true)
            throw "Process timed out after $TimeoutSeconds seconds: $FilePath"
        }
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            Stdout = $stdoutTask.GetAwaiter().GetResult().Trim()
            Stderr = $stderrTask.GetAwaiter().GetResult().Trim()
        }
    }
    finally {
        $process.Dispose()
    }
}

function Invoke-CheckedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [int]$TimeoutSeconds = 120,
        [string]$Description = 'process'
    )

    $result = Invoke-CapturedProcess -FilePath $FilePath -Arguments $Arguments -TimeoutSeconds $TimeoutSeconds
    if ($result.ExitCode -ne 0) {
        throw "$Description failed with exit code $($result.ExitCode). stdout=$($result.Stdout) stderr=$($result.Stderr)"
    }
    return $result
}

function Invoke-Install {
    param(
        [Parameter(Mandatory = $true)][string]$Directory,
        [Parameter(Mandatory = $true)][ValidateSet('enable', 'disable')][string]$Startup
    )

    $taskArgument = if ($Startup -eq 'enable') { '/MERGETASKS=startup' } else { '/MERGETASKS=!startup' }
    [void](Invoke-CheckedProcess -FilePath $installerPath -Arguments @(
        '/VERYSILENT',
        '/SUPPRESSMSGBOXES',
        '/NORESTART',
        '/SP-',
        '/NOICONS',
        "/DIR=$Directory",
        $taskArgument
    ) -TimeoutSeconds 300 -Description "silent install ($Startup startup)")
}

function Invoke-Uninstall {
    param([Parameter(Mandatory = $true)][string]$Directory)

    $uninstaller = Join-Path $Directory 'unins000.exe'
    if (Test-Path -LiteralPath $uninstaller -PathType Leaf) {
        $logPath = Join-Path $backupRoot "uninstall-$([System.IO.Path]::GetFileName($Directory))-$([guid]::NewGuid().ToString('N')).log"
        # Inno runs the real uninstall in a temporary clone. Start-Process
        # -Wait waits for the local process tree; Process.WaitForExit only
        # observes the first-phase stub and can race cleanup/log closure.
        $arguments = @(
            '/VERYSILENT',
            '/SUPPRESSMSGBOXES',
            '/NORESTART',
            ('/LOG="{0}"' -f $logPath)
        )
        $process = Start-Process -FilePath $uninstaller -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
        $exitCode = $process.ExitCode
        $process.Dispose()
        if ($exitCode -ne 0) {
            $logTail = if (Test-Path -LiteralPath $logPath -PathType Leaf) {
                (Get-Content -LiteralPath $logPath -Tail 60) -join "`n"
            }
            else {
                '<no uninstall log>'
            }
            throw "silent uninstall failed with exit code $exitCode. log=$logTail"
        }
    }
}

function Get-TestProcesses {
    $roots = @($testDirPath, $upgradeDirPath)
    return @(
        foreach ($process in @(Get-CimInstance Win32_Process -Filter "Name = 'ShiyiDesktopPet.exe'" -ErrorAction SilentlyContinue)) {
            if (-not $process.ExecutablePath) {
                continue
            }
            foreach ($root in $roots) {
                if (Test-DescendantPath -Path $process.ExecutablePath -Root $root -AllowEqual) {
                    $process
                    break
                }
            }
        }
    )
}

function Assert-NoTestProcesses {
    $processes = @(Get-TestProcesses)
    if ($processes.Count -ne 0) {
        throw "Test ShiyiDesktopPet process remains: $($processes.ProcessId -join ', ')"
    }
}

function Assert-RegistryValueAbsent {
    $snapshot = Get-RegistryValueSnapshot -SubKey $runKeyPath -Name $runValueName
    if ($snapshot.Exists) {
        throw "Unexpected HKCU Run value: $($snapshot.Value)"
    }
}

function Assert-UninstallEntry {
    param([Parameter(Mandatory = $true)][bool]$Expected)

    $actual = (Get-RegistryTreeSnapshot -SubKey $uninstallKeyPath).Exists
    if ($actual -ne $Expected) {
        throw "Uninstall registry entry expected=$Expected actual=$actual"
    }
}

function Assert-InstalledLayout {
    param([Parameter(Mandatory = $true)][string]$Directory)

    foreach ($name in @('ShiyiDesktopPet.exe', 'unins000.exe')) {
        $path = Join-Path $Directory $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Missing installed file: $path"
        }
    }
}

function Invoke-FrozenSelfTest {
    param([Parameter(Mandatory = $true)][string]$Directory)

    $exe = Join-Path $Directory 'ShiyiDesktopPet.exe'
    $result = Invoke-CheckedProcess -FilePath $exe -Arguments @('--self-test') -TimeoutSeconds 30 -Description 'installed frozen self-test'
    try {
        $report = $result.Stdout | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Installed self-test did not return JSON: $($result.Stdout)"
    }
    if (-not $report.ok -or -not $report.webp_plugin) {
        throw "Installed self-test reported failure: $($result.Stdout)"
    }
    Write-Output "SELF-TEST: $($result.Stdout)"
}

function Ensure-IsolatedDataLinks {
    param([Parameter(Mandatory = $true)][object[]]$States)

    foreach ($state in $States) {
        if (-not (Test-Path -LiteralPath $state.Target -PathType Container)) {
            [void](New-Item -ItemType Directory -Path $state.Target -Force)
        }
        if (Test-Path -LiteralPath $state.RealPath) {
            $item = Get-Item -LiteralPath $state.RealPath -Force
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0) {
                throw "Isolation path became a real directory: $($state.RealPath)"
            }
            $targets = @($item.Target | ForEach-Object { [System.IO.Path]::GetFullPath($_) })
            if ($state.Target -notin $targets) {
                throw "Unexpected junction target for $($state.RealPath): $($targets -join ', ')"
            }
            continue
        }
        [void](New-Item -ItemType Junction -Path $state.RealPath -Target $state.Target)
        Write-Output "STATE ISOLATION: $($state.RealPath) -> $($state.Target)"
    }
}

function Remove-IsolatedDataLinks {
    param([Parameter(Mandatory = $true)][object[]]$States)

    foreach ($state in $States) {
        if (-not (Test-Path -LiteralPath $state.RealPath)) {
            continue
        }
        $item = Get-Item -LiteralPath $state.RealPath -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0) {
            throw "Refusing to remove non-junction user data path: $($state.RealPath)"
        }
        $targets = @($item.Target | ForEach-Object { [System.IO.Path]::GetFullPath($_) })
        if ($state.Target -notin $targets) {
            throw "Refusing to remove unexpected junction: $($state.RealPath) -> $($targets -join ', ')"
        }
        Remove-Item -LiteralPath $state.RealPath -Force
    }
}

Assert-TestRoot -Path $testDirPath
Assert-TestRoot -Path $upgradeDirPath
if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    throw "Installer is not a file: $installerPath"
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Missing verification interpreter: $python"
}
if (-not (Test-Path -LiteralPath $workRoot -PathType Container)) {
    [void](New-Item -ItemType Directory -Path $workRoot)
}

# A real running installation could recreate settings/logs while they are held.
# Refuse the test rather than disturb a user's active process.
$foreignProcesses = @(
    Get-CimInstance Win32_Process -Filter "Name = 'ShiyiDesktopPet.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ExecutablePath -and
            -not (Test-DescendantPath -Path $_.ExecutablePath -Root $testDirPath -AllowEqual) -and
            -not (Test-DescendantPath -Path $_.ExecutablePath -Root $upgradeDirPath -AllowEqual)
        }
)
if ($foreignProcesses.Count -ne 0) {
    throw "Refusing release verification while another ShiyiDesktopPet is running: $($foreignProcesses.ProcessId -join ', ')"
}

[void](New-Item -ItemType Directory -Path $backupRoot)
$dataStates = @(
    [pscustomobject]@{
        Name = 'roaming'
        RealPath = $roamingPath
        HoldPath = "$roamingPath.sdd-hold-$verificationId"
        BackupPath = Join-Path $backupRoot 'original-data\roaming'
        Target = Join-Path $backupRoot 'isolated-state\roaming'
        Existed = $false
        Fingerprint = $null
    },
    [pscustomobject]@{
        Name = 'local'
        RealPath = $localPath
        HoldPath = "$localPath.sdd-hold-$verificationId"
        BackupPath = Join-Path $backupRoot 'original-data\local'
        Target = Join-Path $backupRoot 'isolated-state\local'
        Existed = $false
        Fingerprint = $null
    }
)
$registryState = $null
$stateCaptured = $false
$verificationSucceeded = $false

try {
    foreach ($state in $dataStates) {
        if (Test-Path -LiteralPath $state.HoldPath) {
            throw "Unique hold path unexpectedly exists: $($state.HoldPath)"
        }
        if (Test-Path -LiteralPath $state.RealPath) {
            $item = Get-Item -LiteralPath $state.RealPath -Force
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Refusing to isolate an existing reparse point: $($state.RealPath)"
            }
            $state.Existed = $true
            $state.Fingerprint = Get-DirectoryFingerprint -Path $state.RealPath
            $backupParent = Split-Path -Parent $state.BackupPath
            [void](New-Item -ItemType Directory -Path $backupParent -Force)
            Copy-Item -LiteralPath $state.RealPath -Destination $state.BackupPath -Recurse -Force
            $backupFingerprint = Get-DirectoryFingerprint -Path $state.BackupPath
            if ($backupFingerprint -ne $state.Fingerprint) {
                throw "User data backup fingerprint mismatch: $($state.RealPath)"
            }
            Move-Item -LiteralPath $state.RealPath -Destination $state.HoldPath
            Write-Output "USER DATA BACKUP: $($state.RealPath) -> $($state.BackupPath), fingerprint=$($state.Fingerprint)"
        }
        else {
            Write-Output "USER DATA BACKUP: $($state.RealPath) did not exist"
        }
    }

    $registryState = [pscustomobject]@{
        Run = Get-RegistryValueSnapshot -SubKey $runKeyPath -Name $runValueName
        Uninstall = Get-RegistryTreeSnapshot -SubKey $uninstallKeyPath
    }
    $registryState | Export-Clixml -LiteralPath $registryBackupPath
    Write-Output "REGISTRY BACKUP: Run=$($registryState.Run.Exists), Uninstall=$($registryState.Uninstall.Exists), file=$registryBackupPath"
    $stateCaptured = $true
    Remove-RegistryValue -SubKey $runKeyPath -Name $runValueName
    Remove-RegistryTree -SubKey $uninstallKeyPath

    Ensure-IsolatedDataLinks -States $dataStates
    foreach ($directory in @($testDirPath, $upgradeDirPath)) {
        Remove-SafeTree -Path $directory -AllowedRoots @($directory, $workRoot) -Purpose 'pre-test cleanup' -AllowEqual
    }

    Write-Output '--- ordinary install/self-test/uninstall ---'
    Invoke-Install -Directory $testDirPath -Startup disable
    Assert-InstalledLayout -Directory $testDirPath
    Assert-UninstallEntry -Expected $true
    Assert-RegistryValueAbsent
    Invoke-FrozenSelfTest -Directory $testDirPath
    Assert-NoTestProcesses

    $ordinarySettings = Join-Path $roamingPath 'settings.ini'
    $ordinaryLog = Join-Path $localPath 'logs\verification.log'
    [void](New-Item -ItemType Directory -Path (Split-Path -Parent $ordinarySettings) -Force)
    [void](New-Item -ItemType Directory -Path (Split-Path -Parent $ordinaryLog) -Force)
    [System.IO.File]::WriteAllText($ordinarySettings, "[verification]`nid=$verificationId`n", [System.Text.UTF8Encoding]::new($false))
    [System.IO.File]::WriteAllText($ordinaryLog, "verification=$verificationId`n", [System.Text.UTF8Encoding]::new($false))

    Invoke-Uninstall -Directory $testDirPath
    Assert-NoTestProcesses
    Assert-RegistryValueAbsent
    Assert-UninstallEntry -Expected $false
    if (Test-Path -LiteralPath $testDirPath) {
        throw "Ordinary uninstall left test install directory: $testDirPath"
    }
    if ((Test-Path -LiteralPath $ordinarySettings) -or (Test-Path -LiteralPath $ordinaryLog)) {
        throw 'Ordinary uninstall left verification settings or logs'
    }
    foreach ($state in $dataStates) {
        if (Test-Path -LiteralPath $state.RealPath) {
            throw "Ordinary uninstall left product data path: $($state.RealPath)"
        }
    }
    Write-Output 'ORDINARY VERIFY: install=0 self-test=0 startup-absent=true uninstall=0 cleanup=true'

    Write-Output '--- upgrade preservation ---'
    Ensure-IsolatedDataLinks -States $dataStates
    Invoke-Install -Directory $upgradeDirPath -Startup enable
    Assert-InstalledLayout -Directory $upgradeDirPath
    Assert-UninstallEntry -Expected $true
    $expectedRun = '"' + (Join-Path $upgradeDirPath 'ShiyiDesktopPet.exe') + '" --startup'
    $runAfterFirstInstall = Get-RegistryValueSnapshot -SubKey $runKeyPath -Name $runValueName
    if (-not $runAfterFirstInstall.Exists -or $runAfterFirstInstall.Value -ne $expectedRun) {
        throw "First install did not create the expected startup value: $($runAfterFirstInstall.Value)"
    }

    $settingsPath = Join-Path $roamingPath 'settings.ini'
    $settingsText = "[settings]`nschema_version = 1`nwander_enabled = true`nverification_sentinel = $verificationId`n"
    [System.IO.File]::WriteAllText($settingsPath, $settingsText, [System.Text.UTF8Encoding]::new($false))
    $settingsHash = (Get-FileHash -LiteralPath $settingsPath -Algorithm SHA256).Hash

    $startupCode = 'from pathlib import Path; import sys; from shiyi_desktop_pet.startup import StartupManager, WinRegRunKey; StartupManager(WinRegRunKey(), Path(sys.argv[1])).set_enabled(False)'
    $oldPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = Join-Path $repoRoot 'src'
        [void](Invoke-CheckedProcess -FilePath $python -Arguments @('-c', $startupCode, (Join-Path $upgradeDirPath 'ShiyiDesktopPet.exe')) -TimeoutSeconds 30 -Description 'StartupManager disable')
    }
    finally {
        $env:PYTHONPATH = $oldPythonPath
    }
    Assert-RegistryValueAbsent

    Invoke-Install -Directory $upgradeDirPath -Startup enable
    Assert-InstalledLayout -Directory $upgradeDirPath
    Assert-UninstallEntry -Expected $true
    Assert-RegistryValueAbsent
    if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
        throw 'Upgrade removed the settings sentinel'
    }
    if ((Get-FileHash -LiteralPath $settingsPath -Algorithm SHA256).Hash -ne $settingsHash) {
        throw 'Upgrade changed the settings sentinel'
    }
    if ((Get-Content -LiteralPath $settingsPath -Raw) -notmatch '(?m)^wander_enabled\s*=\s*true\s*$') {
        throw 'Upgrade did not preserve wander_enabled=true'
    }
    Write-Output "UPGRADE VERIFY: settings-preserved=true ($settingsHash), startup-disabled-preserved=true"

    Invoke-Uninstall -Directory $upgradeDirPath
    Assert-NoTestProcesses
    Assert-RegistryValueAbsent
    Assert-UninstallEntry -Expected $false
    if (Test-Path -LiteralPath $upgradeDirPath) {
        throw "Upgrade uninstall left test install directory: $upgradeDirPath"
    }
    foreach ($state in $dataStates) {
        if (Test-Path -LiteralPath $state.RealPath) {
            throw "Upgrade uninstall left product data path: $($state.RealPath)"
        }
    }
    Write-Output 'UPGRADE UNINSTALL VERIFY: process/run/uninstall/install/settings/log cleanup=true'
    $verificationSucceeded = $true
}
finally {
    $restoreErrors = [System.Collections.Generic.List[string]]::new()

    foreach ($directory in @($testDirPath, $upgradeDirPath)) {
        try {
            Invoke-Uninstall -Directory $directory
        }
        catch {
            Write-Warning "Fallback uninstall failed for ${directory}; safe test cleanup will continue: $($_.Exception.Message)"
        }
    }
    foreach ($process in @(Get-TestProcesses)) {
        try {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        }
        catch {
            $restoreErrors.Add("stop test process $($process.ProcessId): $($_.Exception.Message)")
        }
    }
    foreach ($directory in @($testDirPath, $upgradeDirPath)) {
        try {
            Remove-SafeTree -Path $directory -AllowedRoots @($directory, $workRoot) -Purpose 'final test cleanup' -AllowEqual
        }
        catch {
            $restoreErrors.Add("cleanup ${directory}: $($_.Exception.Message)")
        }
    }

    if ($stateCaptured) {
        try {
            Restore-RegistryValue -SubKey $runKeyPath -Name $runValueName -Snapshot $registryState.Run
        }
        catch {
            $restoreErrors.Add("Run registry restore: $($_.Exception.Message)")
        }
        try {
            Restore-RegistryTree -SubKey $uninstallKeyPath -Snapshot $registryState.Uninstall
        }
        catch {
            $restoreErrors.Add("uninstall registry restore: $($_.Exception.Message)")
        }
        Write-Output "REGISTRY RESTORE: Run=$($registryState.Run.Exists), Uninstall=$($registryState.Uninstall.Exists)"
    }

    foreach ($state in $dataStates) {
        try {
            Remove-IsolatedDataLinks -States @($state)
            if ($state.Existed) {
                if (-not (Test-Path -LiteralPath $state.HoldPath -PathType Container)) {
                    throw "Missing held user data: $($state.HoldPath)"
                }
                Move-Item -LiteralPath $state.HoldPath -Destination $state.RealPath
                $restoredFingerprint = Get-DirectoryFingerprint -Path $state.RealPath
                if ($restoredFingerprint -ne $state.Fingerprint) {
                    throw "Restored user data fingerprint mismatch: $($state.RealPath)"
                }
                Write-Output "USER DATA RESTORE: $($state.RealPath), fingerprint=$restoredFingerprint"
            }
            elseif (Test-Path -LiteralPath $state.RealPath) {
                throw "Test left a user data path that did not exist before: $($state.RealPath)"
            }
        }
        catch {
            $restoreErrors.Add("user data restore ($($state.Name)): $($_.Exception.Message)")
        }
    }

    if ($restoreErrors.Count -eq 0) {
        try {
            Remove-SafeTree -Path $backupRoot -AllowedRoots @($workRoot) -Purpose 'verified backup cleanup'
        }
        catch {
            $restoreErrors.Add("backup cleanup: $($_.Exception.Message)")
        }
    }
    else {
        Write-Warning "Backup retained for recovery: $backupRoot"
    }

    if ($restoreErrors.Count -ne 0) {
        throw "Release verification restore failed: $($restoreErrors -join ' | ')"
    }
}

if (-not $verificationSucceeded) {
    throw 'Release verification did not complete'
}
Write-Output 'RELEASE VERIFY PASSED: ordinary install/self-test/uninstall and upgrade preservation'
