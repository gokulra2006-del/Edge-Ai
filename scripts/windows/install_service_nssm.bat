@echo off
REM Sentinel-AI - Windows Service Installer using NSSM (Non-Sucking Service Manager)
REM Run this script as Administrator.

set SERVICE_NAME=SentinelAI
set APP_DIR=%~dp0..\..
set PYTHON_EXE=%APP_DIR%\.venv\Scripts\python.exe

echo ==============================================================
echo Installing %SERVICE_NAME% as a Windows Service via NSSM...
echo Application Directory: %APP_DIR%
echo Python Interpreter:   %PYTHON_EXE%
echo ==============================================================

where nssm >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] NSSM executable not found in PATH!
    echo Please download NSSM from https://nssm.cc/download and place it in System32 or PATH.
    pause
    exit /b 1
)

nssm stop %SERVICE_NAME% >nul 2>&1
nssm remove %SERVICE_NAME% confirm >nul 2>&1

nssm install %SERVICE_NAME% "%PYTHON_EXE%"
nssm set %SERVICE_NAME% AppParameters "-m src.modules.dashboard.app --port 8080"
nssm set %SERVICE_NAME% AppDirectory "%APP_DIR%"
nssm set %SERVICE_NAME% DisplayName "Sentinel-AI Edge Incident Command Platform"
nssm set %SERVICE_NAME% Description "Municipal Emergency Edge Detection and Autonomous Response Appliance"
nssm set %SERVICE_NAME% Start SERVICE_AUTO_START
nssm set %SERVICE_NAME% AppStdout "%APP_DIR%\logs\service_stdout.log"
nssm set %SERVICE_NAME% AppStderr "%APP_DIR%\logs\service_stderr.log"
nssm set %SERVICE_NAME% AppRotateFiles 1
nssm set %SERVICE_NAME% AppRotateOnline 1
nssm set %SERVICE_NAME% AppRotateSeconds 86400
nssm set %SERVICE_NAME% AppRotateBytes 10485760

echo Starting %SERVICE_NAME%...
nssm start %SERVICE_NAME%

echo Service installation complete. Check status with: nssm status %SERVICE_NAME%
pause
