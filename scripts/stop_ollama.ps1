# Stops the project-local Ollama server (frees GPU memory).
Get-Process -Name "ollama*" -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*\tools\ollama\*" } | Stop-Process -Force
Write-Host "Stopped project-local Ollama processes."
