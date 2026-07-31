@echo off
cd /d "%~dp0"
echo Сборка MAX-Sender.exe ...

REM Пересоздать venv, если Python внутри сломан (перенос с другого ПК/пользователя)
set NEED_VENV=0
if not exist venv set NEED_VENV=1
if exist venv\Scripts\python.exe (
  venv\Scripts\python.exe -c "import sys" 1>nul 2>nul
  if errorlevel 1 set NEED_VENV=1
) else (
  set NEED_VENV=1
)

if "%NEED_VENV%"=="1" (
  echo Пересоздание venv...
  if exist venv rmdir /s /q venv
  py -3 -m venv venv
  if errorlevel 1 (
    echo Не удалось создать venv. Установите Python 3.12+ и py launcher.
    exit /b 1
  )
  venv\Scripts\pip install -r requirements.txt
)

venv\Scripts\pip install "pyinstaller>=6.0"
venv\Scripts\pyinstaller max-sender.spec --noconfirm --clean

if exist dist\MAX-Sender.exe (
  echo.
  echo Готово: dist\MAX-Sender.exe
  echo Скопируйте MAX-Sender.exe на другой ПК — рядом создастся папка data\
) else (
  echo Ошибка сборки
  exit /b 1
)
