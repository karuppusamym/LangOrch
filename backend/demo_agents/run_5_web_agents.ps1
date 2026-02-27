$ErrorActionPreference = "Stop"

# Launches 5 WEB agents in one shared pool for load/saturation testing.
# Each agent gets a unique port/id/resource_key and the same pool_id.

$poolId = "web_pool_1"
$basePort = 9100
$count = 5

Write-Host "Starting $count WEB agents in shared pool '$poolId'..." -ForegroundColor Cyan

for ($i = 1; $i -le $count; $i++) {
    $port = $basePort + $i - 1
    $agentId = "playwright-web-agent-$i"
    $resourceKey = "web_agent_$i"

    $script = @"
`$env:WEB_AGENT_DRY_RUN = "true"
`$env:WEB_AGENT_HEADLESS = "true"
`$env:WEB_AGENT_ID = "$agentId"
`$env:WEB_AGENT_NAME = "Playwright Web Agent $i"
`$env:WEB_AGENT_PORT = "$port"
`$env:WEB_AGENT_CHANNEL = "web"
`$env:WEB_AGENT_POOL_ID = "$poolId"
`$env:WEB_AGENT_RESOURCE_KEY = "$resourceKey"
`$env:WEB_AGENT_CONCURRENCY = "1"
Set-Location "c:/Users/karup/AGProjects/LangOrch/backend"
C:/Users/karup/AGProjects/LangOrch/.venv/Scripts/python.exe -m uvicorn demo_agents.web_agent:app --host 127.0.0.1 --port $port --log-level warning
"@

    Start-Job -Name "langorch-web-agent-$i" -ScriptBlock ([ScriptBlock]::Create($script)) | Out-Null
    Write-Host "  Started $agentId on http://127.0.0.1:$port (resource_key=$resourceKey)" -ForegroundColor Green
}

Write-Host "" 
Write-Host "Active jobs:" -ForegroundColor Yellow
Get-Job -Name "langorch-web-agent-*" | Format-Table Id, Name, State

Write-Host ""
Write-Host "To stop all demo web agents:" -ForegroundColor Yellow
Write-Host "  Get-Job -Name 'langorch-web-agent-*' | Stop-Job; Get-Job -Name 'langorch-web-agent-*' | Remove-Job"
