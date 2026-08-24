@echo off
set "ROOT=%~dp0"
set "PYTHONW=%ROOT%.venv\Scripts\pythonw.exe"
set "APP=%ROOT%windows\MyCompBot.py"

if not exist "%PYTHONW%" (
  echo Python environment not found: %PYTHONW%
  echo Run windows\Run MyComp Bot.ps1 first.
  pause
  exit /b 1
)

start "MyComp Bot" /min "%PYTHONW%" "%APP%"
exit /b 0
