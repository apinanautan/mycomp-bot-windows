# Read-only and safe-command reference

## Tested operator entry point

This path is for the authorized Windows machine whose source checkout contains `snapgen_ai_operator.py`:

```powershell
$py = Join-Path $env:LOCALAPPDATA 'Tidmunz Studio\.venv312\Scripts\python.exe'
$operator = '<TIDMUNZ_SOURCE_DIR>\snapgen_modules\snapgen_ai_operator.py'
& $py -B $operator status
& $py -B $operator diagnose
& $py -B $operator projects
```

Supported, receipt-aware write commands (ONLY with the user authorization described in SKILL.md):

```powershell
& $py -B $operator open --title 'บท - เจ้าสาวนาคา'
& $py -B $operator stop
& $py -B $operator resume --authorize-paid
```

The last command **will refuse** a potentially ambiguous cloud retry or high-traffic clip. Never work around the refusal without verifying provider receipts and obtaining authorization. The optional `watch --interval 15` is a continuous local read-only watcher that writes `snapgen_data\logs\tidmunz_operator_watch.json`; it does not dispatch paid operations or invoke a background LLM.


Run *on the connected Windows PC*, not on ChatGPT's container. Examples below omit token output intentionally.

## Read status on loopback

```powershell
$path = Join-Path $env:LOCALAPPDATA 'Tidmunz Studio\snapgen_data\mobile_web_url.txt'
$original = [uri](Get-Content -LiteralPath $path -Raw).Trim()
$api = 'http://127.0.0.1:8765/api/status' + $original.Query
$s = Invoke-RestMethod -Uri $api -TimeoutSec 8
[pscustomobject]@{
  Title = $s.auto.title
  Busy = $s.auto.busy
  Stage = $s.auto.stage
  Detail = $s.auto.detail
  Percent = $s.auto.percent
  Images = @($s.auto.shots | Where-Object { $_.image }).Count
  Clips = @($s.auto.shots | Where-Object { $_.clip }).Count
  Total = @($s.auto.shots).Count
  LastLog = (($s.auto.log -split [char]10 | Select-Object -Last 5) -join ' | ')
} | Format-List
```

Never include `$original`, `$api`, `$original.Query` or the URL-file contents in the model's output.

## Inspect only the first missing clip

Use a Python one-liner, or a small local script, that parses `project.json` in the selected story folder. Extract only scene number, if the clip file actually exists, the provider model, error category and **presence** (not values) of UUID/receipt/task fields. Don't print complete prompts, keys, or embedded base64.

## Submit a safe command with one ID

Only after user authorization for the write/paid action:

```powershell
$path = Join-Path $env:LOCALAPPDATA 'Tidmunz Studio\snapgen_data\mobile_web_url.txt'
$original = [uri](Get-Content -LiteralPath $path -Raw).Trim()
$id = 'operator-' + [guid]::NewGuid().ToString('N')
$body = @{ id = $id; action = 'auto_stop'; data = @{} } | ConvertTo-Json -Compress
$reply = Invoke-RestMethod -Uri ('http://127.0.0.1:8765/api/command' + $original.Query) -Method POST -ContentType 'application/json' -Body $body -TimeoutSec 12
# If the command returns pending, check the SAME id:
if ($reply.pending) {
  $reply = Invoke-RestMethod -Uri ('http://127.0.0.1:8765/api/receipt/' + $id + $original.Query) -TimeoutSec 8
}
$reply | ConvertTo-Json -Depth 4
```

Replace `auto_stop` with `auto_open` and `data=@{name='exact project folder name'}`, or `auto_start` with empty `data` only after checking safe state and credits. Persist the issued id in session notes if the network fails; do NOT resend a new command on an ambiguous result.

The API supports `auto_open`, `auto_start`, `auto_stop`, `auto_repair_options`, `auto_identity_repair`. Do not invent unsupported methods like `auto_make_cover`, `auto_finish_all`, `auto_fix_json` or `auto_export`.

## Context and source

The codebase lives at `<TIDMUNZ_SOURCE_DIR>`. State rules in `AGENTS.md`; latest incident log in `STATE.md`. There is a native local rule-based watcher at `tools\naka_auto_supervisor.py` for the preexisting Naka story; it is not a general-purpose AI agent, and its absence should never be replaced with a false claim of continuous AI monitoring.
