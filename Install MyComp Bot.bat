@echo off
setlocal EnableExtensions
title Install MyComp Bot

set "REPO=apinanautan/mycomp-bot-windows"
set "DEST=%LOCALAPPDATA%\MyComp Bot Source"
set "LOCAL_INSTALLER=%~dp0windows\Install MyComp Bot.ps1"
set "INSTALL_ARGS="
if /i "%~1"=="--plan" set "INSTALL_ARGS=-PlanOnly"

if exist "%LOCAL_INSTALLER%" goto run_installer

where winget.exe >nul 2>&1 || goto no_winget
where git.exe >nul 2>&1 || winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
where gh.exe >nul 2>&1 || winget install --id GitHub.cli -e --source winget --accept-package-agreements --accept-source-agreements
set "PATH=%PATH%;%ProgramFiles%\Git\cmd;%ProgramFiles%\GitHub CLI"
where git.exe >nul 2>&1 || goto install_failed
where gh.exe >nul 2>&1 || goto install_failed

gh api repos/%REPO% --silent >nul 2>&1 || gh auth login --hostname github.com --git-protocol https --web
if errorlevel 1 goto github_failed
gh api repos/%REPO% --silent >nul 2>&1 || goto github_failed

if exist "%DEST%\.git" (
  git -C "%DEST%" pull --ff-only
) else (
  if exist "%DEST%" goto destination_exists
  gh repo clone "%REPO%" "%DEST%"
)
if errorlevel 1 goto download_failed
set "LOCAL_INSTALLER=%DEST%\windows\Install MyComp Bot.ps1"

:run_installer
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%LOCAL_INSTALLER%" %INSTALL_ARGS%
if errorlevel 1 goto installer_failed
exit /b 0

:no_winget
echo Windows App Installer ^(winget^) is required. Install it from Microsoft Store, then run this file again.
goto failed
:install_failed
echo Git or GitHub CLI could not be installed.
goto failed
:github_failed
echo GitHub login was not completed. Sign in as apinanautan and run this file again.
goto failed
:destination_exists
echo "%DEST%" already exists but is not a Git repository. Rename or remove that folder, then try again.
goto failed
:download_failed
echo The private GitHub repository could not be downloaded.
goto failed
:installer_failed
echo MyComp Bot setup did not finish. Read the error above, then run this file again.
:failed
pause
exit /b 1
