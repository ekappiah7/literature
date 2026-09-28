@echo off
title LitAssist installer
cd /d "%~dp0"

set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY (where python >nul 2>nul && set PY=python)
if not defined PY (
    echo Python was not found.
    echo Install Python 3.11 or newer from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" on the first screen of the installer.
    pause
    exit /b 1
)

echo Creating a private Python environment for LitAssist...
%PY% -m venv .venv || goto :failed
echo Installing components. This takes a few minutes the first time...
.venv\Scripts\python -m pip install --upgrade pip >nul
.venv\Scripts\python -m pip install -r requirements.txt || goto :failed

rem Skip Streamlit's first-run email question
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    > "%USERPROFILE%\.streamlit\credentials.toml" echo [general]
    >> "%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)

echo Creating a LitAssist shortcut on your desktop...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop') + '\LitAssist.lnk');" ^
  "$s.TargetPath = '%~dp0start.bat'; $s.WorkingDirectory = '%~dp0'; $s.Description = 'LitAssist literature assistant'; $s.Save()"

echo.
echo Done. Double click LitAssist on your desktop to start.
pause
exit /b 0

:failed
echo.
echo Something went wrong. Take a screenshot of this window and share it.
pause
exit /b 1
