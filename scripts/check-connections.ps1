# Health-check every connected account (no LLM calls). Usage: .\scripts\check-connections.ps1 [--user ID] [--provider ID]
Set-Location (Join-Path $PSScriptRoot "..\apps\api")
& .\.venv\Scripts\python.exe -m app.cli.check_connections @args
exit $LASTEXITCODE
