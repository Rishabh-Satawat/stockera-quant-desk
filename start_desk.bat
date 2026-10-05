@echo off
TITLE Stockera Master Quant Desk — Autonomous Orchestrator
COLOR 0B

echo =======================================================================
echo           STOCKERA MASTER QUANT DESK - SYSTEM STARTUP
echo =======================================================================
echo.

cd /d C:\kite-agent

echo [*] Step 1: Terminating stale background processes...
powershell -Command "Get-Process -Name python, streamlit -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -notlike '*Autonomous Orchestrator*' } | Stop-Process -Force" 2>nul
timeout /t 2 /nobreak >nul

echo [*] Step 2: Verifying ledger and secrets...
if not exist "trades_ledger.json" (
    echo [] > trades_ledger.json
)

echo [*] Step 3: Booting Market Day Supervisor (15:20 Watchdog + 15:30 EOD)...
start "Stockera Supervisor Daemon" /min cmd /c "python market_day_supervisor.py"

echo [*] Booting Chain Snapshotter (Time-Series SQLite Ingestion)...
start "Stockera Chain Snapshotter" /min cmd /c "python -m chain_snapshotter"

echo [*] Booting Auto Trade Hunter (60s Scanner - Max 3/3 Quota)...
start "Stockera Auto Hunter" /min cmd /c "python auto_trade_hunter.py"
echo [*] Step 4: Booting 2-Way Interactive Telegram Listener...
start "Stockera Telegram Bot Listener" /min cmd /c "python telegram_bot_listener.py"

echo [*] Step 5: Launching Master Unified Cockpit on Port 8501...
start "" "http://localhost:8501"
echo.
echo =======================================================================
echo  DESK FULLY ARMED ON http://localhost:8501 (Press Ctrl+C to stop)
echo =======================================================================
echo.

streamlit run app_master_cockpit.py --server.port 8501 --server.headless false

pause