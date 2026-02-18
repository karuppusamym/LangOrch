$ErrorActionPreference = "Stop"

$env:WEB_AGENT_DRY_RUN = "false"
$env:WEB_AGENT_HEADLESS = "true"

Write-Host "Starting Playwright Web Agent on http://127.0.0.1:9000 (real browser mode)" -ForegroundColor Cyan
Write-Host "Tip: install dependencies once if needed:" -ForegroundColor Yellow
Write-Host "  C:/Users/karup/AGProjects/LangOrch/.venv/Scripts/python.exe -m pip install playwright" -ForegroundColor Yellow
Write-Host "  C:/Users/karup/AGProjects/LangOrch/.venv/Scripts/python.exe -m playwright install chromium" -ForegroundColor Yellow

Set-Location "c:/Users/karup/AGProjects/LangOrch/backend"
C:/Users/karup/AGProjects/LangOrch/.venv/Scripts/python.exe -m uvicorn demo_agents.web_agent:app --host 127.0.0.1 --port 9000