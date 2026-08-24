[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $python) {
  Write-Host 'Python 3.11 or later is required. Install it from https://www.python.org/downloads/windows/.' -ForegroundColor Red
  exit 1
}

$venv = Join-Path $root '.venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
  & $python.Source -m venv $venv
}
& $venvPython -m pip install --require-hashes -r (Join-Path $root 'requirements.lock')
& $venvPython -m pip install --no-deps $root
& $venvPython (Join-Path $PSScriptRoot 'MyCompBot.py')
