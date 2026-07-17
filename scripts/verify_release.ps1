[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Installer,

    [Parameter(Mandatory = $true)]
    [string]$TestDir,

    [switch]$PreflightOnly,

    [switch]$SimulateUnresolvedShiyiProcess,

    [switch]$ProcessContainmentProbe,

    [switch]$FallbackForeignProcessProbe,

    [switch]$SafeFunctionalFailureProbe,

    [switch]$MutexContentionProbe,

    [switch]$InjectSafeFunctionalFailureAfterStateCapture,

    [switch]$InternalMutexContentionAttempt,

    [switch]$InternalMutexHolderProbe,

    [string]$InternalProbeToken,

    [string]$InternalVerificationId,

    [string]$InternalMutexReadyPath,

    [string]$InternalMutexReleasePath,

    [ValidateRange(1, 3600)]
    [int]$UninstallTimeoutSeconds = 180
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot '..'))
$workRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot 'work'))
$installerPath = (Resolve-Path -LiteralPath $Installer -ErrorAction Stop).Path
$testDirPath = [System.IO.Path]::GetFullPath($TestDir)
$upgradeDirPath = [System.IO.Path]::GetFullPath("$testDirPath-upgrade")
$internalProbeModeCount = @(
    $InjectSafeFunctionalFailureAfterStateCapture,
    $InternalMutexContentionAttempt,
    $InternalMutexHolderProbe
).Where({ $_ }).Count
$internalProductionProbe = $internalProbeModeCount -ne 0
if ($internalProbeModeCount -gt 1) {
    throw 'Only one internal production probe mode may be selected'
}
if ($internalProductionProbe) {
    if (
        $PreflightOnly -or
        -not $InternalProbeToken -or
        $env:SHIYI_INTERNAL_ROLLBACK_PROBE_TOKEN -cne $InternalProbeToken -or
        $InternalVerificationId -cnotmatch '^[0-9a-f]{32}$'
    ) {
        throw 'Internal production probe requires a matching wrapper token, a lowercase 32-hex verification ID, and a production-flow invocation'
    }
    $verificationId = $InternalVerificationId
    if ($InternalMutexHolderProbe) {
        if (-not $InternalMutexReadyPath -or -not $InternalMutexReleasePath) {
            throw 'Internal mutex holder requires ready and release paths'
        }
    }
    elseif ($InternalMutexReadyPath -or $InternalMutexReleasePath) {
        throw 'Internal mutex ready/release paths are valid only with the internal holder probe'
    }
}
else {
    if ($InternalProbeToken -or $InternalVerificationId -or $InternalMutexReadyPath -or $InternalMutexReleasePath) {
        throw 'Internal probe token, verification ID, and holder paths are valid only with an internal production probe'
    }
    $verificationId = [guid]::NewGuid().ToString('N')
}
$backupRoot = [System.IO.Path]::GetFullPath((Join-Path $workRoot "release-verify-$verificationId"))
$registryBackupPath = Join-Path $backupRoot 'registry-state.clixml'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'

$runKeyPath = 'Software\Microsoft\Windows\CurrentVersion\Run'
$runValueName = 'ShiyiDesktopPet'
$uninstallKeyPath = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{5F4B3AD9-7C91-4E2D-A4C4-70C5C4F5A211}_is1'
$roamingPath = [System.IO.Path]::GetFullPath((Join-Path $env:APPDATA 'ShiyiDesktopPet'))
$localPath = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'ShiyiDesktopPet'))
$ownedProcesses = [System.Collections.Generic.List[object]]::new()
$retainedJobHandles = [System.Collections.Generic.List[object]]::new()
$allJobTreesQuiescent = $true
$rollbackSafetyUnknown = $false
$rollbackSafetyReasons = [System.Collections.Generic.List[string]]::new()
$uninstallLaunchCount = 0
$windowsIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
try {
    if ($null -eq $windowsIdentity.User) {
        throw 'Current Windows identity has no user SID'
    }
    $currentUserSidValue = $windowsIdentity.User.Value
}
finally {
    $windowsIdentity.Dispose()
}
$currentUserSid = [System.Security.Principal.SecurityIdentifier]::new($currentUserSidValue)
if ($currentUserSid.Value -cne $currentUserSidValue) {
    throw "Current-user SID was not canonical: $currentUserSidValue"
}
$localSystemSid = [System.Security.Principal.SecurityIdentifier]::new(
    [System.Security.Principal.WellKnownSidType]::LocalSystemSid,
    $null
)
$releaseVerificationMutexName = "Global\ShiyiDesktopPet.ReleaseVerify.$currentUserSidValue.v1"

if ($null -eq ('ShiyiVerifier.JobObject' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace ShiyiVerifier
{
    public sealed class JobObject : IDisposable
    {
        private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
        private SafeFileHandle handle;

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
        {
            public long PerProcessUserTimeLimit;
            public long PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize;
            public UIntPtr MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass;
            public uint SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct IO_COUNTERS
        {
            public ulong ReadOperationCount;
            public ulong WriteOperationCount;
            public ulong OtherOperationCount;
            public ulong ReadTransferCount;
            public ulong WriteTransferCount;
            public ulong OtherTransferCount;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        {
            public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
            public IO_COUNTERS IoInfo;
            public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit;
            public UIntPtr PeakProcessMemoryUsed;
            public UIntPtr PeakJobMemoryUsed;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_BASIC_ACCOUNTING_INFORMATION
        {
            public long TotalUserTime;
            public long TotalKernelTime;
            public long ThisPeriodTotalUserTime;
            public long ThisPeriodTotalKernelTime;
            public uint TotalPageFaultCount;
            public uint TotalProcesses;
            public uint ActiveProcesses;
            public uint TotalTerminatedProcesses;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CreateJobObject(IntPtr securityAttributes, string name);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetInformationJobObject(
            IntPtr job,
            int infoClass,
            IntPtr information,
            uint informationLength);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool QueryInformationJobObject(
            IntPtr job,
            int infoClass,
            out JOBOBJECT_BASIC_ACCOUNTING_INFORMATION information,
            uint informationLength,
            IntPtr returnLength);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool TerminateJobObject(IntPtr job, uint exitCode);

        public JobObject()
        {
            IntPtr raw = CreateJobObject(IntPtr.Zero, null);
            if (raw == IntPtr.Zero)
                throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateJobObject failed");

            handle = new SafeFileHandle(raw, true);
            var limits = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            int size = Marshal.SizeOf<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>();
            IntPtr buffer = Marshal.AllocHGlobal(size);
            try
            {
                Marshal.StructureToPtr(limits, buffer, false);
                if (!SetInformationJobObject(raw, 9, buffer, (uint)size))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "SetInformationJobObject failed");
            }
            finally
            {
                Marshal.FreeHGlobal(buffer);
            }
        }

        public void Assign(Process process)
        {
            if (process == null) throw new ArgumentNullException(nameof(process));
            if (!AssignProcessToJobObject(handle.DangerousGetHandle(), process.Handle))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "AssignProcessToJobObject failed");
        }

        public uint ActiveProcessCount
        {
            get
            {
                JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting;
                int size = Marshal.SizeOf<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>();
                if (!QueryInformationJobObject(
                    handle.DangerousGetHandle(), 1, out accounting, (uint)size, IntPtr.Zero))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "QueryInformationJobObject failed");
                return accounting.ActiveProcesses;
            }
        }

        public void Terminate(uint exitCode)
        {
            if (!TerminateJobObject(handle.DangerousGetHandle(), exitCode))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "TerminateJobObject failed");
        }

        public void Dispose()
        {
            if (handle != null)
            {
                handle.Dispose();
                handle = null;
            }
        }
    }
}
'@
}

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

function Test-PathsOverlap {
    param(
        [Parameter(Mandatory = $true)][string]$First,
        [Parameter(Mandatory = $true)][string]$Second
    )

    $firstPath = [System.IO.Path]::GetFullPath($First).TrimEnd('\', '/')
    $secondPath = [System.IO.Path]::GetFullPath($Second).TrimEnd('\', '/')
    return (
        $firstPath.Equals($secondPath, [System.StringComparison]::OrdinalIgnoreCase) -or
        (Test-DescendantPath -Path $firstPath -Root $secondPath) -or
        (Test-DescendantPath -Path $secondPath -Root $firstPath)
    )
}

function Assert-NoReparseComponents {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Purpose
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $volumeRoot = [System.IO.Path]::GetPathRoot($fullPath)
    $current = $volumeRoot
    $relative = $fullPath.Substring($volumeRoot.Length)
    foreach ($component in $relative.Split(
        [char[]]@('\', '/'),
        [System.StringSplitOptions]::RemoveEmptyEntries
    )) {
        $current = Join-Path $current $component
        if (-not (Test-Path -LiteralPath $current)) {
            break
        }
        $item = Get-Item -LiteralPath $current -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing $Purpose through reparse component: $current"
        }
    }
    return $fullPath
}

function Get-NoFollowTreeItems {
    param([Parameter(Mandatory = $true)][string]$Path)

    $root = Assert-NoReparseComponents -Path $Path -Purpose 'recursive user-data traversal'
    $pending = [System.Collections.Generic.Queue[string]]::new()
    $items = [System.Collections.Generic.List[object]]::new()
    $pending.Enqueue($root)
    while ($pending.Count -gt 0) {
        $directory = $pending.Dequeue()
        foreach ($item in @(Get-ChildItem -LiteralPath $directory -Force)) {
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Refusing nested reparse point in user data: $($item.FullName)"
            }
            $items.Add($item)
            if ($item.PSIsContainer) {
                $pending.Enqueue($item.FullName)
            }
        }
    }
    return $items.ToArray()
}

function Assert-SafeRecursiveTarget {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$AllowedRoots,
        [Parameter(Mandatory = $true)][string]$Purpose
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $safeRoot = $null
    foreach ($candidate in $AllowedRoots) {
        $fullCandidate = [System.IO.Path]::GetFullPath($candidate)
        if (Test-DescendantPath -Path $fullPath -Root $fullCandidate) {
            $safeRoot = $fullCandidate
            break
        }
    }
    if ($null -eq $safeRoot) {
        throw "Refusing recursive $Purpose outside allowed roots: $fullPath"
    }
    [void](Assert-NoReparseComponents -Path $fullPath -Purpose "recursive $Purpose")
    if (Test-Path -LiteralPath $fullPath) {
        foreach ($item in @(Get-NoFollowTreeItems -Path $fullPath)) {
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Refusing recursive $Purpose containing a reparse point: $($item.FullName)"
            }
        }
    }
    Write-Host "SAFE PATH CHECK [$Purpose]: $fullPath <= $safeRoot"
    return $fullPath
}

function Remove-SafeTree {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$AllowedRoots,
        [Parameter(Mandatory = $true)][string]$Purpose
    )

    $fullPath = Assert-SafeRecursiveTarget -Path $Path -AllowedRoots $AllowedRoots -Purpose $Purpose
    if (Test-Path -LiteralPath $fullPath) {
        Remove-Item -LiteralPath $fullPath -Recurse -Force
    }
}

function Assert-TestRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$ProtectedPaths
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    if (-not (Test-DescendantPath -Path $fullPath -Root $workRoot)) {
        throw "Test directory must be a strict child of verifier-owned work root: $fullPath"
    }
    [void](Assert-NoReparseComponents -Path $fullPath -Purpose 'test-root preflight')
    foreach ($protected in $ProtectedPaths) {
        if ($protected -and (Test-PathsOverlap -First $fullPath -Second $protected)) {
            throw "Test directory overlaps protected path: $fullPath <-> $protected"
        }
    }
    if (Test-Path -LiteralPath $fullPath) {
        if (@(Get-NoFollowTreeItems -Path $fullPath).Count -ne 0) {
            throw "Existing test directory is not empty and is not verifier-owned: $fullPath"
        }
    }
    Write-Output "SAFE TEST ROOT: $fullPath"
}

function Get-DirectoryFingerprint {
    param([Parameter(Mandatory = $true)][string]$Path)

    $root = [System.IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $lines = [System.Collections.Generic.List[string]]::new()
    foreach ($item in @(Get-NoFollowTreeItems -Path $root | Sort-Object FullName)) {
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
        foreach ($name in @($Key.GetValueNames() | Sort-Object)) {
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
        foreach ($name in @($Key.GetSubKeyNames() | Sort-Object)) {
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

function Convert-RegistrySnapshotToCanonicalJson {
    param([Parameter(Mandatory = $true)]$Snapshot)

    return ($Snapshot | ConvertTo-Json -Depth 100 -Compress)
}

function Assert-RegistrySnapshotEqual {
    param(
        [Parameter(Mandatory = $true)]$Expected,
        [Parameter(Mandatory = $true)]$Actual,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $expectedJson = Convert-RegistrySnapshotToCanonicalJson -Snapshot $Expected
    $actualJson = Convert-RegistrySnapshotToCanonicalJson -Snapshot $Actual
    if ($actualJson -cne $expectedJson) {
        throw "$Description restore mismatch. expected=$expectedJson actual=$actualJson"
    }
}

function Get-RecordedInstallLocations {
    $snapshot = Get-RegistryTreeSnapshot -SubKey $uninstallKeyPath
    if (-not $snapshot.Exists) {
        return @()
    }
    $locations = @(
        foreach ($value in $snapshot.Node.Values) {
            if ($value.Name -eq 'InstallLocation' -and $value.Value) {
                [System.IO.Path]::GetFullPath([string]$value.Value)
            }
        }
    )
    return $locations
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
        $startedAt = $process.StartTime.ToUniversalTime()
        $resolvedFile = [System.IO.Path]::GetFullPath($FilePath)
        if (
            [System.IO.Path]::GetFileName($resolvedFile) -ieq 'ShiyiDesktopPet.exe' -and
            ((Test-DescendantPath -Path $resolvedFile -Root $testDirPath) -or
             (Test-DescendantPath -Path $resolvedFile -Root $upgradeDirPath))
        ) {
            $ownedProcesses.Add([pscustomobject]@{
                ProcessId = $process.Id
                StartedAtUtc = $startedAt
                ExecutablePath = $resolvedFile
            })
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            $process.Kill($true)
            if (-not $process.WaitForExit(10000)) {
                throw "Timed-out process tree did not terminate: $FilePath (PID $($process.Id))"
            }
            throw "Process timed out after $TimeoutSeconds seconds: $FilePath; process-tree kill requested and root exit confirmed"
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

function Wait-JobTreeQuiescent {
    param(
        [Parameter(Mandatory = $true)][ShiyiVerifier.JobObject]$Job,
        [Parameter(Mandatory = $true)][int]$TimeoutMilliseconds
    )

    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMilliseconds)
    $lastActive = $null
    do {
        try {
            $lastActive = $Job.ActiveProcessCount
        }
        catch {
            return [pscustomobject]@{
                Zero = $false
                LastActive = $lastActive
                QueryError = $_.Exception.Message
            }
        }
        if ($lastActive -eq 0) {
            return [pscustomobject]@{ Zero = $true; LastActive = 0; QueryError = $null }
        }
        Start-Sleep -Milliseconds 50
    } while ([DateTime]::UtcNow -lt $deadline)

    return [pscustomobject]@{ Zero = $false; LastActive = $lastActive; QueryError = $null }
}

function Invoke-GatedJobProcess {
    param(
        [Parameter(Mandatory = $true)][string]$HelperPath,
        [string[]]$HelperArguments = @(),
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $gateName = "Local\ShiyiVerifier-$([guid]::NewGuid().ToString('N'))"
    $gate = [System.Threading.EventWaitHandle]::new(
        $false,
        [System.Threading.EventResetMode]::ManualReset,
        $gateName
    )
    $job = [ShiyiVerifier.JobObject]::new()
    $jobRetained = $false
    $jobAssigned = $false
    $treeQuiescent = $false
    $processStarted = $false
    $process = [System.Diagnostics.Process]::new()
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = (Get-Process -Id $PID).Path
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true
    foreach ($argument in @('-NoProfile', '-NonInteractive', '-File', $HelperPath, '-GateName', $gateName) + $HelperArguments) {
        $startInfo.ArgumentList.Add($argument)
    }
    $process.StartInfo = $startInfo
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        [void]$process.Start()
        $processStarted = $true
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()

        try {
            $job.Assign($process)
            $jobAssigned = $true
        }
        catch {
            # The helper is still blocked on the unsignaled gate, so no child
            # or uninstaller can exist when assignment fails.
            $process.Kill($true)
            if (-not $process.WaitForExit(10000)) {
                $script:allJobTreesQuiescent = $false
                throw "Startup-gated helper could not be assigned and its root exit was not confirmed: $Description"
            }
            throw "Startup-gated helper was not assigned to the kill-on-close job; uninstaller was not launched: $Description; $($_.Exception.Message)"
        }

        if (-not $gate.Set()) {
            throw "Failed to release startup gate after job assignment: $Description"
        }

        $poll = Wait-JobTreeQuiescent -Job $job -TimeoutMilliseconds ($TimeoutSeconds * 1000)
        if (-not $poll.Zero) {
            try {
                $job.Terminate(1460)
            }
            catch {
                throw "Timed-out job termination failed: $Description; $($_.Exception.Message)"
            }
            $terminationPoll = Wait-JobTreeQuiescent -Job $job -TimeoutMilliseconds 10000
            if (-not $terminationPoll.Zero) {
                $script:allJobTreesQuiescent = $false
                $script:retainedJobHandles.Add($job)
                $jobRetained = $true
                throw "JOB QUIESCENCE FAILURE: $Description; active=$($terminationPoll.LastActive); queryError=$($terminationPoll.QueryError)"
            }
            $treeQuiescent = $true
            if (-not $process.WaitForExit(5000)) {
                $script:allJobTreesQuiescent = $false
                throw "Job reported active=0 but helper root did not signal exit: $Description"
            }
            throw "JOB TIMEOUT: $Description; timeout=$TimeoutSeconds seconds; terminated=true; job-active=0; helper-exit-confirmed=true"
        }

        $treeQuiescent = $true
        if (-not $process.WaitForExit(5000)) {
            $script:allJobTreesQuiescent = $false
            throw "Job reported active=0 but helper root did not signal exit: $Description"
        }
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            Stdout = $stdoutTask.GetAwaiter().GetResult().Trim()
            Stderr = $stderrTask.GetAwaiter().GetResult().Trim()
            ElapsedSeconds = [Math]::Round($stopwatch.Elapsed.TotalSeconds, 3)
            JobActive = 0
        }
    }
    catch {
        if ($jobAssigned -and -not $treeQuiescent -and -not $jobRetained) {
            try {
                $job.Terminate(1460)
                $failurePoll = Wait-JobTreeQuiescent -Job $job -TimeoutMilliseconds 10000
                if ($failurePoll.Zero) {
                    $treeQuiescent = $true
                    [void]$process.WaitForExit(5000)
                }
                else {
                    $script:allJobTreesQuiescent = $false
                    $script:retainedJobHandles.Add($job)
                    $jobRetained = $true
                    throw "JOB QUIESCENCE FAILURE after error: $Description; active=$($failurePoll.LastActive); queryError=$($failurePoll.QueryError)"
                }
            }
            catch {
                if (-not $jobRetained) {
                    $script:allJobTreesQuiescent = $false
                    $script:retainedJobHandles.Add($job)
                    $jobRetained = $true
                }
                throw "JOB QUIESCENCE FAILURE after error: $Description; $($_.Exception.Message)"
            }
        }
        throw
    }
    finally {
        $stopwatch.Stop()
        $gate.Dispose()
        if ($processStarted) {
            $process.Dispose()
        }
        if (-not $jobRetained) {
            $job.Dispose()
        }
    }
}

function Assert-UninstallOwnershipGate {
    param([Parameter(Mandatory = $true)][string]$Context)

    try {
        Stop-OwnedProcesses
        Assert-NoTestProcesses
    }
    catch {
        $script:rollbackSafetyUnknown = $true
        $script:rollbackSafetyReasons.Add("process ownership ($Context): $($_.Exception.Message)")
        throw
    }
    Write-Output "UNINSTALL OWNERSHIP GATE [$Context]: global-shiyi=0; owned-processes-reconciled=true"
}

function Test-RollbackSafetyKnown {
    return ($allJobTreesQuiescent -and -not $rollbackSafetyUnknown)
}

function Format-ExceptionDetails {
    param([AllowNull()][System.Exception]$Exception)

    if ($null -eq $Exception) {
        return '<none>'
    }
    $parts = [System.Collections.Generic.List[string]]::new()
    $current = $Exception
    while ($null -ne $current) {
        $parts.Add("$($current.GetType().FullName): $($current.Message)")
        $current = $current.InnerException
    }
    return ($parts -join ' -> INNER: ')
}

function New-ReleaseVerificationMutexSecurity {
    $security = [System.Security.AccessControl.MutexSecurity]::new()
    $security.SetAccessRuleProtection($true, $false)
    $security.SetOwner($currentUserSid)
    foreach ($sid in @($currentUserSid, $localSystemSid)) {
        $security.AddAccessRule([System.Security.AccessControl.MutexAccessRule]::new(
            $sid,
            [System.Security.AccessControl.MutexRights]::FullControl,
            [System.Security.AccessControl.AccessControlType]::Allow
        ))
    }
    return $security
}

function Assert-ReleaseVerificationMutexAcl {
    param([Parameter(Mandatory = $true)][System.Threading.Mutex]$Mutex)

    $security = [System.Threading.ThreadingAclExtensions]::GetAccessControl($Mutex)
    if (-not $security.AreAccessRulesProtected) {
        throw 'Release-verification mutex DACL is not protected from inheritance'
    }
    $owner = $security.GetOwner([System.Security.Principal.SecurityIdentifier]).Value
    if ($owner -cne $currentUserSidValue) {
        throw "Release-verification mutex owner is not the current user SID: $owner"
    }
    $rules = @($security.GetAccessRules(
        $true,
        $false,
        [System.Security.Principal.SecurityIdentifier]
    ))
    $allowedSids = @($currentUserSidValue, $localSystemSid.Value)
    if ($rules.Count -ne 2) {
        throw "Release-verification mutex must have exactly two explicit DACL entries, found $($rules.Count)"
    }
    foreach ($rule in $rules) {
        $sid = $rule.IdentityReference.Value
        if ($sid -notin $allowedSids) {
            throw "Release-verification mutex DACL contains a broad or unexpected principal: $sid"
        }
        if (
            $rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow -or
            $rule.MutexRights -ne [System.Security.AccessControl.MutexRights]::FullControl -or
            $rule.IsInherited
        ) {
            throw "Release-verification mutex DACL entry is not explicit FullControl Allow: SID=$sid rights=$($rule.MutexRights) type=$($rule.AccessControlType) inherited=$($rule.IsInherited)"
        }
    }
    foreach ($requiredSid in $allowedSids) {
        if (@($rules | Where-Object { $_.IdentityReference.Value -ceq $requiredSid }).Count -ne 1) {
            throw "Release-verification mutex DACL does not contain exactly one rule for $requiredSid"
        }
    }
    return [pscustomobject]@{
        Protected = $true
        Owner = $owner
        Rules = @($rules | Sort-Object { $_.IdentityReference.Value } | ForEach-Object {
            "$($_.IdentityReference.Value):$($_.MutexRights):$($_.AccessControlType)"
        })
    }
}

function Enter-ReleaseVerificationMutex {
    $createdNew = $false
    $mutexSecurity = New-ReleaseVerificationMutexSecurity
    $mutex = [System.Threading.MutexAcl]::Create(
        $false,
        $releaseVerificationMutexName,
        [ref]$createdNew,
        $mutexSecurity
    )
    $acquired = $false
    try {
        $acl = Assert-ReleaseVerificationMutexAcl -Mutex $mutex
        Write-Host "RELEASE VERIFY MUTEX ACL: name=$releaseVerificationMutexName; protected=$($acl.Protected); owner=$($acl.Owner); rules=$($acl.Rules -join ','); broad-principal=false"
        try {
            $acquired = $mutex.WaitOne(0)
        }
        catch [System.Threading.AbandonedMutexException] {
            $acquired = $true
        }
        if (-not $acquired) {
            throw "Another Shiyi release verification is already active for the current user: $releaseVerificationMutexName"
        }
        Write-Host "RELEASE VERIFY MUTEX ACQUIRED: $releaseVerificationMutexName"
        return $mutex
    }
    catch {
        if (-not $acquired) {
            $mutex.Dispose()
        }
        throw
    }
}

function Exit-ReleaseVerificationMutex {
    param([Parameter(Mandatory = $true)][System.Threading.Mutex]$Mutex)

    try {
        $Mutex.ReleaseMutex()
    }
    finally {
        $Mutex.Dispose()
    }
    Write-Host "RELEASE VERIFY MUTEX RELEASED: $releaseVerificationMutexName"
}

function Invoke-InProcessProductionProbe {
    param(
        [Parameter(Mandatory = $true)][string]$Token,
        [Parameter(Mandatory = $true)][string]$VerificationId,
        [Parameter(Mandatory = $true)][ValidateSet('FunctionalFailure', 'MutexContention')][string]$Mode
    )

    $records = [System.Collections.Generic.List[object]]::new()
    $caughtException = $null
    $arguments = @{
        Installer = $installerPath
        TestDir = $testDirPath
        UninstallTimeoutSeconds = $UninstallTimeoutSeconds
        InternalProbeToken = $Token
        InternalVerificationId = $VerificationId
    }
    if ($Mode -eq 'FunctionalFailure') {
        $arguments.InjectSafeFunctionalFailureAfterStateCapture = $true
    }
    else {
        $arguments.InternalMutexContentionAttempt = $true
    }

    try {
        & $PSCommandPath @arguments *>&1 | ForEach-Object {
            $records.Add($_)
        }
    }
    catch {
        $caughtException = $_.Exception
        $records.Add($_)
    }

    $recordText = @($records | ForEach-Object { $_.ToString() })
    $exceptionDetails = Format-ExceptionDetails -Exception $caughtException
    return [pscustomobject]@{
        Records = $records.ToArray()
        Exception = $caughtException
        ExceptionDetails = $exceptionDetails
        Evidence = (($recordText + $exceptionDetails) -join "`n")
    }
}

function Invoke-Uninstall {
    param([Parameter(Mandatory = $true)][string]$Directory)

    $uninstaller = Join-Path $Directory 'unins000.exe'
    if (Test-Path -LiteralPath $uninstaller -PathType Leaf) {
        Assert-UninstallOwnershipGate -Context $Directory
        $logPath = Join-Path $backupRoot "uninstall-$([System.IO.Path]::GetFileName($Directory))-$([guid]::NewGuid().ToString('N')).log"
        $helperPath = Join-Path $backupRoot "wait-uninstall-$([guid]::NewGuid().ToString('N')).ps1"
        $helperText = @'
param([string]$GateName, [string]$Uninstaller, [string]$LogPath)
$gate = [System.Threading.EventWaitHandle]::OpenExisting($GateName)
try {
    if (-not $gate.WaitOne(30000)) {
        exit 1460
    }
}
finally {
    $gate.Dispose()
}
$arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', ('/LOG="{0}"' -f $LogPath))
$process = Start-Process -FilePath $Uninstaller -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
$exitCode = $process.ExitCode
$process.Dispose()
exit $exitCode
'@
        [System.IO.File]::WriteAllText($helperPath, $helperText, [System.Text.UTF8Encoding]::new($false))
        $script:uninstallLaunchCount++
        $result = Invoke-GatedJobProcess -HelperPath $helperPath -HelperArguments @(
            '-Uninstaller',
            $uninstaller,
            '-LogPath',
            $logPath
        ) -TimeoutSeconds $UninstallTimeoutSeconds -Description "Inno uninstall $Directory"
        $exitCode = $result.ExitCode
        if ($exitCode -ne 0) {
            $logTail = if (Test-Path -LiteralPath $logPath -PathType Leaf) {
                (Get-Content -LiteralPath $logPath -Tail 60) -join "`n"
            }
            else {
                '<no uninstall log>'
            }
            throw "silent uninstall failed with exit code $exitCode; job-active=$($result.JobActive); elapsed=$($result.ElapsedSeconds) seconds. log=$logTail"
        }
        Write-Output "JOB-CONTAINED UNINSTALL: directory=$Directory; timeout=$UninstallTimeoutSeconds seconds; elapsed=$($result.ElapsedSeconds) seconds; exit=$exitCode; job-active=$($result.JobActive)"
    }
}

function Get-TestProcesses {
    return @(Get-CimInstance Win32_Process -Filter "Name = 'ShiyiDesktopPet.exe'" -ErrorAction Stop)
}

function Assert-NoTestProcesses {
    $processes = @(Get-TestProcesses)
    if ($processes.Count -ne 0) {
        $details = @($processes | ForEach-Object {
            "PID=$($_.ProcessId), path=$(if ($_.ExecutablePath) { $_.ExecutablePath } else { '<unavailable>' })"
        }) -join '; '
        throw "ShiyiDesktopPet process remains or appeared during verification: $details"
    }
}

function Stop-OwnedProcesses {
    foreach ($record in $ownedProcesses) {
        $process = Get-Process -Id $record.ProcessId -ErrorAction SilentlyContinue
        if ($null -eq $process) {
            continue
        }
        $startedAt = $process.StartTime.ToUniversalTime()
        if ($startedAt -ne $record.StartedAtUtc) {
            throw "Refusing to stop reused PID $($record.ProcessId)"
        }
        $processPath = [System.IO.Path]::GetFullPath($process.Path)
        if (
            $processPath -ine $record.ExecutablePath -or
            (-not (Test-DescendantPath -Path $processPath -Root $workRoot))
        ) {
            throw "Refusing to stop unowned process PID $($record.ProcessId): $processPath"
        }
        $process.Kill($true)
        if (-not $process.WaitForExit(10000)) {
            throw "Owned process did not terminate: PID $($record.ProcessId)"
        }
    }
}

function Assert-RegistryValueAbsent {
    $snapshot = Get-RegistryValueSnapshot -SubKey $runKeyPath -Name $runValueName
    if ($snapshot.Exists) {
        throw "Unexpected HKCU Run value: $($snapshot.Value)"
    }
}

function Assert-RegistryValueExact {
    param([Parameter(Mandatory = $true)][string]$Expected)

    $snapshot = Get-RegistryValueSnapshot -SubKey $runKeyPath -Name $runValueName
    if (-not $snapshot.Exists -or $snapshot.Kind -ne 'String' -or $snapshot.Value -cne $Expected) {
        throw "HKCU Run value mismatch. expected String '$Expected'; actual=$($snapshot | ConvertTo-Json -Compress)"
    }
}

function Set-StartupViaManager {
    param(
        [Parameter(Mandatory = $true)][string]$Directory,
        [Parameter(Mandatory = $true)][bool]$Enabled
    )

    $startupCode = 'from pathlib import Path; import sys; from shiyi_desktop_pet.startup import StartupManager, WinRegRunKey; StartupManager(WinRegRunKey(), Path(sys.argv[1])).set_enabled(sys.argv[2] == "true")'
    $oldPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = Join-Path $repoRoot 'src'
        [void](Invoke-CheckedProcess -FilePath $python -Arguments @(
            '-c',
            $startupCode,
            (Join-Path $Directory 'ShiyiDesktopPet.exe'),
            $Enabled.ToString().ToLowerInvariant()
        ) -TimeoutSeconds 30 -Description "StartupManager set_enabled($Enabled)")
    }
    finally {
        $env:PYTHONPATH = $oldPythonPath
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

function Ensure-IsolatedDataRoots {
    param([Parameter(Mandatory = $true)][object[]]$States)

    foreach ($state in $States) {
        if (Test-Path -LiteralPath $state.RealPath) {
            throw "Verifier-owned data root must start absent ($($state.Name)): $($state.RealPath)"
        }
        [void](Assert-NoReparseComponents -Path (Split-Path -Parent $state.RealPath) -Purpose 'verifier data-root creation')
        [void](New-Item -ItemType Directory -Path $state.RealPath)
        [System.IO.File]::WriteAllText(
            $state.OwnershipMarker,
            $verificationId,
            [System.Text.UTF8Encoding]::new($false)
        )
        [void](Assert-NoReparseComponents -Path $state.RealPath -Purpose 'verifier data-root creation')
        Write-Output "STATE ISOLATION: verifier-owned ordinary root $($state.RealPath), marker=$($state.OwnershipMarker)"
    }
}

function Assert-DirectSentinel {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedText
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Missing direct isolated sentinel: $Path"
    }
    $actual = [System.IO.File]::ReadAllText($Path)
    if ($actual -cne $ExpectedText) {
        throw "Direct isolated sentinel content mismatch: $Path"
    }
}

function Assert-IsolatedTargetsClean {
    param(
        [Parameter(Mandatory = $true)][object[]]$States,
        [Parameter(Mandatory = $true)][string]$Phase
    )

    foreach ($state in $States) {
        if (Test-Path -LiteralPath $state.Target) {
            $items = @(Get-NoFollowTreeItems -Path $state.Target)
            throw "$Phase left direct verifier-owned data root ($($state.Name)): root=$($state.Target); items=$($items.FullName -join ', ')"
        }
    }
    Write-Output "DIRECT TARGET VERIFY [$Phase]: roots-absent=true"
}

function Remove-VerifierDataRoots {
    param([Parameter(Mandatory = $true)][object[]]$States)

    foreach ($state in $States) {
        if (-not (Test-Path -LiteralPath $state.RealPath)) {
            continue
        }
        [void](Assert-NoReparseComponents -Path $state.RealPath -Purpose 'verifier data-root cleanup')
        [void](Get-NoFollowTreeItems -Path $state.RealPath)
        if (-not (Test-Path -LiteralPath $state.OwnershipMarker -PathType Leaf)) {
            throw "Refusing to remove data root without verifier ownership marker: $($state.RealPath)"
        }
        $markerValue = [System.IO.File]::ReadAllText($state.OwnershipMarker)
        if ($markerValue -cne $verificationId) {
            throw "Refusing data-root cleanup with mismatched ownership marker: $($state.OwnershipMarker)"
        }
        Remove-Item -LiteralPath $state.RealPath -Recurse -Force
        Write-Output "OWNED DATA CLEANUP: $($state.RealPath)"
    }
}

function Invoke-ProcessContainmentProbe {
    $probeRoot = Join-Path $workRoot "job-timeout-probe-$([guid]::NewGuid().ToString('N'))"
    if (-not (Test-DescendantPath -Path $probeRoot -Root $workRoot)) {
        throw "Unsafe containment probe root: $probeRoot"
    }
    [void](Assert-NoReparseComponents -Path $workRoot -Purpose 'job-timeout probe')
    [void](New-Item -ItemType Directory -Path $probeRoot)
    $childPath = Join-Path $probeRoot 'long-child.ps1'
    $helperPath = Join-Path $probeRoot 'gated-helper.ps1'
    $pidPath = Join-Path $probeRoot 'child.pid'
    $heartbeatPath = Join-Path $probeRoot 'heartbeat.log'
    $childText = @'
param([string]$PidPath, [string]$HeartbeatPath)
$current = [System.Diagnostics.Process]::GetCurrentProcess()
[System.IO.File]::WriteAllText($PidPath, ("{0}|{1}" -f $PID, $current.StartTime.ToUniversalTime().Ticks))
while ($true) {
    [System.IO.File]::AppendAllText($HeartbeatPath, ("{0:o}`n" -f [DateTime]::UtcNow))
    Start-Sleep -Milliseconds 100
}
'@
    $helperText = @'
param([string]$GateName, [string]$ChildPath, [string]$PidPath, [string]$HeartbeatPath)
$gate = [System.Threading.EventWaitHandle]::OpenExisting($GateName)
try {
    if (-not $gate.WaitOne(30000)) { exit 1460 }
}
finally {
    $gate.Dispose()
}
$startInfo = [System.Diagnostics.ProcessStartInfo]::new()
$startInfo.FileName = (Get-Process -Id $PID).Path
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true
foreach ($argument in @('-NoProfile', '-NonInteractive', '-File', $ChildPath, '-PidPath', $PidPath, '-HeartbeatPath', $HeartbeatPath)) {
    $startInfo.ArgumentList.Add($argument)
}
$child = [System.Diagnostics.Process]::new()
$child.StartInfo = $startInfo
[void]$child.Start()
$child.WaitForExit()
$exitCode = $child.ExitCode
$child.Dispose()
exit $exitCode
'@
    [System.IO.File]::WriteAllText($childPath, $childText, [System.Text.UTF8Encoding]::new($false))
    [System.IO.File]::WriteAllText($helperPath, $helperText, [System.Text.UTF8Encoding]::new($false))

    $probePassed = $false
    try {
        try {
            [void](Invoke-GatedJobProcess -HelperPath $helperPath -HelperArguments @(
                '-ChildPath', $childPath,
                '-PidPath', $pidPath,
                '-HeartbeatPath', $heartbeatPath
            ) -TimeoutSeconds 3 -Description 'deterministic long-child containment probe')
            throw 'Containment probe unexpectedly completed without timeout'
        }
        catch {
            if ($_.Exception.Message -notmatch 'JOB TIMEOUT:.*job-active=0.*helper-exit-confirmed=true') {
                throw
            }
        }
        if (-not $allJobTreesQuiescent) {
            throw 'Containment probe did not preserve the global job-quiescence proof'
        }
        if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf) -or -not (Test-Path -LiteralPath $heartbeatPath -PathType Leaf)) {
            throw 'Containment probe child did not create PID/heartbeat evidence before timeout'
        }
        $identity = [System.IO.File]::ReadAllText($pidPath).Split('|')
        $childPid = [int]$identity[0]
        $childStartTicks = [long]$identity[1]
        $live = Get-Process -Id $childPid -ErrorAction SilentlyContinue
        if ($null -ne $live -and $live.StartTime.ToUniversalTime().Ticks -eq $childStartTicks) {
            throw "Containment probe child is still alive after job active=0: PID $childPid"
        }
        $firstLength = (Get-Item -LiteralPath $heartbeatPath).Length
        Start-Sleep -Milliseconds 500
        $secondLength = (Get-Item -LiteralPath $heartbeatPath).Length
        if ($firstLength -ne $secondLength) {
            throw 'Containment probe heartbeat continued after job active=0'
        }
        $probePassed = $true
        Write-Output "JOB TIMEOUT PROBE PASSED: job-active=0; child-pid=$childPid terminated=true; heartbeat-stable=true; product-state-mutated=false"
    }
    finally {
        if ($probePassed -and (Test-Path -LiteralPath $probeRoot)) {
            Remove-SafeTree -Path $probeRoot -AllowedRoots @($workRoot) -Purpose 'job-timeout probe cleanup'
        }
        elseif (Test-Path -LiteralPath $probeRoot) {
            Write-Warning "Containment probe evidence retained after failure: $probeRoot"
        }
    }
}

function Invoke-FallbackForeignProcessProbe {
    $priorSafetyUnknown = $rollbackSafetyUnknown
    $priorSafetyReasons = @($rollbackSafetyReasons)
    $probeRoot = Join-Path $workRoot "fallback-foreign-probe-$([guid]::NewGuid().ToString('N'))"
    $dummyInstall = Join-Path $probeRoot 'dummy-install'
    if (-not (Test-DescendantPath -Path $probeRoot -Root $workRoot)) {
        throw "Unsafe foreign-process probe root: $probeRoot"
    }
    [void](Assert-NoReparseComponents -Path $workRoot -Purpose 'foreign-process probe')
    [void](New-Item -ItemType Directory -Path $dummyInstall -Force)
    $foreignExe = Join-Path $probeRoot 'ShiyiDesktopPet.exe'
    $dummyUninstaller = Join-Path $dummyInstall 'unins000.exe'
    Copy-Item -LiteralPath (Join-Path $env:SystemRoot 'System32\ping.exe') -Destination $foreignExe
    Copy-Item -LiteralPath (Join-Path $env:SystemRoot 'System32\ping.exe') -Destination $dummyUninstaller

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $foreignExe
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($argument in @('127.0.0.1', '-n', '60', '-w', '1000')) {
        $startInfo.ArgumentList.Add($argument)
    }
    $foreign = [System.Diagnostics.Process]::new()
    $foreign.StartInfo = $startInfo
    $probePassed = $false
    try {
        [void]$foreign.Start()
        $foreignStart = $foreign.StartTime.ToUniversalTime()
        $deadline = [DateTime]::UtcNow.AddSeconds(10)
        do {
            $observed = @(Get-TestProcesses | Where-Object ProcessId -eq $foreign.Id)
            if ($observed.Count -eq 1) { break }
            Start-Sleep -Milliseconds 50
        } while ([DateTime]::UtcNow -lt $deadline)
        if ($observed.Count -ne 1) {
            throw "Foreign-process probe was not visible to fail-closed WMI enumeration: PID $($foreign.Id)"
        }

        $launchesBefore = $uninstallLaunchCount
        try {
            Invoke-Uninstall -Directory $dummyInstall
            throw 'Foreign-process probe unexpectedly allowed fallback uninstall'
        }
        catch {
            if ($_.Exception.Message -notmatch 'ShiyiDesktopPet process remains or appeared during verification') {
                throw
            }
        }
        if ($uninstallLaunchCount -ne $launchesBefore) {
            throw 'Foreign-process probe incremented uninstall launch count before refusal'
        }
        if (-not $rollbackSafetyUnknown) {
            throw 'Foreign-process probe was not classified as rollback-safety unknown'
        }
        $stillLive = Get-Process -Id $foreign.Id -ErrorAction SilentlyContinue
        if ($null -eq $stillLive -or $stillLive.StartTime.ToUniversalTime() -ne $foreignStart) {
            throw 'Foreign-process probe process was stopped or replaced by the ownership gate'
        }
        $probePassed = $true
        Write-Output "FALLBACK FOREIGN PROBE PASSED: foreign-pid=$($foreign.Id) preserved=true; uninstall-launch-delta=0; rollback-safety-unknown=true; product-state-mutated=false"
    }
    finally {
        if (-not $foreign.HasExited) {
            $foreign.Kill($true)
            if (-not $foreign.WaitForExit(10000)) {
                throw "Controlled foreign-process probe did not terminate: PID $($foreign.Id)"
            }
        }
        $foreign.Dispose()
        if ($probePassed -and (Test-Path -LiteralPath $probeRoot)) {
            Remove-SafeTree -Path $probeRoot -AllowedRoots @($workRoot) -Purpose 'foreign-process probe cleanup'
        }
        elseif (Test-Path -LiteralPath $probeRoot) {
            Write-Warning "Foreign-process probe evidence retained after failure: $probeRoot"
        }
        $script:rollbackSafetyUnknown = $priorSafetyUnknown
        $script:rollbackSafetyReasons.Clear()
        foreach ($reason in $priorSafetyReasons) {
            $script:rollbackSafetyReasons.Add($reason)
        }
    }
}

function Get-ProtectedProductStateSnapshot {
    $holds = @(Get-ChildItem -LiteralPath $env:APPDATA, $env:LOCALAPPDATA -Force -ErrorAction Stop |
        Where-Object Name -like 'ShiyiDesktopPet.sdd-hold-*' |
        Sort-Object FullName |
        ForEach-Object {
            $fingerprint = if ($_.PSIsContainer) { Get-DirectoryFingerprint -Path $_.FullName } else { '<not-a-directory>' }
            "$($_.FullName)|$fingerprint"
        })
    $processes = @(Get-TestProcesses | Sort-Object ProcessId | ForEach-Object {
        "PID=$($_.ProcessId)|PATH=$(if ($_.ExecutablePath) { $_.ExecutablePath } else { '<unavailable>' })"
    })
    return [ordered]@{
        RoamingFingerprint = if (Test-Path -LiteralPath $roamingPath) { Get-DirectoryFingerprint -Path $roamingPath } else { '<absent>' }
        LocalFingerprint = if (Test-Path -LiteralPath $localPath) { Get-DirectoryFingerprint -Path $localPath } else { '<absent>' }
        Run = Convert-RegistrySnapshotToCanonicalJson -Snapshot (Get-RegistryValueSnapshot -SubKey $runKeyPath -Name $runValueName)
        Uninstall = Convert-RegistrySnapshotToCanonicalJson -Snapshot (Get-RegistryTreeSnapshot -SubKey $uninstallKeyPath)
        Processes = $processes
        Holds = $holds
    }
}

function Convert-ProtectedProductStateToJson {
    param([Parameter(Mandatory = $true)]$Snapshot)
    return ($Snapshot | ConvertTo-Json -Depth 20 -Compress)
}

function Invoke-SafeFunctionalFailureProbe {
    if ((Test-Path -LiteralPath $testDirPath) -or (Test-Path -LiteralPath $upgradeDirPath)) {
        throw 'Production-finalizer fault-injection probe requires both strict-work test roots to start absent'
    }
    $beforeState = Get-ProtectedProductStateSnapshot
    $beforeStateJson = Convert-ProtectedProductStateToJson -Snapshot $beforeState
    $beforeWorkEntries = @(Get-ChildItem -LiteralPath $workRoot -Force | Sort-Object FullName | Select-Object -ExpandProperty FullName)
    $token = [guid]::NewGuid().ToString('N')
    $probeVerificationId = [guid]::NewGuid().ToString('N')
    $expectedBackup = [System.IO.Path]::GetFullPath((Join-Path $workRoot "release-verify-$probeVerificationId"))
    $siblingVerificationId = [guid]::NewGuid().ToString('N')
    $siblingRoot = [System.IO.Path]::GetFullPath((Join-Path $workRoot "release-verify-$siblingVerificationId"))
    $siblingMarker = Join-Path $siblingRoot '.sdd-owned-sibling-fixture'
    $siblingFingerprint = $null
    $siblingCreated = $false
    $probeSucceeded = $false
    $oldToken = $env:SHIYI_INTERNAL_ROLLBACK_PROBE_TOKEN
    try {
        foreach ($ownedPath in @($expectedBackup, $siblingRoot)) {
            if (Test-Path -LiteralPath $ownedPath) {
                throw "Generated probe recovery identity unexpectedly exists: $ownedPath"
            }
        }
        [void](New-Item -ItemType Directory -Path $siblingRoot)
        $siblingCreated = $true
        [System.IO.File]::WriteAllText($siblingMarker, $token, [System.Text.UTF8Encoding]::new($false))
        $siblingFingerprint = Get-DirectoryFingerprint -Path $siblingRoot

        try {
            $env:SHIYI_INTERNAL_ROLLBACK_PROBE_TOKEN = $token
            $childResult = Invoke-InProcessProductionProbe -Token $token -VerificationId $probeVerificationId -Mode FunctionalFailure
        }
        finally {
            [System.Environment]::SetEnvironmentVariable(
                'SHIYI_INTERNAL_ROLLBACK_PROBE_TOKEN',
                $oldToken,
                [System.EnvironmentVariableTarget]::Process
            )
        }

        $childEvidence = $childResult.Evidence
        if ($null -eq $childResult.Exception) {
            throw 'In-process production-finalizer fault injection did not throw its final aggregate error'
        }
        foreach ($evidence in @(
            [pscustomobject]@{ Label = 'exact recovery identity'; Pattern = [regex]::Escape($expectedBackup) },
            [pscustomobject]@{ Label = 'user data backup'; Pattern = 'USER DATA BACKUP:' },
            [pscustomobject]@{ Label = 'registry backup'; Pattern = 'REGISTRY BACKUP:' },
            [pscustomobject]@{ Label = 'primary injection'; Pattern = 'INJECTED PRIMARY FAILURE AFTER STATE CAPTURE' },
            [pscustomobject]@{ Label = 'complete Job quiescence'; Pattern = 'job-active=0' },
            [pscustomobject]@{ Label = 'safe functional fallback'; Pattern = 'Fallback uninstall functional failure is quiescent; exact rollback will continue' },
            [pscustomobject]@{ Label = 'registry restore'; Pattern = 'REGISTRY RESTORE:' },
            [pscustomobject]@{ Label = 'mutex release'; Pattern = 'RELEASE VERIFY MUTEX RELEASED:' },
            [pscustomobject]@{ Label = 'functional priority error'; Pattern = 'Release verification functional failure after safe rollback:' },
            [pscustomobject]@{ Label = 'preserved primary error'; Pattern = '(?s)primary=.*INJECTED\W+PRIMARY\W+FAILURE\W+AFTER\W+STATE\W+CAPTURE' }
        )) {
            if ($childEvidence -notmatch $evidence.Pattern) {
                throw "In-process production-finalizer output missing $($evidence.Label) evidence. evidence=$childEvidence"
            }
        }
        $markerEvidenceCount = [regex]::Matches($childEvidence, 'STATE ISOLATION: verifier-owned ordinary root').Count
        if ($markerEvidenceCount -ne 2) {
            throw "In-process production-finalizer did not report both verifier-owned marker roots: count=$markerEvidenceCount"
        }
        if ($beforeState.LocalFingerprint -ne '<absent>' -and $childEvidence -notmatch 'USER DATA RESTORE:') {
            throw 'In-process production-finalizer did not report restoring existing Local data'
        }

        $afterState = Get-ProtectedProductStateSnapshot
        $afterStateJson = Convert-ProtectedProductStateToJson -Snapshot $afterState
        if ($afterStateJson -cne $beforeStateJson) {
            throw "Production-finalizer probe changed protected state. before=$beforeStateJson after=$afterStateJson"
        }
        if ((Test-Path -LiteralPath $testDirPath) -or (Test-Path -LiteralPath $upgradeDirPath)) {
            throw 'Production-finalizer probe left a test install root after quiescent functional failure'
        }

        if (-not (Test-Path -LiteralPath $expectedBackup -PathType Container)) {
            throw "Expected exact retained production recovery backup is absent: $expectedBackup"
        }
        [void](Assert-SafeRecursiveTarget -Path $expectedBackup -AllowedRoots @($workRoot) -Purpose 'exact production-finalizer retained backup validation')
        $retainedRegistryPath = Join-Path $expectedBackup 'registry-state.clixml'
        if (-not (Test-Path -LiteralPath $retainedRegistryPath -PathType Leaf)) {
            throw "Retained production recovery backup lacks CLIXML: $retainedRegistryPath"
        }
        $retainedRegistry = Import-Clixml -LiteralPath $retainedRegistryPath
        Assert-RegistrySnapshotEqual -Expected $retainedRegistry.Run -Actual (Get-RegistryValueSnapshot -SubKey $runKeyPath -Name $runValueName) -Description 'retained/live Run registry'
        Assert-RegistrySnapshotEqual -Expected $retainedRegistry.Uninstall -Actual (Get-RegistryTreeSnapshot -SubKey $uninstallKeyPath) -Description 'retained/live uninstall registry'

        foreach ($dataEvidence in @(
            [pscustomobject]@{ Name = 'roaming'; LivePath = $roamingPath; BackupPath = Join-Path $expectedBackup 'original-data\roaming'; Expected = $beforeState.RoamingFingerprint },
            [pscustomobject]@{ Name = 'local'; LivePath = $localPath; BackupPath = Join-Path $expectedBackup 'original-data\local'; Expected = $beforeState.LocalFingerprint }
        )) {
            if ($dataEvidence.Expected -eq '<absent>') {
                if (Test-Path -LiteralPath $dataEvidence.BackupPath) {
                    throw "Unexpected retained backup for originally absent $($dataEvidence.Name) data"
                }
                continue
            }
            if (-not (Test-Path -LiteralPath $dataEvidence.BackupPath -PathType Container)) {
                throw "Missing retained backup for $($dataEvidence.Name) data: $($dataEvidence.BackupPath)"
            }
            $backupFingerprint = Get-DirectoryFingerprint -Path $dataEvidence.BackupPath
            $liveFingerprint = Get-DirectoryFingerprint -Path $dataEvidence.LivePath
            if ($backupFingerprint -ne $dataEvidence.Expected -or $liveFingerprint -ne $dataEvidence.Expected) {
                throw "Retained/live $($dataEvidence.Name) fingerprints differ: expected=$($dataEvidence.Expected), backup=$backupFingerprint, live=$liveFingerprint"
            }
        }

        if (-not (Test-Path -LiteralPath $siblingMarker -PathType Leaf) -or [System.IO.File]::ReadAllText($siblingMarker) -cne $token) {
            throw 'Unrelated release-verify sibling ownership marker changed while validating exact probe identity'
        }
        if ((Get-DirectoryFingerprint -Path $siblingRoot) -cne $siblingFingerprint) {
            throw 'Unrelated release-verify sibling changed while validating exact probe identity'
        }

        Remove-SafeTree -Path $expectedBackup -AllowedRoots @($workRoot) -Purpose 'validated exact production-finalizer recovery cleanup'
        if (-not (Test-Path -LiteralPath $siblingRoot -PathType Container) -or (Get-DirectoryFingerprint -Path $siblingRoot) -cne $siblingFingerprint) {
            throw 'Exact recovery cleanup removed or changed the unrelated release-verify sibling fixture'
        }
        $probeSucceeded = $true
    }
    finally {
        [System.Environment]::SetEnvironmentVariable(
            'SHIYI_INTERNAL_ROLLBACK_PROBE_TOKEN',
            $oldToken,
            [System.EnvironmentVariableTarget]::Process
        )
        if ($siblingCreated -and (Test-Path -LiteralPath $siblingRoot)) {
            $siblingOwned = $false
            try {
                $siblingOwned =
                    (Test-Path -LiteralPath $siblingMarker -PathType Leaf) -and
                    ([System.IO.File]::ReadAllText($siblingMarker) -ceq $token) -and
                    ((Get-DirectoryFingerprint -Path $siblingRoot) -ceq $siblingFingerprint)
            }
            catch {
                Write-Warning "Sibling fixture ownership check failed; fixture retained: $(Format-ExceptionDetails -Exception $_.Exception)"
            }
            if ($siblingOwned) {
                Remove-SafeTree -Path $siblingRoot -AllowedRoots @($workRoot) -Purpose 'owned unrelated recovery sibling fixture cleanup'
            }
            else {
                Write-Warning "Sibling fixture retained because exact ownership/fingerprint could not be proven: $siblingRoot"
            }
        }
    }

    if (-not $probeSucceeded) {
        throw 'Production-finalizer fault injection did not complete its exact-identity assertions'
    }
    $afterWorkEntries = @(Get-ChildItem -LiteralPath $workRoot -Force | Sort-Object FullName | Select-Object -ExpandProperty FullName)
    if (($afterWorkEntries | ConvertTo-Json -Compress) -cne ($beforeWorkEntries | ConvertTo-Json -Compress)) {
        throw "Production-finalizer probe did not restore work inventory. before=$($beforeWorkEntries -join ', ') after=$($afterWorkEntries -join ', ')"
    }
    Write-Output "PRODUCTION FINALIZER FAILURE PROBE PASSED: same-process=true; inner-final-aggregate-caught=true; exact-verification-id=$probeVerificationId; primary-preserved=true; functional-nonzero=true; job-active=0; strict-cleanup=true; registry-structural-restore=true; data-fingerprint-restore=true; exact-backup-validated-and-removed=true; sibling-preserved-then-owned-cleanup=true"
}

function Invoke-MutexContentionProbe {
    $beforeState = Convert-ProtectedProductStateToJson -Snapshot (Get-ProtectedProductStateSnapshot)
    $beforeWorkEntries = @(Get-ChildItem -LiteralPath $workRoot -Force | Sort-Object FullName | Select-Object -ExpandProperty FullName)
    $token = [guid]::NewGuid().ToString('N')
    $holderToken = [guid]::NewGuid().ToString('N')
    $fixtureToken = [guid]::NewGuid().ToString('N')
    $probeVerificationId = [guid]::NewGuid().ToString('N')
    $holderVerificationId = [guid]::NewGuid().ToString('N')
    $expectedBackup = [System.IO.Path]::GetFullPath((Join-Path $workRoot "release-verify-$probeVerificationId"))
    $holderBackup = [System.IO.Path]::GetFullPath((Join-Path $workRoot "release-verify-$holderVerificationId"))
    $probeRoot = [System.IO.Path]::GetFullPath((Join-Path $workRoot "global-mutex-probe-$fixtureToken"))
    $ownershipMarker = Join-Path $probeRoot '.sdd-global-mutex-probe-owner'
    $readyPath = Join-Path $probeRoot 'holder.ready'
    $releasePath = Join-Path $probeRoot 'holder.release'
    $oldToken = $env:SHIYI_INTERNAL_ROLLBACK_PROBE_TOKEN
    $holder = $null
    $holderExited = $false
    $probeRootCreated = $false
    try {
        foreach ($path in @($expectedBackup, $holderBackup, $probeRoot)) {
            if (Test-Path -LiteralPath $path) {
                throw "Generated cross-process mutex probe identity unexpectedly exists: $path"
            }
        }
        [void](New-Item -ItemType Directory -Path $probeRoot)
        $probeRootCreated = $true
        [System.IO.File]::WriteAllText($ownershipMarker, $fixtureToken, [System.Text.UTF8Encoding]::new($false))

        $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
        $startInfo.FileName = (Get-Process -Id $PID).Path
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        foreach ($argument in @(
            '-NoProfile',
            '-NonInteractive',
            '-File',
            $PSCommandPath,
            '-Installer',
            $installerPath,
            '-TestDir',
            $testDirPath,
            '-UninstallTimeoutSeconds',
            $UninstallTimeoutSeconds.ToString(),
            '-InternalMutexHolderProbe',
            '-InternalProbeToken',
            $holderToken,
            '-InternalVerificationId',
            $holderVerificationId,
            '-InternalMutexReadyPath',
            $readyPath,
            '-InternalMutexReleasePath',
            $releasePath
        )) {
            $startInfo.ArgumentList.Add($argument)
        }
        $startInfo.Environment['SHIYI_INTERNAL_ROLLBACK_PROBE_TOKEN'] = $holderToken
        $holder = [System.Diagnostics.Process]::new()
        $holder.StartInfo = $startInfo
        if (-not $holder.Start()) {
            throw 'Could not start independent pwsh Global mutex holder'
        }

        $readyDeadline = [System.Diagnostics.Stopwatch]::StartNew()
        while (-not (Test-Path -LiteralPath $readyPath -PathType Leaf)) {
            if ($holder.HasExited) {
                $holder.WaitForExit()
                $holderExited = $true
                throw "Independent pwsh mutex holder exited before readiness: exit=$($holder.ExitCode); stdout=$($holder.StandardOutput.ReadToEnd()); stderr=$($holder.StandardError.ReadToEnd())"
            }
            if ($readyDeadline.Elapsed.TotalSeconds -ge 10) {
                throw 'Independent pwsh mutex holder did not signal readiness within ten seconds'
            }
            Start-Sleep -Milliseconds 100
        }
        $readyEvidence = [System.IO.File]::ReadAllText($readyPath)
        foreach ($expectedEvidence in @(
            "PID=$($holder.Id)",
            "NAME=$releaseVerificationMutexName",
            "SID=$currentUserSidValue",
            'ACL=protected-current-user-and-system-only'
        )) {
            if (-not $readyEvidence.Contains($expectedEvidence)) {
                throw "Independent holder readiness lacks '$expectedEvidence': $readyEvidence"
            }
        }

        try {
            $env:SHIYI_INTERNAL_ROLLBACK_PROBE_TOKEN = $token
            $contentionResult = Invoke-InProcessProductionProbe -Token $token -VerificationId $probeVerificationId -Mode MutexContention
        }
        finally {
            [System.Environment]::SetEnvironmentVariable(
                'SHIYI_INTERNAL_ROLLBACK_PROBE_TOKEN',
                $oldToken,
                [System.EnvironmentVariableTarget]::Process
            )
        }
        if ($null -eq $contentionResult.Exception -or $contentionResult.ExceptionDetails -notmatch 'Another Shiyi release verification is already active') {
            throw "Second production verification did not fail on mutex contention before mutation: $($contentionResult.Evidence)"
        }
        if (
            $contentionResult.Evidence -notmatch [regex]::Escape($releaseVerificationMutexName) -or
            $contentionResult.Evidence -notmatch 'broad-principal=false'
        ) {
            throw "Second production entry did not report the actual Global SID mutex and verified DACL: $($contentionResult.Evidence)"
        }
        if ($contentionResult.Evidence -match 'USER DATA BACKUP:|REGISTRY BACKUP:|STATE ISOLATION:|INTERNAL MUTEX CONTENTION ATTEMPT ACQUIRED') {
            throw "Mutex contention reached a state-mutation marker: $($contentionResult.Evidence)"
        }
        foreach ($path in @($expectedBackup, $holderBackup)) {
            if (Test-Path -LiteralPath $path) {
                throw "Mutex probe created a forbidden recovery root before mutation: $path"
            }
        }
        if ((Convert-ProtectedProductStateToJson -Snapshot (Get-ProtectedProductStateSnapshot)) -cne $beforeState) {
            throw 'Mutex contention probe changed protected product state'
        }
        if ((Test-Path -LiteralPath $testDirPath) -or (Test-Path -LiteralPath $upgradeDirPath)) {
            throw 'Mutex contention probe created a test install root'
        }
        $duringWorkEntries = @(Get-ChildItem -LiteralPath $workRoot -Force | Sort-Object FullName | Select-Object -ExpandProperty FullName)
        $expectedDuringWorkEntries = @(($beforeWorkEntries + $probeRoot) | Sort-Object)
        if (($duringWorkEntries | ConvertTo-Json -Compress) -cne ($expectedDuringWorkEntries | ConvertTo-Json -Compress)) {
            throw "Mutex contention probe created unexpected work entries: $($duringWorkEntries -join ', ')"
        }
        [System.IO.File]::WriteAllText($releasePath, $fixtureToken, [System.Text.UTF8Encoding]::new($false))
        if (-not $holder.WaitForExit(10000)) {
            throw 'Independent pwsh mutex holder did not exit within ten seconds after release'
        }
        $holderExited = $true
        $holderOutput = $holder.StandardOutput.ReadToEnd()
        $holderError = $holder.StandardError.ReadToEnd()
        if ($holder.ExitCode -ne 0) {
            throw "Independent pwsh mutex holder failed: exit=$($holder.ExitCode); stdout=$holderOutput; stderr=$holderError"
        }
        foreach ($holderEvidence in @(
            $releaseVerificationMutexName,
            'broad-principal=false',
            'INTERNAL CROSS-PROCESS MUTEX HOLDER RELEASE SIGNAL OBSERVED',
            'RELEASE VERIFY MUTEX RELEASED:'
        )) {
            if (-not $holderOutput.Contains($holderEvidence)) {
                throw "Independent holder output lacks '$holderEvidence': stdout=$holderOutput stderr=$holderError"
            }
        }

        $reacquiredMutex = Enter-ReleaseVerificationMutex
        Exit-ReleaseVerificationMutex -Mutex $reacquiredMutex

        if (
            -not (Test-Path -LiteralPath $ownershipMarker -PathType Leaf) -or
            [System.IO.File]::ReadAllText($ownershipMarker) -cne $fixtureToken
        ) {
            throw 'Cross-process mutex probe ownership marker changed'
        }
        Remove-SafeTree -Path $probeRoot -AllowedRoots @($workRoot) -Purpose 'owned cross-process Global mutex probe cleanup'
        $probeRootCreated = $false

        $afterState = Convert-ProtectedProductStateToJson -Snapshot (Get-ProtectedProductStateSnapshot)
        if ($afterState -cne $beforeState) {
            throw 'Cross-process mutex probe changed protected product state after holder release'
        }
        $afterWorkEntries = @(Get-ChildItem -LiteralPath $workRoot -Force | Sort-Object FullName | Select-Object -ExpandProperty FullName)
        if (($afterWorkEntries | ConvertTo-Json -Compress) -cne ($beforeWorkEntries | ConvertTo-Json -Compress)) {
            throw 'Cross-process mutex probe did not restore work inventory'
        }
        Write-Output "MUTEX CONTENTION PROBE PASSED: cross-process-pwsh=true; global-current-user-mutex=$releaseVerificationMutexName; acl-protected=true; acl-current-user-full-control=true; acl-system-only-additional=true; broad-principal=false; second-verification-rejected-before-mutation=true; exact-backup-absent=true; product-state-mutated=false; reacquire-after-release=true"
    }
    finally {
        [System.Environment]::SetEnvironmentVariable(
            'SHIYI_INTERNAL_ROLLBACK_PROBE_TOKEN',
            $oldToken,
            [System.EnvironmentVariableTarget]::Process
        )
        if ($null -ne $holder) {
            try {
                if (-not $holder.HasExited) {
                    $probeOwned =
                        $probeRootCreated -and
                        (Test-Path -LiteralPath $ownershipMarker -PathType Leaf) -and
                        ([System.IO.File]::ReadAllText($ownershipMarker) -ceq $fixtureToken)
                    if ($probeOwned) {
                        [System.IO.File]::WriteAllText($releasePath, $fixtureToken, [System.Text.UTF8Encoding]::new($false))
                        [void]$holder.WaitForExit(10000)
                    }
                    if (-not $holder.HasExited) {
                        $holder.Kill($true)
                        [void]$holder.WaitForExit(10000)
                    }
                }
                $holderExited = $holder.HasExited
            }
            catch {
                Write-Warning "Cross-process mutex holder cleanup failed: $(Format-ExceptionDetails -Exception $_.Exception)"
            }
            finally {
                $holder.Dispose()
            }
        }
        if ($probeRootCreated -and (Test-Path -LiteralPath $probeRoot) -and $holderExited) {
            try {
                if (
                    (Test-Path -LiteralPath $ownershipMarker -PathType Leaf) -and
                    [System.IO.File]::ReadAllText($ownershipMarker) -ceq $fixtureToken
                ) {
                    Remove-SafeTree -Path $probeRoot -AllowedRoots @($workRoot) -Purpose 'failed owned cross-process Global mutex probe cleanup'
                }
                else {
                    Write-Warning "Cross-process mutex probe fixture retained because ownership changed: $probeRoot"
                }
            }
            catch {
                Write-Warning "Cross-process mutex probe fixture cleanup failed: $(Format-ExceptionDetails -Exception $_.Exception)"
            }
        }
    }
}

if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    throw "Installer is not a file: $installerPath"
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Missing verification interpreter: $python"
}
if (-not (Test-Path -LiteralPath $workRoot)) {
    [void](Assert-NoReparseComponents -Path $repoRoot -Purpose 'repository preflight')
    [void](New-Item -ItemType Directory -Path $workRoot)
}
if (-not (Test-Path -LiteralPath $workRoot -PathType Container)) {
    throw "Verifier work root is not a directory: $workRoot"
}
[void](Assert-NoReparseComponents -Path $workRoot -Purpose 'verifier work-root preflight')

$recordedInstallLocations = @(Get-RecordedInstallLocations)
$protectedPaths = @(
    $installerPath,
    $env:USERPROFILE,
    $env:APPDATA,
    $env:LOCALAPPDATA,
    $roamingPath,
    $localPath,
    (Join-Path $env:LOCALAPPDATA 'Programs\ShiyiDesktopPet'),
    (Join-Path $repoRoot '.git'),
    (Join-Path $repoRoot '.superpowers'),
    (Join-Path $repoRoot 'approved-input'),
    (Join-Path $repoRoot 'artifacts'),
    (Join-Path $repoRoot 'build'),
    (Join-Path $repoRoot 'dist'),
    (Join-Path $repoRoot 'packaging'),
    (Join-Path $repoRoot 'scripts'),
    (Join-Path $repoRoot 'src'),
    (Join-Path $repoRoot 'tests')
) + $recordedInstallLocations
Assert-TestRoot -Path $testDirPath -ProtectedPaths $protectedPaths
Assert-TestRoot -Path $upgradeDirPath -ProtectedPaths $protectedPaths
if (Test-PathsOverlap -First $testDirPath -Second $upgradeDirPath) {
    throw "Ordinary and upgrade test roots overlap: $testDirPath <-> $upgradeDirPath"
}

foreach ($dataPath in @($roamingPath, $localPath)) {
    if (Test-Path -LiteralPath $dataPath) {
        [void](Get-NoFollowTreeItems -Path $dataPath)
    }
}

$existingProcesses = @(Get-TestProcesses)
if (($ProcessContainmentProbe -or $FallbackForeignProcessProbe -or $SafeFunctionalFailureProbe -or $MutexContentionProbe) -and -not $PreflightOnly) {
    throw 'Process safety probes are permitted only with -PreflightOnly'
}
if ($SimulateUnresolvedShiyiProcess) {
    if (-not $PreflightOnly) {
        throw '-SimulateUnresolvedShiyiProcess is permitted only with -PreflightOnly'
    }
    $existingProcesses += [pscustomobject]@{ ProcessId = 0; ExecutablePath = $null }
}
if ($existingProcesses.Count -ne 0) {
    $details = @($existingProcesses | ForEach-Object {
        "PID=$($_.ProcessId), path=$(if ($_.ExecutablePath) { $_.ExecutablePath } else { '<unavailable>' })"
    }) -join '; '
    throw "Refusing release verification while any ShiyiDesktopPet process exists: $details"
}

Write-Output "PREFLIGHT PASSED: test roots are canonical strict work children; protected/reparse/process checks passed"
if ($ProcessContainmentProbe) {
    Invoke-ProcessContainmentProbe
}
if ($FallbackForeignProcessProbe) {
    Invoke-FallbackForeignProcessProbe
}
if ($SafeFunctionalFailureProbe) {
    Invoke-SafeFunctionalFailureProbe
}
if ($MutexContentionProbe) {
    Invoke-MutexContentionProbe
}
if ($PreflightOnly) {
    return
}

$releaseVerificationMutex = $null
$productionCompletionError = $null
$mutexReleaseError = $null
try {
$releaseVerificationMutex = Enter-ReleaseVerificationMutex
if ($InternalMutexHolderProbe) {
    $readyPath = [System.IO.Path]::GetFullPath($InternalMutexReadyPath)
    $releasePath = [System.IO.Path]::GetFullPath($InternalMutexReleasePath)
    $readyParent = [System.IO.Path]::GetFullPath((Split-Path -Parent $readyPath))
    $releaseParent = [System.IO.Path]::GetFullPath((Split-Path -Parent $releasePath))
    if (
        -not (Test-DescendantPath -Path $readyPath -Root $workRoot) -or
        -not (Test-DescendantPath -Path $releasePath -Root $workRoot) -or
        -not [string]::Equals($readyParent, $releaseParent, [System.StringComparison]::OrdinalIgnoreCase)
    ) {
        throw 'Internal mutex holder coordination paths must be sibling files under strict work'
    }
    [void](Assert-NoReparseComponents -Path $readyParent -Purpose 'mutex holder coordination root')
    if ((Test-Path -LiteralPath $readyPath) -or (Test-Path -LiteralPath $releasePath)) {
        throw 'Internal mutex holder coordination files must start absent'
    }
    [System.IO.File]::WriteAllText(
        $readyPath,
        "PID=$PID; NAME=$releaseVerificationMutexName; SID=$currentUserSidValue; ACL=protected-current-user-and-system-only",
        [System.Text.UTF8Encoding]::new($false)
    )
    $holderDeadline = [System.Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path -LiteralPath $releasePath -PathType Leaf)) {
        if ($holderDeadline.Elapsed.TotalSeconds -ge 30) {
            throw 'Internal cross-process mutex holder timed out waiting for release signal'
        }
        Start-Sleep -Milliseconds 100
    }
    Write-Output 'INTERNAL CROSS-PROCESS MUTEX HOLDER RELEASE SIGNAL OBSERVED: no product state was mutated'
    return
}
if ($InternalMutexContentionAttempt) {
    Write-Output 'INTERNAL MUTEX CONTENTION ATTEMPT ACQUIRED: no product state was mutated'
    return
}
if (Test-Path -LiteralPath $backupRoot) {
    throw "Verification recovery identity already exists before state mutation: $backupRoot"
}
[void](New-Item -ItemType Directory -Path $backupRoot)
$dataStates = @(
    [pscustomobject]@{
        Name = 'roaming'
        RealPath = $roamingPath
        HoldPath = "$roamingPath.sdd-hold-$verificationId"
        BackupPath = Join-Path $backupRoot 'original-data\roaming'
        Target = $roamingPath
        OwnershipMarker = Join-Path $roamingPath ".sdd-verifier-owned-$verificationId"
        Existed = $false
        Fingerprint = $null
    },
    [pscustomobject]@{
        Name = 'local'
        RealPath = $localPath
        HoldPath = "$localPath.sdd-hold-$verificationId"
        BackupPath = Join-Path $backupRoot 'original-data\local'
        Target = $localPath
        OwnershipMarker = Join-Path $localPath ".sdd-verifier-owned-$verificationId"
        Existed = $false
        Fingerprint = $null
    }
)
$roamingState = $dataStates | Where-Object Name -eq 'roaming'
$localState = $dataStates | Where-Object Name -eq 'local'
$registryState = $null
$stateCaptured = $false
$verificationSucceeded = $false
$primaryVerificationError = $null
$restoreErrors = [System.Collections.Generic.List[string]]::new()
$functionalErrors = [System.Collections.Generic.List[string]]::new()

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

    Ensure-IsolatedDataRoots -States $dataStates
    foreach ($directory in @($testDirPath, $upgradeDirPath)) {
        Remove-SafeTree -Path $directory -AllowedRoots @($workRoot) -Purpose 'pre-test cleanup'
    }

    if ($InjectSafeFunctionalFailureAfterStateCapture) {
        [void](New-Item -ItemType Directory -Path $testDirPath)
        Copy-Item -LiteralPath (Join-Path $env:SystemRoot 'System32\ping.exe') -Destination (Join-Path $testDirPath 'unins000.exe')
        Write-Output 'INJECTED PRIMARY FAILURE AFTER STATE CAPTURE: dummy nonzero uninstaller created in strict work test root'
        throw 'INJECTED PRIMARY FAILURE AFTER STATE CAPTURE'
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
    $ordinaryTargetSettings = Join-Path $roamingState.Target 'settings.ini'
    $ordinaryTargetLog = Join-Path $localState.Target 'logs\verification.log'
    $ordinarySettingsText = "[verification]`nid=$verificationId`n"
    $ordinaryLogText = "verification=$verificationId`n"
    [void](New-Item -ItemType Directory -Path (Split-Path -Parent $ordinarySettings) -Force)
    [void](New-Item -ItemType Directory -Path (Split-Path -Parent $ordinaryLog) -Force)
    [System.IO.File]::WriteAllText($ordinarySettings, $ordinarySettingsText, [System.Text.UTF8Encoding]::new($false))
    [System.IO.File]::WriteAllText($ordinaryLog, $ordinaryLogText, [System.Text.UTF8Encoding]::new($false))
    Assert-DirectSentinel -Path $ordinaryTargetSettings -ExpectedText $ordinarySettingsText
    Assert-DirectSentinel -Path $ordinaryTargetLog -ExpectedText $ordinaryLogText

    $ordinaryExpectedRun = '"' + (Join-Path $testDirPath 'ShiyiDesktopPet.exe') + '" --startup'
    Set-StartupViaManager -Directory $testDirPath -Enabled $true
    Assert-RegistryValueExact -Expected $ordinaryExpectedRun

    Invoke-Uninstall -Directory $testDirPath
    Assert-NoTestProcesses
    Assert-RegistryValueAbsent
    Assert-UninstallEntry -Expected $false
    if (Test-Path -LiteralPath $testDirPath) {
        throw "Ordinary uninstall left test install directory: $testDirPath"
    }
    if (
        (Test-Path -LiteralPath $ordinarySettings) -or
        (Test-Path -LiteralPath $ordinaryLog) -or
        (Test-Path -LiteralPath $ordinaryTargetSettings) -or
        (Test-Path -LiteralPath $ordinaryTargetLog) -or
        (Test-Path -LiteralPath (Split-Path -Parent $ordinaryTargetLog))
    ) {
        throw 'Ordinary uninstall left direct verifier-owned settings/logs'
    }
    foreach ($state in $dataStates) {
        if (Test-Path -LiteralPath $state.RealPath) {
            throw "Ordinary uninstall left product data path: $($state.RealPath)"
        }
    }
    Assert-IsolatedTargetsClean -States $dataStates -Phase 'ordinary uninstall'
    Write-Output 'ORDINARY VERIFY: install=0 self-test=0 startup-initially-absent=true startup-enabled-before-uninstall=true uninstall-removed-run=true direct-target-cleanup=true'

    Write-Output '--- upgrade preservation ---'
    Ensure-IsolatedDataRoots -States $dataStates
    Invoke-Install -Directory $upgradeDirPath -Startup enable
    Assert-InstalledLayout -Directory $upgradeDirPath
    Assert-UninstallEntry -Expected $true
    $expectedRun = '"' + (Join-Path $upgradeDirPath 'ShiyiDesktopPet.exe') + '" --startup'
    Assert-RegistryValueExact -Expected $expectedRun

    $settingsPath = Join-Path $roamingPath 'settings.ini'
    $targetSettingsPath = Join-Path $roamingState.Target 'settings.ini'
    $upgradeLogPath = Join-Path $localPath 'logs\upgrade-verification.log'
    $targetUpgradeLogPath = Join-Path $localState.Target 'logs\upgrade-verification.log'
    $settingsText = "[settings]`nschema_version = 1`nwander_enabled = true`nverification_sentinel = $verificationId`n"
    $upgradeLogText = "upgrade-verification=$verificationId`n"
    [System.IO.File]::WriteAllText($settingsPath, $settingsText, [System.Text.UTF8Encoding]::new($false))
    [void](New-Item -ItemType Directory -Path (Split-Path -Parent $upgradeLogPath) -Force)
    [System.IO.File]::WriteAllText($upgradeLogPath, $upgradeLogText, [System.Text.UTF8Encoding]::new($false))
    Assert-DirectSentinel -Path $targetSettingsPath -ExpectedText $settingsText
    Assert-DirectSentinel -Path $targetUpgradeLogPath -ExpectedText $upgradeLogText
    $settingsHash = (Get-FileHash -LiteralPath $targetSettingsPath -Algorithm SHA256).Hash

    Set-StartupViaManager -Directory $upgradeDirPath -Enabled $false
    Assert-RegistryValueAbsent

    Invoke-Install -Directory $upgradeDirPath -Startup enable
    Assert-InstalledLayout -Directory $upgradeDirPath
    Assert-UninstallEntry -Expected $true
    Assert-RegistryValueAbsent
    if (-not (Test-Path -LiteralPath $targetSettingsPath -PathType Leaf)) {
        throw 'Upgrade removed the settings sentinel'
    }
    if ((Get-FileHash -LiteralPath $targetSettingsPath -Algorithm SHA256).Hash -ne $settingsHash) {
        throw 'Upgrade changed the settings sentinel'
    }
    if ((Get-Content -LiteralPath $targetSettingsPath -Raw) -notmatch '(?m)^wander_enabled\s*=\s*true\s*$') {
        throw 'Upgrade did not preserve wander_enabled=true'
    }
    Assert-DirectSentinel -Path $targetUpgradeLogPath -ExpectedText $upgradeLogText
    Write-Output "UPGRADE VERIFY: settings-preserved=true ($settingsHash), startup-disabled-preserved=true"

    Invoke-Uninstall -Directory $upgradeDirPath
    Assert-NoTestProcesses
    Assert-RegistryValueAbsent
    Assert-UninstallEntry -Expected $false
    if (Test-Path -LiteralPath $upgradeDirPath) {
        throw "Upgrade uninstall left test install directory: $upgradeDirPath"
    }
    if (
        (Test-Path -LiteralPath $targetSettingsPath) -or
        (Test-Path -LiteralPath $targetUpgradeLogPath) -or
        (Test-Path -LiteralPath (Split-Path -Parent $targetUpgradeLogPath))
    ) {
        throw 'Upgrade uninstall left direct isolated settings/logs'
    }
    foreach ($state in $dataStates) {
        if (Test-Path -LiteralPath $state.RealPath) {
            throw "Upgrade uninstall left product data path: $($state.RealPath)"
        }
    }
    Assert-IsolatedTargetsClean -States $dataStates -Phase 'upgrade uninstall'
    Write-Output 'UPGRADE UNINSTALL VERIFY: process/run/uninstall/install/settings/log cleanup=true'
    $verificationSucceeded = $true
}
catch {
    $primaryVerificationError = $_.Exception
}
finally {
    try {
    $rollbackAllowed = Test-RollbackSafetyKnown
    if (-not $rollbackAllowed) {
        $restoreErrors.Add("rollback prohibited: process/job safety is unknown ($($rollbackSafetyReasons -join '; '))")
    }

    if ($rollbackAllowed) {
        foreach ($directory in @($testDirPath, $upgradeDirPath)) {
            try {
                Invoke-Uninstall -Directory $directory
                if (-not $allJobTreesQuiescent) {
                    throw 'fallback uninstall did not prove its complete job tree quiescent'
                }
            }
            catch {
                $functionalDetail = Format-ExceptionDetails -Exception $_.Exception
                $functionalErrors.Add("fallback uninstall blocked/failed (${directory}): $functionalDetail")
                if (-not (Test-RollbackSafetyKnown)) {
                    $rollbackAllowed = $false
                    break
                }
                Write-Warning "Fallback uninstall functional failure is quiescent; exact rollback will continue: $functionalDetail"
            }
        }
    }

    if ($rollbackAllowed) {
        try {
            Assert-UninstallOwnershipGate -Context 'pre-rollback global check'
        }
        catch {
            $restoreErrors.Add("rollback process-ownership gate: $(Format-ExceptionDetails -Exception $_.Exception)")
            $rollbackAllowed = $false
        }
    }

    if (-not (Test-RollbackSafetyKnown)) {
        $restoreErrors.Add("rollback prohibited after fallback: process/job safety is unknown ($($rollbackSafetyReasons -join '; '))")
        $rollbackAllowed = $false
    }

    if ($rollbackAllowed) {
        foreach ($directory in @($testDirPath, $upgradeDirPath)) {
            try {
                Remove-SafeTree -Path $directory -AllowedRoots @($workRoot) -Purpose 'final test cleanup'
            }
            catch {
                $restoreErrors.Add("cleanup ${directory}: $(Format-ExceptionDetails -Exception $_.Exception)")
            }
        }
    }

    if ($rollbackAllowed -and $stateCaptured) {
        try {
            Restore-RegistryValue -SubKey $runKeyPath -Name $runValueName -Snapshot $registryState.Run
        }
        catch {
            $restoreErrors.Add("Run registry restore: $(Format-ExceptionDetails -Exception $_.Exception)")
        }
        try {
            Restore-RegistryTree -SubKey $uninstallKeyPath -Snapshot $registryState.Uninstall
        }
        catch {
            $restoreErrors.Add("uninstall registry restore: $(Format-ExceptionDetails -Exception $_.Exception)")
        }
        try {
            $actualRun = Get-RegistryValueSnapshot -SubKey $runKeyPath -Name $runValueName
            Assert-RegistrySnapshotEqual -Expected $registryState.Run -Actual $actualRun -Description 'Run registry'
        }
        catch {
            $restoreErrors.Add("Run registry post-restore verification: $(Format-ExceptionDetails -Exception $_.Exception)")
        }
        try {
            $actualUninstall = Get-RegistryTreeSnapshot -SubKey $uninstallKeyPath
            Assert-RegistrySnapshotEqual -Expected $registryState.Uninstall -Actual $actualUninstall -Description 'uninstall registry tree'
        }
        catch {
            $restoreErrors.Add("uninstall registry post-restore verification: $(Format-ExceptionDetails -Exception $_.Exception)")
        }
        Write-Output "REGISTRY RESTORE: Run=$($registryState.Run.Exists), Uninstall=$($registryState.Uninstall.Exists)"
    }

    if ($rollbackAllowed) {
        foreach ($state in $dataStates) {
            try {
                Remove-VerifierDataRoots -States @($state)
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
                $restoreErrors.Add("user data restore ($($state.Name)): $(Format-ExceptionDetails -Exception $_.Exception)")
            }
        }
    }
    else {
        Write-Warning 'ROLLBACK REFUSED: test roots, verifier data roots, registry test state, holds, backup, and CLIXML are retained because process ownership/job quiescence was not proven.'
    }

    if ($rollbackAllowed -and $restoreErrors.Count -eq 0 -and $functionalErrors.Count -eq 0 -and $verificationSucceeded) {
        try {
            Remove-SafeTree -Path $backupRoot -AllowedRoots @($workRoot) -Purpose 'verified backup cleanup'
        }
        catch {
            $restoreErrors.Add("backup cleanup: $(Format-ExceptionDetails -Exception $_.Exception)")
        }
    }

    if ($restoreErrors.Count -ne 0 -or $functionalErrors.Count -ne 0 -or -not $verificationSucceeded) {
        Write-Warning "Backup retained for recovery: $backupRoot"
        foreach ($state in $dataStates) {
            $holdExists = Test-Path -LiteralPath $state.HoldPath
            $holdFingerprint = '<unavailable>'
            if ($holdExists) {
                try {
                    $holdFingerprint = Get-DirectoryFingerprint -Path $state.HoldPath
                }
                catch {
                    $holdFingerprint = "ERROR: $($_.Exception.Message)"
                }
            }
            Write-Warning "RECOVERY HOLD [$($state.Name)]: path=$($state.HoldPath), exists=$holdExists, fingerprint=$holdFingerprint"
            $backupExists = Test-Path -LiteralPath $state.BackupPath
            $backupFingerprint = '<unavailable>'
            if ($backupExists) {
                try {
                    $backupFingerprint = Get-DirectoryFingerprint -Path $state.BackupPath
                }
                catch {
                    $backupFingerprint = "ERROR: $($_.Exception.Message)"
                }
            }
            Write-Warning "RECOVERY BACKUP [$($state.Name)]: path=$($state.BackupPath), exists=$backupExists, fingerprint=$backupFingerprint"
        }
        Write-Warning "RECOVERY REGISTRY SNAPSHOT: $registryBackupPath (exists=$(Test-Path -LiteralPath $registryBackupPath))"
        Write-Warning "NON-DESTRUCTIVE RECOVERY OUTLINE: inspect listed hold/backup paths with Get-ChildItem -LiteralPath '<Path>' -Force; copy one to a new recovery directory with Copy-Item -LiteralPath '<Path>' -Destination '<NewPath>' -Recurse; inspect Import-Clixml -LiteralPath '$registryBackupPath'. Do not delete or overwrite current user data until contents are compared."
    }
    }
    catch {
        $restoreErrors.Add("unexpected finalization failure: $(Format-ExceptionDetails -Exception $_.Exception)")
    }
}

$primaryDetails = Format-ExceptionDetails -Exception $primaryVerificationError
if ($restoreErrors.Count -ne 0) {
    throw "Release verification restore failed: restore=$($restoreErrors -join ' | '); functional=$($functionalErrors -join ' | '); primary=$primaryDetails"
}
if ($functionalErrors.Count -ne 0) {
    throw "Release verification functional failure after safe rollback: functional=$($functionalErrors -join ' | '); primary=$primaryDetails"
}
if ($null -ne $primaryVerificationError) {
    throw "Release verification failed after exact rollback: primary=$primaryDetails"
}
if (-not $verificationSucceeded) {
    throw 'Release verification did not complete without a captured primary error'
}
Write-Output 'RELEASE VERIFY PASSED: ordinary install/self-test/uninstall and upgrade preservation'
}
catch {
    $productionCompletionError = $_.Exception
}
finally {
    if ($null -ne $releaseVerificationMutex) {
        try {
            Exit-ReleaseVerificationMutex -Mutex $releaseVerificationMutex
        }
        catch {
            if ($InternalMutexContentionAttempt -or $InternalMutexHolderProbe) {
                throw
            }
            $mutexReleaseError = $_.Exception
        }
    }
}
if ($null -ne $mutexReleaseError) {
    throw "Release verification mutex release failed: mutex=$(Format-ExceptionDetails -Exception $mutexReleaseError); production=$(Format-ExceptionDetails -Exception $productionCompletionError)"
}
if ($null -ne $productionCompletionError) {
    throw $productionCompletionError
}
