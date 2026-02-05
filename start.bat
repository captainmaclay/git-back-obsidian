@echo off
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" "main.py"
git remote -v
