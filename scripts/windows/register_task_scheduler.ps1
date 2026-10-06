# PowerShell script to register Sentinel-AI with Windows Task Scheduler
# Run in Administrator PowerShell: powershell -ExecutionPolicy Bypass -File scripts/windows/register_task_scheduler.ps1

$ErrorActionPreference = "Stop"
$TaskName = "Sentinel-AI-Edge-Node"
$RepoRoot = (Get-Item $PSScriptRoot\..\..).FullName
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"

Write-Host "Registering $TaskName in Windows Task Scheduler..." -ForegroundColor Cyan
Write-Host "Working Directory: $RepoRoot"
Write-Host "Python Path:       $PythonExe"

# Unregister if already present
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing scheduled task $TaskName..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Define Action
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "-m src.modules.dashboard.app --port 8080" -WorkingDirectory $RepoRoot

# Define Trigger (At System Startup)
$Trigger = New-ScheduledTaskTrigger -AtStartup

# Define Settings (Restart on failure, run indefinitely)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 365) -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)

# Register Task to run as SYSTEM or current user
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Sentinel-AI Edge Incident Command Platform" -User "NT AUTHORITY\SYSTEM"

Write-Host "Successfully registered $TaskName! To start it now:" -ForegroundColor Green
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor White
Write-Host "  Get-ScheduledTask -TaskName '$TaskName'" -ForegroundColor White
