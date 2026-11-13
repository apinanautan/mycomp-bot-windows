[CmdletBinding()]
param([switch]$WithRuntime)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$required = @(
    'VERSION', 'pyproject.toml', 'README.md', 'AGENTS.md',
    'requirements.lock', 'capability_sources/manifest.json',
    'capability_sources/browser_cdp.py', 'capability_sources/windows_ui.py',
    'scripts/benchmark.py', 'scripts/package-app.sh',
    'scripts/prepare-icon.py', 'scripts/win/_bridge.py',
    'skills/README.md', 'skills/tool-routing/SKILL.md',
    'src/mycomp_bot_engine/server.py', 'windows/UIAutomationBridge.py'
)

$missing = @($required | Where-Object { -not (Test-Path -LiteralPath (Join-Path $root $_) -PathType Leaf) })
$version = (Get-Content -LiteralPath (Join-Path $root 'VERSION') -Raw).Trim()
$gitClean = $null
$git = Join-Path $env:ProgramFiles 'Git\cmd\git.exe'
if (Test-Path -LiteralPath $git) {
    $changes = & $git -C $root status --porcelain
    if ($LASTEXITCODE -eq 0) { $gitClean = -not [bool]$changes }
}

$result = [ordered]@{
    source_version = $version
    checked = $required.Count
    passed = $required.Count - $missing.Count
    missing = $missing
    git_clean = $gitClean
}
if ($WithRuntime) {
    $active = @()
    try {
        $active = @(Get-CimInstance Win32_Process |
            Where-Object { $_.CommandLine -match 'MyComp Bot.*versions' -and $_.CommandLine -match 'MyCompBot.py|mycomp_bot_engine.server' } |
            ForEach-Object {
                if ($_.CommandLine -match 'versions\\(v[0-9.]+)') { $Matches[1] }
            } | Select-Object -Unique)
    } catch { $active = @() }

    $health = 'unavailable'
    try {
        $response = Invoke-RestMethod 'http://127.0.0.1:8645/health' -TimeoutSec 2
        if ($response.status -eq 'ok' -and $response.service -eq 'mycomp-bot') {
            $health = 'ok'
        }
    } catch {}
    $result.active_versions = $active
    $result.engine_health = $health
}
[pscustomobject]$result | ConvertTo-Json -Compress -Depth 4
