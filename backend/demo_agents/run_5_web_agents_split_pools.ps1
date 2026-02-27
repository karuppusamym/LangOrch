$ErrorActionPreference = "Stop"

# Launches 5 WEB agents in DIFFERENT pools for dispatcher behavior comparison.
# Each agent gets unique port/id/resource_key/pool_id.

$basePort = 9200
$count = 5

Write-Host "Starting $count WEB agents in separate pools..." -ForegroundColor Cyan

for ($i = 1; $i -le $count; $i++) {
    $port = $basePort + $i - 1
    $agentId = "playwright-web-agent-split-$i"
    $resourceKey = "web_split_agent_$i"
    $poolId = "web_pool_$i"

    $script = @"
`$env:WEB_AGENT_DRY_RUN = "true"
`$env:WEB_AGENT_HEADLESS = "true"
`$env:WEB_AGENT_ID = "$agentId"
`$env:WEB_AGENT_NAME = "Playwright Web Agent Split $i"
`$env:WEB_AGENT_PORT = "$port"
`$env:WEB_AGENT_CHANNEL = "web"
`$env:WEB_AGENT_POOL_ID = "$poolId"
`$env:WEB_AGENT_RESOURCE_KEY = "$resourceKey"
`$env:WEB_AGENT_CONCURRENCY = "1"
Set-Location "c:/Users/karup/AGProjects/LangOrch/backend"
C:/Users/karup/AGProjects/LangOrch/.venv/Scripts/python.exe -m uvicorn demo_agents.web_agent:app --host 127.0.0.1 --port $port --log-level warning
"@

    Start-Job -Name "langorch-web-agent-split-$i" -ScriptBlock ([ScriptBlock]::Create($script)) | Out-Null
    Write-Host "  Started $agentId on http://127.0.0.1:$port (pool_id=$poolId, resource_key=$resourceKey)" -ForegroundColor Green
}

Write-Host ""
Write-Host "Active jobs:" -ForegroundColor Yellow
Get-Job -Name "langorch-web-agent-split-*" | Format-Table Id, Name, State

Write-Host ""
Write-Host "To stop all split-pool demo agents:" -ForegroundColor Yellow
Write-Host "  Get-Job -Name 'langorch-web-agent-split-*' | Stop-Job; Get-Job -Name 'langorch-web-agent-split-*' | Remove-Job"
