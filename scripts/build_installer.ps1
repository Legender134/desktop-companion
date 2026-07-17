$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot '..'))
$buildApp = Join-Path $scriptRoot 'build_app.ps1'
$installerScript = Join-Path $repoRoot 'packaging\installer.iss'
$languageFile = Join-Path $repoRoot 'packaging\languages\ChineseSimplified.isl'
$artifactsDir = Join-Path $repoRoot 'artifacts'
$expectedInstaller = Join-Path $artifactsDir '十一桌面宠物安装程序.exe'
$expectedLanguageHash = '869E43E7C7B8D20C7E4397C8E98F7D1B7CF0528803ACDF019AD350143EC85469'

function Find-InnoCompiler {
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    $candidates = @()
    if ($null -ne $command) {
        $candidates += $command.Source
    }
    $candidates += @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 7\ISCC.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 7\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
    )
    if (${env:ProgramFiles(x86)}) {
        $candidates += @(
            (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 7\ISCC.exe'),
            (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe')
        )
    }

    foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw 'ISCC.exe was not found. Install Inno Setup 7.0.2 or a signed version >=6.7.3,<8.'
}

function Get-InnoVersion {
    param([Parameter(Mandatory = $true)][string]$Compiler)

    # ISCC.exe itself intentionally has 0.0.0.0 version resources in recent
    # distributions. The co-installed signed uninstaller carries the product
    # version; the HKCU uninstall record is a fallback for layout variations.
    $versionTexts = [System.Collections.Generic.List[string]]::new()
    foreach ($file in @($Compiler, (Join-Path (Split-Path -Parent $Compiler) 'unins000.exe'))) {
        if (Test-Path -LiteralPath $file -PathType Leaf) {
            $info = (Get-Item -LiteralPath $file).VersionInfo
            $versionTexts.Add([string]$info.ProductVersion)
            $versionTexts.Add([string]$info.FileVersion)
        }
    }
    foreach ($key in @('Inno Setup 7_is1', 'Inno Setup 6_is1')) {
        $path = "Registry::HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Uninstall\$key"
        if (Test-Path -LiteralPath $path) {
            $versionTexts.Add([string](Get-ItemPropertyValue -LiteralPath $path -Name DisplayVersion -ErrorAction SilentlyContinue))
        }
    }
    foreach ($text in $versionTexts) {
        $match = [regex]::Match($text, '\d+(?:\.\d+){1,3}')
        if ($match.Success -and [version]$match.Value -ne [version]'0.0.0.0') {
            return [version]$match.Value
        }
    }
    throw "Could not determine Inno Setup version for: $Compiler"
}

if (-not (Test-Path -LiteralPath $languageFile -PathType Leaf)) {
    throw "Missing Simplified Chinese Inno Setup messages file: $languageFile"
}
$languageText = [System.IO.File]::ReadAllText($languageFile).Replace("`r`n", "`n")
$languageBytes = [System.Text.Encoding]::UTF8.GetBytes($languageText)
$sha256 = [System.Security.Cryptography.SHA256]::Create()
try {
    # Git may check text out as LF or CRLF. Verify the pinned translation's
    # normalized content so a standard Windows autocrlf checkout still builds.
    $languageHash = [System.Convert]::ToHexString($sha256.ComputeHash($languageBytes))
}
finally {
    $sha256.Dispose()
}
if ($languageHash -ne $expectedLanguageHash) {
    throw "Unexpected Simplified Chinese messages hash: $languageHash"
}

$iscc = Find-InnoCompiler
$version = Get-InnoVersion -Compiler $iscc
if ($version -lt [version]'6.7.3' -or $version -ge [version]'8.0') {
    throw "Unsupported Inno Setup version $version; expected >=6.7.3,<8"
}
Write-Output "Inno Setup compiler: $iscc ($version)"
Write-Output "Simplified Chinese messages: $languageFile ($languageHash)"

Push-Location $repoRoot
try {
    & $buildApp
    if ($LASTEXITCODE -ne 0) {
        throw 'Application build failed'
    }

    if (-not (Test-Path -LiteralPath $artifactsDir -PathType Container)) {
        [void](New-Item -ItemType Directory -Path $artifactsDir)
    }
    if (Test-Path -LiteralPath $expectedInstaller -PathType Leaf) {
        Remove-Item -LiteralPath $expectedInstaller -Force
    }

    & $iscc $installerScript
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup compilation failed with exit code $LASTEXITCODE"
    }

    $installers = @(Get-ChildItem -LiteralPath $artifactsDir -File -Filter '十一桌面宠物安装程序*.exe')
    if ($installers.Count -ne 1) {
        throw "Expected exactly one installer, found $($installers.Count) in $artifactsDir"
    }
    if ($installers[0].FullName -ne $expectedInstaller) {
        throw "Unexpected installer output: $($installers[0].FullName)"
    }

    $hash = (Get-FileHash -LiteralPath $expectedInstaller -Algorithm SHA256).Hash
    Write-Output "Installer: $expectedInstaller"
    Write-Output "SHA256: $hash"
    Write-Output "Size: $($installers[0].Length) bytes"
}
finally {
    Pop-Location
}
