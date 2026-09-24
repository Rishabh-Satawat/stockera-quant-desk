$pythonPath = "C:\Users\Dell\AppData\Local\Programs\Python\Python314\python.exe"
$workDir = "C:\kite-agent"

# 1. 08:50 AM Auth & System Wakeup
$action1 = New-ScheduledTaskAction -Execute$pythonPath -Argument "-c `"print('08:50 AM Auth Check Passed')`"" -WorkingDirectory $workDir
$trigger1 = New-ScheduledTaskTrigger -Daily -At "08:50"
Register-ScheduledTask -TaskName "TradingDesk_0850_Auth" -Action $action1 -Trigger $trigger1 -User $env:USERNAME -Force

# 2. 09:15 AM Market Open Entry Trigger
$action2 = New-ScheduledTaskAction -Execute $pythonPath -Argument "hedge_4leg_tracker.py" -WorkingDirectory $workDir
$trigger2 = New-ScheduledTaskTrigger -Daily -At "09:15"
Register-ScheduledTask -TaskName "TradingDesk_0915_Entry" -Action $action2 -Trigger $trigger2 -User $env:USERNAME -Force

# 3. 15:20 PM Square-off & Position Exit Trigger
$action3 = New-ScheduledTaskAction -Execute $pythonPath -Argument "hedge_4leg_tracker.py" -WorkingDirectory $workDir
$trigger3 = New-ScheduledTaskTrigger -Daily -At "15:20"
Register-ScheduledTask -TaskName "TradingDesk_1520_Exit" -Action $action3 -Trigger $trigger3 -User $env:USERNAME -Force

# 4. 15:31 PM EOD Audit Report to Telegram & Supabase
$action4 = New-ScheduledTaskAction -Execute $pythonPath -Argument "eod_audit_report.py" -WorkingDirectory $workDir
$trigger4 = New-ScheduledTaskTrigger -Daily -At "15:31"
Register-ScheduledTask -TaskName "TradingDesk_1531_EODReport" -Action $action4 -Trigger $trigger4 -User $env:USERNAME -Force

Write-Host "`n--- Registered Tasks Status ---" -ForegroundColor Cyan
Get-ScheduledTask -TaskName "TradingDesk_*" | Select-Object TaskName, State