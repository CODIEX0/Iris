$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$ReleaseRoot = Join-Path $Root "release\iris-windows"
$ModelDir = Join-Path $ReleaseRoot "models"
$PyInstallerWork = Join-Path $Root "build\pyinstaller-windows"
$PyInstallerSpec = Join-Path $Root "build\pyinstaller-spec"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

Set-Location $Root

if (-not (Test-Path $VenvPython)) {
    powershell -ExecutionPolicy Bypass -File (Join-Path $Root "desktop\scripts\setup_windows.ps1")
}

& $VenvPython -m pip install --upgrade pip pyinstaller
& $VenvPython -m pip install -r desktop\requirements-windows.txt
& $VenvPython -m pip install -e desktop

New-Item -ItemType Directory -Force -Path $ReleaseRoot, $ModelDir, $PyInstallerWork, $PyInstallerSpec | Out-Null
$env:IRIS_DESKTOP_MODEL_DIR = $ModelDir
$env:IRIS_OBJECT_MODEL_DIR = Join-Path $ModelDir "object_detection"
& $VenvPython desktop\scripts\download_desktop_models.py

& $VenvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --console `
    --name IrisDesktop `
    --paths desktop `
    --hidden-import pyttsx3.drivers `
    --hidden-import pyttsx3.drivers.sapi5 `
    --hidden-import sounddevice `
    --hidden-import vosk `
    --hidden-import websockets `
    --hidden-import pygame `
    --hidden-import cv2 `
    --distpath $ReleaseRoot `
    --workpath $PyInstallerWork `
    --specpath $PyInstallerSpec `
    desktop\iris_desktop\__main__.py

@'
DEEPGRAM_API_KEY=your-deepgram-key
GEMINI_API_KEY=your-gemini-key
# Optional secondary cloud fallback:
# GROQ_API_KEY=your-groq-key
'@ | Set-Content -Encoding ASCII (Join-Path $ReleaseRoot ".env.local.example")

@'
@echo off
cd /d "%~dp0"
set "IRIS_DESKTOP_MODEL_DIR=%~dp0models"
set "IRIS_OBJECT_MODEL_DIR=%~dp0models\object_detection"
IrisDesktop\IrisDesktop.exe --mode auto --camera-backend auto --object-detection on --object-confidence 0.35 %*
'@ | Set-Content -Encoding ASCII (Join-Path $ReleaseRoot "run_iris_online.bat")

@'
@echo off
cd /d "%~dp0"
set "IRIS_DESKTOP_MODEL_DIR=%~dp0models"
set "IRIS_OBJECT_MODEL_DIR=%~dp0models\object_detection"
IrisDesktop\IrisDesktop.exe --mode offline --camera-backend auto --object-detection on --object-confidence 0.35 %*
'@ | Set-Content -Encoding ASCII (Join-Path $ReleaseRoot "run_iris_offline.bat")

@'
Iris Desktop for Windows

1. Copy .env.local.example to .env.local.
2. Paste DEEPGRAM_API_KEY for online voice mode.
3. Paste GEMINI_API_KEY if you want the same env file to be usable by ROS brain tests.
4. Double-click run_iris_online.bat for Deepgram online mode.
5. Double-click run_iris_offline.bat for offline local mode.

Object recognition uses the bundled free open-source MobileNet SSD Caffe model
from https://github.com/chuanqi305/MobileNet-SSD under the MIT license, loaded
locally with OpenCV DNN. Iris can name the VOC object classes that model knows,
including person, bottle, chair, car, bicycle, bus, cat, dog, sofa, train, and
TV monitor.

The models folder is bundled in this release. Do not commit .env.local.
'@ | Set-Content -Encoding ASCII (Join-Path $ReleaseRoot "README.txt")

Compress-Archive -Path (Join-Path $ReleaseRoot "*") -DestinationPath (Join-Path $Root "release\iris-windows.zip") -Force

Write-Host ""
Write-Host "Windows Iris app built at: $ReleaseRoot"
Write-Host "Zip package: $(Join-Path $Root 'release\iris-windows.zip')"
Write-Host "Run: $(Join-Path $ReleaseRoot 'run_iris_online.bat')"