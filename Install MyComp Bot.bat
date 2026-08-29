@echo off
setlocal EnableExtensions
title Install MyComp Bot

set "REPO_ZIP=https://github.com/apinanautan/mycomp-bot-windows/archive/refs/heads/main.zip"
set "DEST=%LOCALAPPDATA%\MyComp Bot Source"
set "LOCAL_INSTALLER=%~dp0windows\Install MyComp Bot.ps1"
set "INSTALL_ARGS="
if /i "%~1"=="--plan" set "INSTALL_ARGS=-PlanOnly"

if exist "%LOCAL_INSTALLER%" goto run_installer

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; $zip=Join-Path $env:TEMP ('mycomp-bot-'+[guid]::NewGuid().ToString('N')+'.zip'); $unpack=$zip+'.d'; try { Invoke-WebRequest -UseBasicParsing $env:REPO_ZIP -OutFile $zip; Expand-Archive -LiteralPath $zip -DestinationPath $unpack; $source=Join-Path $unpack 'mycomp-bot-windows-main'; $null=New-Item -ItemType Directory -Force -Path $env:DEST; Copy-Item -Path (Join-Path $source '*') -Destination $env:DEST -Recurse -Force } finally { Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $unpack -Recurse -Force -ErrorAction SilentlyContinue }"
if errorlevel 1 goto download_failed
set "LOCAL_INSTALLER=%DEST%\windows\Install MyComp Bot.ps1"

:run_installer
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%LOCAL_INSTALLER%" %INSTALL_ARGS%
if errorlevel 1 goto installer_failed
exit /b 0

:download_failed
echo MyComp Bot could not be downloaded from GitHub. Check the internet connection and try again.
goto failed
:installer_failed
echo MyComp Bot setup did not finish. Read the error above, then run this file again.
:failed
pause
exit /b 1
