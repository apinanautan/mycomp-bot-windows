[CmdletBinding()]
param([switch]$PlanOnly, [switch]$NoErrorUi)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$target = 'http://127.0.0.1:8645'
$issueBase = 'https://github.com/apinanautan/mycomp-bot-windows/issues/new'
$errorLog = Join-Path $env:LOCALAPPDATA 'MyComp Bot\install-error.log'

trap {
    $details = ($_ | Out-String).Trim()
    $logSaved = $false
    try {
        $null = New-Item -ItemType Directory -Force -Path (Split-Path -Parent $errorLog)
        [IO.File]::WriteAllText($errorLog, "$(Get-Date -Format o)`r`n$details`r`n", [Text.UTF8Encoding]::new($false))
        $logSaved = $true
    } catch {}

    Write-Host ''
    Write-Host 'Actual setup error:' -ForegroundColor Red
    Write-Host $details -ForegroundColor Red
    $copied = $false
    $notepadOpened = $false
    if (-not $NoErrorUi) {
        try { Set-Clipboard -Value $details; $copied = $true } catch {}
        if ($logSaved) {
            try { Start-Process notepad.exe -ArgumentList ('"{0}"' -f $errorLog); $notepadOpened = $true } catch {}
        }
    }
    try {
        $summary = $details -replace '(?i)(token|secret|password)=\S+', '$1=[redacted]'
        if ($summary.Length -gt 2000) { $summary = $summary.Substring(0, 2000) }
        $title = [uri]::EscapeDataString('MyComp Bot installer error')
        $body = [uri]::EscapeDataString("Installer error:`r`n`r`n$summary`r`n`r`nLocal log: $errorLog")
        if (-not $NoErrorUi) { Start-Process "$issueBase?title=$title&body=$body" }
    } catch {}
    if ($notepadOpened) { Write-Host "The error log was opened in Notepad and saved to $errorLog" -ForegroundColor Yellow }
    elseif ($logSaved) { Write-Host "The error log was saved to $errorLog" -ForegroundColor Yellow }
    if ($copied) { Write-Host 'The error was copied to the clipboard. Git is not required.' -ForegroundColor Yellow }
    exit 1
}

function Find-Tailscale {
    $command = Get-Command tailscale.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $candidate = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
    if (Test-Path $candidate) { return $candidate }
    throw 'Tailscale is not installed. Install and connect Tailscale, then run this installer again.'
}

function Find-Python311 {
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    $candidates = @(
        $(if ($command) { $command.Source }),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
        (Join-Path $env:ProgramFiles 'Python311\python.exe')
    ) | Where-Object { $_ } | Select-Object -Unique
    foreach ($candidate in $candidates) {
        if (-not (Test-Path $candidate)) { continue }
        & $candidate -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) { return $candidate }
    }
    return $null
}

function Set-EnvValue([string]$Path, [string]$Key, [string]$Value, [switch]$OnlyIfMissing) {
    [string[]]$lines = @()
    if (Test-Path $Path) { $lines = @(Get-Content -LiteralPath $Path) }
    $index = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match ('^' + [regex]::Escape($Key) + '=')) { $index = $i; break }
    }
    if ($index -ge 0) {
        if (-not $OnlyIfMissing) { $lines[$index] = "$Key=$Value" }
    } else {
        $lines += "$Key=$Value"
    }
    [IO.File]::WriteAllLines($Path, $lines, [Text.UTF8Encoding]::new($false))
}

$tailscale = Find-Tailscale
$status = (& $tailscale status --json | ConvertFrom-Json)
if ($LASTEXITCODE -ne 0 -or $status.BackendState -ne 'Running') {
    throw 'Tailscale is installed but not connected. Sign in to Tailscale, then run this installer again.'
}
$dnsName = ([string]$status.Self.DNSName).TrimEnd('.')
if (-not $dnsName) { throw 'Tailscale did not report a MagicDNS name for this computer.' }
$baseUrl = "https://$dnsName"
$endpoint = "$baseUrl/mcp"

Write-Host "Tailscale endpoint: $endpoint" -ForegroundColor Cyan
if ($PlanOnly) {
    Write-Host 'Plan check passed. No files, packages, Funnel settings, or processes were changed.' -ForegroundColor Green
    exit 0
}

$python = Find-Python311
if (-not $python) {
    $winget = (Get-Command winget.exe -ErrorAction SilentlyContinue).Source
    if (-not $winget) { throw 'Python 3.11+ is required and winget is unavailable to install it.' }
    & $winget install --id Python.Python.3.11 -e --scope user --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 installation failed.' }
    $python = Find-Python311
    if (-not $python) { throw 'Python 3.11 was installed but could not be located. Restart Windows and run this installer again.' }
}

$venv = Join-Path $root '.venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $venvPython)) { & $python -m venv $venv }
& $venvPython -m pip install --require-hashes -r (Join-Path $root 'requirements.lock')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $venvPython -m pip install --no-deps $root
if ($LASTEXITCODE -ne 0) { throw 'MyComp Bot installation failed.' }

$configDir = Join-Path $env:LOCALAPPDATA 'MyComp Bot'
$configPath = Join-Path $configDir '.env'
New-Item -ItemType Directory -Force -Path $configDir | Out-Null
Set-EnvValue $configPath 'MYCOMP_PUBLIC_BASE_URL' $baseUrl
Set-EnvValue $configPath 'MYCOMP_AUTH_MODE' 'oauth' -OnlyIfMissing
$allowedRoots = @('Documents', 'Desktop', 'Downloads') | ForEach-Object { Join-Path $env:USERPROFILE $_ }
Set-EnvValue $configPath 'MYCOMP_ALLOWED_ROOTS' ($allowedRoots -join ',') -OnlyIfMissing
Set-EnvValue $configPath 'MYCOMP_ALLOW_SHELL' 'true' -OnlyIfMissing
Set-EnvValue $configPath 'MYCOMP_ALLOWED_EXECUTABLES' 'C:\Windows\System32\cmd.exe,C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -OnlyIfMissing
Set-EnvValue $configPath 'MYCOMP_SHELL_PATH' 'C:\Windows\System32;C:\Windows;C:\Windows\System32\WindowsPowerShell\v1.0' -OnlyIfMissing

$funnel = (& $tailscale funnel status --json 2>$null | ConvertFrom-Json)
$funnelKey = "${dnsName}:443"
$existing = if ($funnel -and $funnel.Web) { $funnel.Web.PSObject.Properties[$funnelKey] } else { $null }
if ($existing) {
    $rootHandler = $existing.Value.Handlers.PSObject.Properties['/']
    $proxy = if ($rootHandler) { [string]$rootHandler.Value.Proxy } else { '' }
    if ($proxy -and $proxy -ne $target) {
        throw "Tailscale Funnel port 443 already proxies to $proxy. It was not overwritten."
    }
}
if (-not $existing) {
    & $tailscale funnel --bg --yes --https=443 $target
    if ($LASTEXITCODE -ne 0) { throw 'Tailscale Funnel could not be enabled. Confirm Funnel is allowed for this tailnet.' }
}

$pythonw = Join-Path $venv 'Scripts\pythonw.exe'
$app = Join-Path $PSScriptRoot 'MyCompBot.py'
Start-Process -FilePath $pythonw -ArgumentList ('"{0}"' -f $app)
$healthy = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "$target/health" -TimeoutSec 2
        if ($response.StatusCode -eq 200) { $healthy = $true; break }
    } catch {}
}
if (-not $healthy) { throw 'MyComp Bot started but its local health check did not become ready.' }

Set-Clipboard -Value $endpoint
Write-Host ''
Write-Host 'MyComp Bot is running.' -ForegroundColor Green
Write-Host "MCP URL: $endpoint"
Write-Host 'The MCP URL was copied to the clipboard. Paste the ChatGPT callback URL in the app once when connecting a new computer.'
Write-Host 'Use the checkbox in the app to start MyComp Bot automatically whenever you sign in to Windows.'
