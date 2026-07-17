$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot '..'))
$buildApp = Join-Path $scriptRoot 'build_app.ps1'
$installerScript = Join-Path $repoRoot 'packaging\installer.iss'
$languageFile = Join-Path $repoRoot 'packaging\languages\ChineseSimplified.isl'
$artifactsDir = Join-Path $repoRoot 'artifacts'
$expectedInstaller = Join-Path $artifactsDir '十一桌面宠物安装程序.exe'
$expectedLanguageHash = '869E43E7C7B8D20C7E4397C8E98F7D1B7CF0528803ACDF019AD350143EC85469'

function Get-InnoInstallRecords {
    $records = [System.Collections.Generic.List[object]]::new()
    foreach ($hive in @('HKEY_CURRENT_USER', 'HKEY_LOCAL_MACHINE')) {
        foreach ($key in @('Inno Setup 7_is1', 'Inno Setup 6_is1')) {
            $path = "Registry::$hive\Software\Microsoft\Windows\CurrentVersion\Uninstall\$key"
            if (-not (Test-Path -LiteralPath $path)) {
                continue
            }
            $properties = Get-ItemProperty -LiteralPath $path
            if ($properties.InstallLocation -and $properties.DisplayVersion) {
                $records.Add([pscustomobject]@{
                    RegistryPath = $path
                    InstallLocation = [System.IO.Path]::GetFullPath([string]$properties.InstallLocation).TrimEnd('\', '/')
                    DisplayVersion = [version]([string]$properties.DisplayVersion)
                })
            }
        }
    }
    return $records.ToArray()
}

function Assert-OfficialInnoSignature {
    param([Parameter(Mandatory = $true)][string]$Path)

    $signature = Get-AuthenticodeSignature -FilePath $Path
    if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        throw "Inno file does not have a valid Authenticode signature: $Path ($($signature.Status))"
    }
    $subject = $signature.SignerCertificate.Subject
    if ($subject -notmatch '(^|,\s*)O=Pyrsys B\.V\.(,|$)') {
        throw "Unexpected Inno Authenticode publisher for $Path`: $subject"
    }
    return $signature
}

function Get-InnoCompilerEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$Compiler,
        [Parameter(Mandatory = $true)][object[]]$InstallRecords
    )

    $compilerPath = (Resolve-Path -LiteralPath $Compiler).Path
    $compilerDirectory = [System.IO.Path]::GetFullPath((Split-Path -Parent $compilerPath)).TrimEnd('\', '/')
    $compilerSignature = Assert-OfficialInnoSignature -Path $compilerPath

    $banner = (& $compilerPath /? 2>&1 | Out-String)
    $bannerExitCode = $LASTEXITCODE
    if ($bannerExitCode -notin @(0, 1) -or $banner -notmatch 'Inno Setup [67] Command-Line Compiler' -or $banner -notmatch 'https://www\.innosetup\.com') {
        throw "Selected compiler did not produce the official Inno banner: $compilerPath"
    }

    $adjacentUninstaller = Join-Path $compilerDirectory 'unins000.exe'
    if (-not (Test-Path -LiteralPath $adjacentUninstaller -PathType Leaf)) {
        throw "Selected compiler has no adjacent signed version evidence: $compilerPath"
    }
    $uninstallerSignature = Assert-OfficialInnoSignature -Path $adjacentUninstaller
    if ($uninstallerSignature.SignerCertificate.Subject -cne $compilerSignature.SignerCertificate.Subject) {
        throw "Compiler and adjacent uninstaller publishers differ: $compilerPath"
    }
    $versionText = (Get-Item -LiteralPath $adjacentUninstaller).VersionInfo.ProductVersion
    $versionMatch = [regex]::Match($versionText, '\d+(?:\.\d+){1,3}')
    if (-not $versionMatch.Success) {
        throw "Adjacent signed file has no version evidence: $adjacentUninstaller"
    }
    $version = [version]$versionMatch.Value

    $matchingRecords = @($InstallRecords | Where-Object {
        $_.InstallLocation.Equals($compilerDirectory, [System.StringComparison]::OrdinalIgnoreCase)
    })
    if ($matchingRecords.Count -ne 1) {
        throw "Expected exactly one uninstall record bound to selected compiler directory, found $($matchingRecords.Count): $compilerDirectory"
    }
    if ($matchingRecords[0].DisplayVersion -ne $version) {
        throw "Registry/file version evidence differs for $compilerPath`: registry=$($matchingRecords[0].DisplayVersion), file=$version"
    }

    return [pscustomobject]@{
        Compiler = $compilerPath
        Version = $version
        Publisher = $compilerSignature.SignerCertificate.Subject
        RegistryPath = $matchingRecords[0].RegistryPath
    }
}

function Find-InnoCompiler {
    $records = @(Get-InnoInstallRecords)
    $candidates = @(
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
    $candidates += @($records | ForEach-Object { Join-Path $_.InstallLocation 'ISCC.exe' })
    $trustedCandidates = @(
        $candidates |
            Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } |
            ForEach-Object { (Resolve-Path -LiteralPath $_).Path } |
            Select-Object -Unique
    )

    $pathCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $pathCommand) {
        $pathCompiler = (Resolve-Path -LiteralPath $pathCommand.Source).Path
        if ($pathCompiler -notin $trustedCandidates) {
            throw "Refusing unbound ISCC.exe from PATH: $pathCompiler"
        }
    }
    if ($trustedCandidates.Count -ne 1) {
        throw "Expected exactly one trusted Inno compiler, found $($trustedCandidates.Count): $($trustedCandidates -join ', ')"
    }
    return Get-InnoCompilerEvidence -Compiler $trustedCandidates[0] -InstallRecords $records
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

$inno = Find-InnoCompiler
$iscc = $inno.Compiler
$version = $inno.Version
if ($version -lt [version]'6.7.3' -or $version -ge [version]'8.0') {
    throw "Unsupported Inno Setup version $version; expected >=6.7.3,<8"
}
Write-Output "Inno Setup compiler: $iscc ($version); publisher=$($inno.Publisher); registry=$($inno.RegistryPath)"
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
