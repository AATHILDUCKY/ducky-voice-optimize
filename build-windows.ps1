param(
    [ValidateSet("x64", "arm64")]
    [string]$Architecture = $(if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "x64" })
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python 3.10+ is required. Install it from python.org and enable the Python launcher."
}

if (-not (Test-Path ".build-venv")) {
    py -3 -m venv .build-venv
}

$Python = Join-Path $Root ".build-venv\Scripts\python.exe"
$PythonMachine = (& $Python -c "import platform; print(platform.machine().lower())").Trim()
if ($Architecture -eq "arm64" -and $PythonMachine -notmatch "arm64|aarch64") {
    throw "Arm64 releases require native Windows Arm64 Python. Detected: $PythonMachine"
}
if ($Architecture -eq "x64" -and $PythonMachine -notmatch "amd64|x86_64") {
    throw "x64 releases require x64 Python. Detected: $PythonMachine"
}
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt -r requirements-build.txt
& $Python packaging\make_icons.py
& $Python -m PyInstaller --clean --noconfirm packaging\ducky-voice-optimizer.spec

$InnoCandidates = @(
    "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
)
$ISCC = $InnoCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $ISCC) {
    throw "Inno Setup 6 or 7 is required. Install it from https://jrsoftware.org/isdl.php and run this script again."
}

New-Item -ItemType Directory -Force -Path release | Out-Null
& $ISCC "/DAppArch=$Architecture" packaging\windows\installer.iss
Write-Host "Windows installer created in $Root\release" -ForegroundColor Green
