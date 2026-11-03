<#
Register (or remove) the Windows Task Scheduler task of the Voyage Watch (Agents plan Phase 11, §6c P11-7).
Written 2026-10-28 by the autonomous session and NOT registered: the owner runs it once, from the project root, in a
normal (not elevated) PowerShell, after adding WATCH_RUN_AS=<an Operations manager, e.g. 2> to .env:

    powershell -NoProfile -ExecutionPolicy Bypass -File ops\scheduler\register_voyage_watch.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File ops\scheduler\register_voyage_watch.ps1 -Unregister

The task "NileGate Voyage Watch" runs `Voyage_watch.py scheduled` every day at 10:30 and 22:30 local time (every
12 h: the Open-Meteo free quota, F12), only while the owner is logged on (no stored Windows password; Docker Desktop
starts after logon — the firing waits up to 30 min for PostgreSQL and MongoDB), as soon as possible after a missed
start, stopped after 1 h, never two at once. Each firing resumes a run stopped mid-way, else watches the next instant
of the replay (2026-09-06T00:00Z … 2026-09-13T00:00Z, every 12 h: 15 firings), else does nothing ("done"). Its
console output is appended to reports\_log\voyage_watch_console.log; the record of each firing is
reports\_log\voyage_watch.jsonl; the alerts are in reports\voyage_watch\ (read them with `Voyage_watch.py alerts`).
A firing by hand:

    Start-ScheduledTask -TaskName "NileGate Voyage Watch"
    Get-ScheduledTaskInfo -TaskName "NileGate Voyage Watch"     (LastRunTime, LastTaskResult, NextRunTime)
#>
param([switch]$Unregister, [string[]]$At = @("10:30", "22:30"))
$ErrorActionPreference = "Stop"
$name = "NileGate Voyage Watch"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

if ($Unregister) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Output "removed task '$name'"
    } else { Write-Output "no task '$name'" }
    return
}

$uv = (Get-Command uv -ErrorAction Stop).Source          # an absolute path: the task does not rely on PATH
if (-not (Test-Path (Join-Path $root ".env"))) { throw ".env not found in $root" }
if (-not (Select-String -Path (Join-Path $root ".env") -Pattern '^WATCH_RUN_AS=\d+' -Quiet)) {
    throw "WATCH_RUN_AS (an Operations manager's employee id) is not set in .env"
}
$log = Join-Path $root "reports\_log"
New-Item -ItemType Directory -Force $log | Out-Null

# exit code of Voyage_watch.py kept for LastTaskResult (0 done, 1 the run raised, 2 a database unreachable,
# 3 the identity is not an Operations manager)
$cmd = ('$env:PYTHONIOENCODING = ''utf-8''; & ''{0}'' run python pipelines/scripts/agents/Voyage_watch.py scheduled ' +
        '2>&1 | Out-File -Append -Encoding utf8 ''reports\_log\voyage_watch_console.log''; exit $LASTEXITCODE') -f $uv
$action = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $root `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"$cmd`""
$triggers = foreach ($t in $At) {
    $start = [datetime]::Today.Add([timespan]::Parse($t))
    $tr = New-ScheduledTaskTrigger -Daily -At $start
    # a start without a UTC offset is local wall-clock time and follows DST (ADR-054 amendment 2)
    $tr.StartBoundary = $start.ToString("yyyy-MM-dd'T'HH:mm:ss")
    $tr
}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger $triggers -Settings $settings -Principal $principal `
    -Description "Agents plan Phase 11: Voyage_watch.py scheduled (next instant of the voyage-watch replay; alerts saved)" `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName $name
foreach ($tr in $task.Triggers) {
    if ($tr.StartBoundary -match '(Z|[+-]\d\d:\d\d)$') { throw "trigger stored with a UTC offset ($($tr.StartBoundary))" }
}
$info = Get-ScheduledTaskInfo -TaskName $name
Write-Output "registered task '$name': every day at $($At -join ' and ') (local time), user $env:USERNAME, logged-on only"
Write-Output "next run: $($info.NextRunTime) | working directory: $root | uv: $uv"
