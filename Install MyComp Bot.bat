@echo off
setlocal EnableExtensions
title Install MyComp Bot

set "RELEASE_API=https://api.github.com/repos/apinanautan/mycomp-bot-windows/releases/latest"
set "DEST=%LOCALAPPDATA%\MyComp Bot Source"
set "LOCAL_INSTALLER=%~dp0windows\Install MyComp Bot.ps1"
set "INSTALL_ARGS="
if /i "%~1"=="--plan" set "INSTALL_ARGS=-PlanOnly"

if exist "%LOCAL_INSTALLER%" goto run_installer

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; $zip=Join-Path $env:TEMP ('mycomp-bot-'+[guid]::NewGuid().ToString('N')+'.zip'); $unpack=$zip+'.d'; try { $release=Invoke-RestMethod -Uri $env:RELEASE_API -Headers @{'User-Agent'='MyComp-Bot-Installer'}; Invoke-WebRequest -UseBasicParsing $release.zipball_url -OutFile $zip; Expand-Archive -LiteralPath $zip -DestinationPath $unpack; $source=Get-ChildItem -LiteralPath $unpack -Directory | Select-Object -First 1; if(-not $source){throw 'Release archive contains no source directory'}; $null=New-Item -ItemType Directory -Force -Path $env:DEST; Copy-Item -Path (Join-Path $source.FullName '*') -Destination $env:DEST -Recurse -Force } finally { Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue; if(Test-Path $unpack){$resolved=[IO.Path]::GetFullPath($unpack); if(-not $resolved.StartsWith([IO.Path]::GetFullPath($env:TEMP)+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe temporary extraction path'}; Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction SilentlyContinue} }"
if errorlevel 1 goto download_failed
set "LOCAL_INSTALLER=%DEST%\windows\Install MyComp Bot.ps1"

:run_installer
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%LOCAL_INSTALLER%" %INSTALL_ARGS%
if errorlevel 1 goto installer_failed
exit /b 0

:download_failed
echo MyComp Bot could not be downloaded from GitHub. Check the internet connection and try again.
start "" "https://github.com/apinanautan/mycomp-bot-windows/issues/new?title=MyComp%%20Bot%%20download%%20error"
goto failed
:installer_failed
echo MyComp Bot setup did not finish. The actual error is shown above and opened in Notepad.
:failed
pause
exit /b 1
