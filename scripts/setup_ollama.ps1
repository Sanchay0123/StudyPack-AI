# StudyPack AI - portable Ollama setup (everything stays inside this project folder).
# Usage (from project root):  powershell -ExecutionPolicy Bypass -File scripts\setup_ollama.ps1
param(
    [string]$Version = "v0.40.17",
    [string]$Model = "qwen3.5:4b-q4_K_M"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$OllamaDir = Join-Path $Root "tools\ollama"
$Zip = Join-Path $Root "tools\ollama-windows-amd64.zip"
New-Item -ItemType Directory -Force (Join-Path $OllamaDir "models") | Out-Null

if (-not (Test-Path (Join-Path $OllamaDir "ollama.exe"))) {
    if (-not (Test-Path $Zip)) {
        $Url = "https://github.com/ollama/ollama/releases/download/$Version/ollama-windows-amd64.zip"
        Write-Host "Downloading $Url (~1.6 GB)..."
        curl.exe -L --fail -o $Zip $Url
    }
    Write-Host "Extracting to $OllamaDir ..."
    tar.exe -xf $Zip -C $OllamaDir
    Remove-Item $Zip
}

& (Join-Path $PSScriptRoot "start_ollama.ps1")
Start-Sleep -Seconds 5
$env:OLLAMA_MODELS = Join-Path $OllamaDir "models"
& (Join-Path $OllamaDir "ollama.exe") pull $Model
