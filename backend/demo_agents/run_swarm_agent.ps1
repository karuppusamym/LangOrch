<#
.SYNOPSIS
Runs the LangOrch Demo Swarm Agent on port 9006
#>

$env:PYTHONPATH = "..\.."
$env:SWARM_AGENT_PORT = "9006"
$env:SWARM_AGENT_ID = "swarm-demo-agent"
$env:ORCHESTRATOR_URL = "http://127.0.0.1:8000"

Write-Host "Starting Swarm Demo Agent on http://127.0.0.1:$env:SWARM_AGENT_PORT" -ForegroundColor Cyan
Write-Host "This agent exposes bounded reasoning workflows through LangOrch's existing workflow capability model." -ForegroundColor Yellow

..\..\.venv\Scripts\python.exe -m uvicorn swarm_agent:app --host 127.0.0.1 --port $env:SWARM_AGENT_PORT