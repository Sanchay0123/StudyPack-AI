# StudyPack AI - portable Tesseract OCR setup (everything stays inside this project folder; no installer, no registry).
#
# What it does:
#   1. Downloads the official 7-Zip 26.06 standalone extractor (7zr.exe) and 7-Zip itself from github.com/ip7z/7zip
#      and unpacks 7-Zip into tools\7zip (needed to unpack the Tesseract installer without running it).
#   2. Downloads the UB Mannheim Tesseract 5.4.0 Windows build from github.com/UB-Mannheim/tesseract and UNPACKS it
#      (the installer is never executed) into tools\tesseract. English language data is included.
#   3. Deletes the downloaded installers.
# StudyPack finds tools\tesseract\tesseract.exe automatically (no .env change needed).
#
# Usage (from the project root):  powershell -ExecutionPolicy Bypass -File scripts\setup_tesseract.ps1
$ErrorActionPreference = "Stop"
$Root  = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Root "tools"
$Dl    = Join-Path $Tools "_dl"
New-Item -ItemType Directory -Force $Dl | Out-Null

$SevenZip = Join-Path $Tools "7zip\7z.exe"
if (-not (Test-Path $SevenZip)) {
    Write-Host "Downloading 7-Zip 26.06 ..."
    curl.exe -L --fail -o (Join-Path $Dl "7zr.exe")    "https://github.com/ip7z/7zip/releases/download/26.06/7zr.exe"
    curl.exe -L --fail -o (Join-Path $Dl "7z-x64.exe") "https://github.com/ip7z/7zip/releases/download/26.06/7z2606-x64.exe"
    & (Join-Path $Dl "7zr.exe") x (Join-Path $Dl "7z-x64.exe") ("-o" + (Join-Path $Tools "7zip")) -y | Out-Null
}

$Tesseract = Join-Path $Tools "tesseract\tesseract.exe"
if (-not (Test-Path $Tesseract)) {
    Write-Host "Downloading Tesseract 5.4.0 (~50 MB) ..."
    $Setup = Join-Path $Dl "tesseract-setup.exe"
    curl.exe -L --fail -o $Setup "https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe"
    Write-Host "Unpacking (the installer is not run) ..."
    & $SevenZip x $Setup ("-o" + (Join-Path $Tools "tesseract")) -y "-x!`$PLUGINSDIR" "-x!Uninstall.exe" | Out-Null
}

Remove-Item -Recurse -Force $Dl -ErrorAction SilentlyContinue
& $Tesseract --version
& $Tesseract --list-langs
Write-Host "Tesseract ready at $Tesseract"
