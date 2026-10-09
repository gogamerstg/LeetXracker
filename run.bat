@echo off
title LeetCode Auto-Pilot Multi-AI Engine
cd /d "%~dp0"
echo ========================================================
echo   LeetCode Auto-Pilot Multi-AI Engine
echo   Starting web dashboard on http://localhost:8000
echo ========================================================
python server.py
pause
