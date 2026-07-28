@echo off
cd /d "%~dp0"
if not exist venv (
  py -3 -m venv venv
  venv\Scripts\pip install -r requirements-dev.txt
) else (
  venv\Scripts\pip install -q -r requirements-dev.txt
)
venv\Scripts\pip install -r requirements-dev.txt
venv\Scripts\python -m pytest tests\ -v
exit /b %ERRORLEVEL%
