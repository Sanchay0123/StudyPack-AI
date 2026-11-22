# Starts the project-local Ollama server (if it is not already running) and the StudyPack AI web app.
# Usage (from the project root):  powershell -ExecutionPolicy Bypass -File scripts\start_app.ps1
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
try {
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
    Write-Host "Ollama already running."
} catch {
    & (Join-Path $PSScriptRoot "start_ollama.ps1")
    Start-Sleep -Seconds 4
}
& (Join-Path $Root ".venv\Scripts\streamlit.exe") run app.py
