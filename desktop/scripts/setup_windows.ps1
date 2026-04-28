$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

$Python = Get-Command py -ErrorAction SilentlyContinue
if ($Python) {
    py -3 -m venv .venv
} else {
    python -m venv .venv
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r desktop\requirements-windows.txt
& $VenvPython -m pip install -e desktop
& $VenvPython desktop\scripts\download_desktop_models.py

Write-Host ""
Write-Host "Iris desktop is ready."
Write-Host "Offline test: .\.venv\Scripts\iris-desktop.exe --mode offline"
Write-Host "Online test:  `$env:DEEPGRAM_API_KEY='your-key'; .\.venv\Scripts\iris-desktop.exe --mode auto"