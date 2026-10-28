param(
    [switch]$Installer
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
$venvScripts = Join-Path $projectRoot '.venv\Scripts'
$pythonExe = Join-Path $venvScripts 'python.exe'
$pyinstallerExe = Join-Path $venvScripts 'pyinstaller.exe'
if (-not (Test-Path -LiteralPath $pythonExe) -or -not (Test-Path -LiteralPath $pyinstallerExe)) {
    throw 'Install requirements-build.txt into .venv before building.'
}
$pythonBase = (& $pythonExe -c 'import sys; print(sys.base_prefix)').Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $pythonBase)) {
    throw 'Could not locate the base Python installation.'
}

# Release builds supply this stamp. A local build uses the latest release tag.
$versionFile = Join-Path $projectRoot 'assets\version.txt'
$temporaryVersionFile = -not (Test-Path -LiteralPath $versionFile)
if ($temporaryVersionFile) {
    $tag = (& git -C $projectRoot describe --tags --abbrev=0 2>$null).Trim()
    if ($LASTEXITCODE -ne 0 -or $tag -notmatch '^v(\d+\.\d+\.\d+)$') {
        throw 'No valid release tag is available for the Windows build.'
    }
    [IO.File]::WriteAllText($versionFile, $tag, [Text.Encoding]::ASCII)
}
$tag = [IO.File]::ReadAllText($versionFile).Trim()
if ($tag -notmatch '^v(\d+\.\d+\.\d+)$') { throw "Invalid version stamp: $tag" }
$version = $Matches[1]

$originalPath = $env:PATH
try {
    # A small PATH keeps unrelated developer-tool DLLs out of the EXE.
    $env:PATH = @($venvScripts, $pythonBase, "$env:SystemRoot\System32", $env:SystemRoot,
                  "$env:SystemRoot\System32\Wbem") -join ';'
    Push-Location $projectRoot
    try {
        & $pyinstallerExe --noconfirm --clean steamcase.spec
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    }
    finally { Pop-Location }

    $appExe = Join-Path $projectRoot 'dist\CaseCovers.exe'
    if (-not (Test-Path -LiteralPath $appExe)) { throw 'The CaseCovers.exe build is missing.' }
    $appCheck = Start-Process -FilePath $appExe -ArgumentList '--selftest' -Wait -PassThru -WindowStyle Hidden
    if ($appCheck.ExitCode -ne 0) { throw "CaseCovers.exe selftest failed: $($appCheck.ExitCode)" }
    Write-Output "CaseCovers.exe built and checked (version $version)."

    if ($Installer) {
        $isccCandidates = @(
            (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
            (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
            (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
        )
        $iscc = $isccCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
        if (-not $iscc) { throw 'Inno Setup 6 (ISCC.exe) is unavailable; no installer was published.' }
        # Compile into a unique staging folder; build\installer only receives a verified installer.
        $outputDirectory = Join-Path $projectRoot 'build\installer'
        $stage = Join-Path $projectRoot ('build\installer-stage-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $stage -Force | Out-Null
        New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
        & $iscc "/DAppVersion=$version" "/O$stage" (Join-Path $PSScriptRoot 'casecovers.iss')
        if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compilation failed; the previous installer was preserved.' }
        $filename = "CaseCovers-Setup-$version.exe"
        $stageInstaller = Join-Path $stage $filename
        if (-not (Test-Path -LiteralPath $stageInstaller) -or
            (Get-Item -LiteralPath $stageInstaller).Length -lt 1MB) {
            throw 'The compiled installer is missing or implausibly small.'
        }
        $stream = [IO.File]::OpenRead($stageInstaller)
        try {
            if ($stream.ReadByte() -ne 77 -or $stream.ReadByte() -ne 90) {
                throw 'The compiled installer is not a Windows executable.'
            }
        }
        finally { $stream.Dispose() }

        # Smoke-test a real install and uninstall in a unique project-local folder.
        $smokeDir = Join-Path $projectRoot ("build\installer-smoke-" + [guid]::NewGuid().ToString('N'))
        $installedExe = Join-Path $smokeDir 'CaseCovers.exe'
        $install = Start-Process -FilePath $stageInstaller -ArgumentList @(
            '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOICONS', "/DIR=`"$smokeDir`"") -Wait -PassThru -WindowStyle Hidden
        if ($install.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $installedExe)) {
            throw "Installer smoke install failed ($($install.ExitCode)); no installer was published."
        }
        $installedCheck = Start-Process -FilePath $installedExe -ArgumentList '--selftest' -Wait -PassThru -WindowStyle Hidden
        if ($installedCheck.ExitCode -ne 0) { throw 'Installed application selftest failed; no installer was published.' }
        $uninstallExe = Join-Path $smokeDir 'unins000.exe'
        $uninstall = Start-Process -FilePath $uninstallExe -ArgumentList @(
            '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -Wait -PassThru -WindowStyle Hidden
        if ($uninstall.ExitCode -ne 0 -or (Test-Path -LiteralPath $installedExe)) {
            throw 'Installer smoke uninstall failed; no installer was published.'
        }
        if ((Test-Path -LiteralPath $smokeDir) -and
            @(Get-ChildItem -LiteralPath $smokeDir -Force).Count -gt 0) {
            throw 'Installer smoke test left files behind; no installer was published.'
        }

        # Move into build\installer only after verification; a failed check leaves the
        # previous installer untouched. GitHub Releases are the only distribution
        # channel, so nothing is copied anywhere else. Move-Item works in Windows
        # PowerShell 5.1 and PowerShell 7 alike.
        $destination = Join-Path $outputDirectory $filename
        Move-Item -LiteralPath $stageInstaller -Destination $destination -Force
        Remove-Item -LiteralPath $stage -Recurse -Force
        Write-Output "Verified installer: $destination"
    }
}
finally {
    $env:PATH = $originalPath
    if ($temporaryVersionFile -and (Test-Path -LiteralPath $versionFile)) {
        Remove-Item -LiteralPath $versionFile -Force
    }
}
