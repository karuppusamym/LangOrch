$ErrorActionPreference = "Stop"

# -------------------------------------------------------------------------
# Playwright Web Agent — VISIBLE browser (headless=false)
# Use this script when you want to watch the browser while a workflow runs.
# -------------------------------------------------------------------------
$env:WEB_AGENT_DRY_RUN = "false"
$env:WEB_AGENT_HEADLESS = "false"   # <-- key difference: browser window is visible

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " LangOrch Playwright Agent (VISIBLE)    " -ForegroundColor Cyan
Write-Host " http://127.0.0.1:9000  — real browser  " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Browser window will open when the first workflow step runs." -ForegroundColor Green
Write-Host ""
Write-Host "Tip: install dependencies once if needed:" -ForegroundColor Yellow
Write-Host "  C:/Users/karup/AGProjects/LangOrch/.venv/Scripts/python.exe -m pip install playwright" -ForegroundColor Yellow
Write-Host "  C:/Users/karup/AGProjects/LangOrch/.venv/Scripts/python.exe -m playwright install chromium" -ForegroundColor Yellow
Write-Host ""

Set-Location "c:/Users/karup/AGProjects/LangOrch/backend"
C:/Users/karup/AGProjects/LangOrch/.venv/Scripts/python.exe -m uvicorn demo_agents.web_agent:app --host 127.0.0.1 --port 9000 --log-level info
