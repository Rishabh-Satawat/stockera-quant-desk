# =============================================================================
# STOCKERA QUANT - UNIFIED MASTER DESK LAUNCHER
# =============================================================================
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "STOCKERA QUANT - AUTOMATED TRADING DESK INITIALIZATION" -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Cyan

# 1. Activate Virtual Environment
Set-Location C:\kite-agent
& ".\.venv\Scripts\Activate.ps1"

# 2. Verify Dhan Connection
Write-Host ""
Write-Host "[1/4] Verifying Dhan HQ v2 API Connection..." -ForegroundColor Yellow
python C:\kite-agent\brain\test_dhan.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "Dhan Auth verification failed. Please check secrets/dhan.env" -ForegroundColor Red
    exit 1
}

# 3. Auto-Detect Expiry Target (Tuesday = NIFTY, Thursday = SENSEX)
$dayOfWeek = (Get-Date).DayOfWeek
$targetIndex = "NIFTY"
if ($dayOfWeek -eq "Thursday") {
    $targetIndex = "SENSEX"
    Write-Host ""
    Write-Host "Targeting BSE SENSEX Weekly Expiry (Thursday Cycle)" -ForegroundColor Magenta
} else {
    Write-Host ""
    Write-Host "Targeting NIFTY 50 Cycle" -ForegroundColor Magenta
}

# 4. Run Multi-Agent Deliberation
Write-Host ""
Write-Host "[2/4] Executing Multi-Agent Market Regime Committee..." -ForegroundColor Yellow
Set-Location C:\kite-agent\TradingAgents
python indian_trading_agent.py $targetIndex

# 5. Calibrate Strike & Wing Engine
Write-Host ""
Write-Host "[3/4] Calibrating Dynamic Strike Matrix..." -ForegroundColor Yellow
Set-Location C:\kite-agent\brain
if ($targetIndex -eq "SENSEX") {
    python 60-tools/python/sensex_expiry_engine.py
} else {
    python 60-tools/python/nifty_expiry_0dte_engine.py
}

# 6. Launch Visual Cockpit
Write-Host ""
Write-Host "[4/4] Launching Stockera Quant Terminal at http://localhost:8501..." -ForegroundColor Green
Set-Location C:\kite-agent\TradingAgents
streamlit run app_cockpit.py