# LangOrch Demo Setup and Execution Script
# Run this to set up agent, import procedures, and create test runs

$ErrorActionPreference = "Stop"
$BaseUrl = "http://localhost:8000/api"
$FrontendUrl = "http://localhost:3000"

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  LangOrch Demo Setup" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Check Backend
Write-Host "Step 1: Checking Backend Server..." -ForegroundColor Yellow
try {
    $health = Invoke-RestMethod -Uri "http://localhost:8000/api/health" -Method Get -TimeoutSec 3
    if ($health.status -eq "ok") {
        Write-Host "  ✓ Backend is running" -ForegroundColor Green
    }
} catch {
    Write-Host "  ✗ Backend is not running!" -ForegroundColor Red
    Write-Host "  Please start it with: cd backend && uvicorn app.main:app --reload" -ForegroundColor Red
    exit 1
}

# Step 2: Register Agent
Write-Host ""
Write-Host "Step 2: Registering Demo Agent..." -ForegroundColor Yellow
$agent = @{
    agent_id = "demo-agent-001"
    name = "Demo Agent"
    url = "http://localhost:9000"
    channel = "masteragent"
    status = "online"
    capabilities = @("web_navigation", "data_extraction", "api_calls", "form_filling", "screenshot")
    metadata = @{
        description = "Demo agent for testing workflows"
        version = "1.0.0"
    }
} | ConvertTo-Json -Depth 10

try {
    $agentResult = Invoke-RestMethod -Uri "$BaseUrl/agents" -Method Post -Body $agent -ContentType "application/json"
    Write-Host "  ✓ Agent registered: $($agentResult.agent_id)" -ForegroundColor Green
} catch {
    if ($_.Exception.Response.StatusCode.value__ -eq 409) {
        Write-Host "  ℹ Agent already exists (OK)" -ForegroundColor Cyan
    } else {
        Write-Host "  ✗ Error: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# Step 3: Import Simple HTTP Test
Write-Host ""
Write-Host "Step 3: Importing Simple HTTP Test Procedure..." -ForegroundColor Yellow
$ckp1 = Get-Content "demo_procedures\simple_http_test.ckp.json" -Raw | ConvertFrom-Json
$proc1 = @{
    procedure_id = "simple-http-test"
    version = "1.0.0"
    ckp_json = $ckp1
} | ConvertTo-Json -Depth 100

try {
    $proc1Result = Invoke-RestMethod -Uri "$BaseUrl/procedures" -Method Post -Body $proc1 -ContentType "application/json"
    Write-Host "  ✓ Imported: $($proc1Result.procedure_id) v$($proc1Result.version)" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Error: $($_.Exception.Message)" -ForegroundColor Red
}

# Step 4: Import Product Enrichment Pipeline
Write-Host ""
Write-Host "Step 4: Importing Product Enrichment Pipeline..." -ForegroundColor Yellow
$ckp2 = Get-Content "demo_procedures\product_enrichment_pipeline.ckp.json" -Raw | ConvertFrom-Json
$proc2 = @{
    procedure_id = "product-enrichment-demo"
    version = "1.0.0"
    ckp_json = $ckp2
} | ConvertTo-Json -Depth 100

try {
    $proc2Result = Invoke-RestMethod -Uri "$BaseUrl/procedures" -Method Post -Body $proc2 -ContentType "application/json"
    Write-Host "  ✓ Imported: $($proc2Result.procedure_id) v$($proc2Result.version)" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Error: $($_.Exception.Message)" -ForegroundColor Red
}

# Step 5: Create Simple Test Run
Write-Host ""
Write-Host "Step 5: Creating Simple HTTP Test Run..." -ForegroundColor Yellow
$run1 = @{
    procedure_id = "simple-http-test"
    procedure_version = "1.0.0"
    input_vars = @{ post_id = 42 }
} | ConvertTo-Json

try {
    $run1Result = Invoke-RestMethod -Uri "$BaseUrl/runs" -Method Post -Body $run1 -ContentType "application/json"
    Write-Host "  ✓ Run created: $($run1Result.run_id)" -ForegroundColor Green
    Write-Host "  → View at: $FrontendUrl/runs/$($run1Result.run_id)" -ForegroundColor Cyan
    $simpleRunId = $run1Result.run_id
} catch {
    Write-Host "  ✗ Error: $($_.Exception.Message)" -ForegroundColor Red
}

# Step 6: Create Enrichment Pipeline Run
Write-Host ""
Write-Host "Step 6: Creating Product Enrichment Run..." -ForegroundColor Yellow
$run2 = @{
    procedure_id = "product-enrichment-demo"
    procedure_version = "1.0.0"
    input_vars = @{
        product_id = 5
        enrichment_mode = "standard"
    }
} | ConvertTo-Json

try {
    $run2Result = Invoke-RestMethod -Uri "$BaseUrl/runs" -Method Post -Body $run2 -ContentType "application/json"
    Write-Host "  ✓ Run created: $($run2Result.run_id)" -ForegroundColor Green
    Write-Host "  → View at: $FrontendUrl/runs/$($run2Result.run_id)" -ForegroundColor Cyan
    $enrichmentRunId = $run2Result.run_id
} catch {
    Write-Host "  ✗ Error: $($_.Exception.Message)" -ForegroundColor Red
}

# Summary
Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  ✓ Demo Setup Complete!" -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "----------------------------------------------------------------------"
Write-Host ""
Write-Host "1. View All Runs:" -ForegroundColor White
Write-Host "   $FrontendUrl/runs" -ForegroundColor Cyan
Write-Host ""
Write-Host "2. Watch Simple HTTP Test:" -ForegroundColor White
if ($simpleRunId) {
    Write-Host "   $FrontendUrl/runs/$simpleRunId" -ForegroundColor Cyan
}
Write-Host ""
Write-Host "3. Watch Product Enrichment Pipeline:" -ForegroundColor White
if ($enrichmentRunId) {
    Write-Host "   $FrontendUrl/runs/$enrichmentRunId" -ForegroundColor Cyan
}
Write-Host ""
Write-Host "4. The enrichment workflow will PAUSE at approval gate" -ForegroundColor Yellow
Write-Host "   Go to: $FrontendUrl/approvals" -ForegroundColor Cyan
Write-Host "   And approve/reject the enrichment" -ForegroundColor White
Write-Host ""
Write-Host "5. Check registered agent:" -ForegroundColor White
Write-Host "   $FrontendUrl/agents" -ForegroundColor Cyan
Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""
