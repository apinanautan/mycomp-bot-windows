$ErrorActionPreference='Stop'
$raw=[Console]::In.ReadToEnd()
$python=Join-Path (Split-Path $PSScriptRoot -Parent) '.venv\Scripts\python.exe'
$helper=Join-Path $PSScriptRoot 'UIAutomationBridge.py'
$raw | & $python $helper
exit $LASTEXITCODE
