# Starts the project-local Ollama server in the background, storing models in tools\ollama\models.
$Root = Split-Path -Parent $PSScriptRoot
$OllamaDir = Join-Path $Root "tools\ollama"
$env:OLLAMA_MODELS = Join-Path $OllamaDir "models"
$env:OLLAMA_HOST = "127.0.0.1:11434"
New-Item -ItemType Directory -Force (Join-Path $Root "logs") | Out-Null
Start-Process -FilePath (Join-Path $OllamaDir "ollama.exe") -ArgumentList "serve" -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $Root "logs\ollama.out.log") -RedirectStandardError (Join-Path $Root "logs\ollama.err.log")
Write-Host "Ollama server starting on http://127.0.0.1:11434 (models: $env:OLLAMA_MODELS)"
