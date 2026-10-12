@echo off
title SENTINEL-AI Emergency Video Demonstration Suite
cd /d "%~dp0"
echo ======================================================================
echo   Starting Sentinel-AI Video Demonstration Suite for Ambulance & Lane
echo ======================================================================
echo.
.venv\Scripts\python.exe scripts\run_video_demonstration.py
pause
