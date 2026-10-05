@echo off
TITLE Stockera Desk Shutdown
COLOR 0C

echo =======================================================================
echo           STOCKERA MASTER QUANT DESK - DESK SHUTDOWN
echo =======================================================================
echo.
echo [*] Terminating all Streamlit, Supervisor, and Sentinel processes...

powershell -Command "Get-Process -Name python, streamlit -ErrorAction SilentlyContinue | Stop-Process -Force" 2>nul

echo [OK] All trading desk services terminated. Desk is safely offline.
timeout /t 3 >nul