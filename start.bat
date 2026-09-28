@echo off
title LitAssist (keep this window open while you work)
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo LitAssist is not installed yet. Double click install.bat first.
    pause
    exit /b 1
)
echo LitAssist is starting and will open in your browser.
echo Keep this window open while you work. Close it to stop LitAssist.
.venv\Scripts\python -m streamlit run app.py
