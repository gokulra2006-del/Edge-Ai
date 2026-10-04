@echo off
cd /d "%~dp0"
echo Starting Edge-AI dashboard at http://127.0.0.1:8084/
.venv\Scripts\python.exe scripts\run_synthetic_demo.py --port 8084
pause
