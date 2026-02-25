<#
.SYNOPSIS
Runs the LangOrch Demo Hybrid Agent on port 9005
#>

$env:PYTHONPATH = "..\.."
$env:AGENT_PORT = "9005"
$env:AGENT_ID = "hybrid-demo-agent"
$env:ORCHESTRATOR_URL = "http://127.0.0.1:8000"

Write-Host "Starting Hybrid Demo Agent on http://127.0.0.1:$env:AGENT_PORT" -ForegroundColor Cyan
Write-Host "This agent demonstrates both granular tools and complex agent macro workflows." -ForegroundColor Yellow

..\..\.venv\Scripts\python.exe -m uvicorn hybrid_agent:app --host 127.0.0.1 --port $env:AGENT_PORT
