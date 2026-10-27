<#
Register (or remove) the Windows Task Scheduler task of the Weekly Finance Pack (Agents plan Phase 8, §5e P8-2 / S3).
Run by the owner once, from the project root, in a normal (not elevated) PowerShell:

    powershell -NoProfile -ExecutionPolicy Bypass -File ops\scheduler\register_weekly_pack.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File ops\scheduler\register_weekly_pack.ps1 -Unregister

The task "NileGate Weekly Finance Pack" runs `Weekly_pack.py scheduled` every Monday at 10:30 local time (Cairo:
after the Gemini daily reset), only while the owner is logged on (no stored Windows password; Docker Desktop starts
after logon anyway — the firing itself waits up to 30 min for PostgreSQL), as soon as possible after a missed start,
restarted twice every 30 min if it fails to start, stopped after 1 h, never two at once. The command needs nothing
but .env (PACK_RUN_AS = the scheduled Finance manager, LANGSMITH_API_KEY optional). Its console output is appended
to reports\_log\scheduled_console.log; the record of each firing is reports\_log\scheduled.jsonl. A firing by hand:

    Start-ScheduledTask -TaskName "NileGate Weekly Finance Pack"
    Get-ScheduledTaskInfo -TaskName "NileGate Weekly Finance Pack"     (LastRunTime, LastTaskResult, NextRunTime)
#>
param([switch]$Unregister, [string]$At = "10:30", [string]$Day = "Monday")
$ErrorActionPreference = "Stop"
$name = "NileGate Weekly Finance Pack"
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
$log = Join-Path $root "reports\_log"
New-Item -ItemType Directory -Force $log | Out-Null

# powershell -Command: UTF-8 output appended to the console log, and the exit code of Weekly_pack.py kept for
# LastTaskResult (0 done / wait, 1 the pack raised, 2 database unreachable, 3 identity not a Finance manager)
$cmd = ('$env:PYTHONIOENCODING = ''utf-8''; & ''{0}'' run python pipelines/scripts/agents/Weekly_pack.py scheduled ' +
        '2>&1 | Out-File -Append -Encoding utf8 ''reports\_log\scheduled_console.log''; exit $LASTEXITCODE') -f $uv
$action = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $root `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"$cmd`""
$start = [datetime]::Today.Add([timespan]::Parse($At))
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Day -At $start
# New-ScheduledTaskTrigger stores the start with the UTC offset of the day it ran ("…T10:30:00+03:00"), so after a
# daylight-saving change the task fires an hour off (09:30 in Cairo winter: before the Gemini reset). A start
# without an offset is local wall-clock time and follows DST (found 2026-10-27, ADR-054 amendment 2).
$trigger.StartBoundary = $start.ToString("yyyy-MM-dd'T'HH:mm:ss")
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 30) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Agents plan Phase 8: Weekly_pack.py scheduled (next week of the 2025 replay; waits for approval)" `
    -Force | Out-Null

$info = Get-ScheduledTaskInfo -TaskName $name
$stored = (Get-ScheduledTask -TaskName $name).Triggers[0].StartBoundary
if ($stored -match '(Z|[+-]\d\d:\d\d)$') { throw "trigger stored with a UTC offset ($stored): it would not follow DST" }
if ($info.NextRunTime.ToString("HH:mm") -ne ([timespan]::Parse($At)).ToString("hh\:mm")) {
    throw "next run $($info.NextRunTime) is not at $At local time"
}
Write-Output "registered task '$name': every $Day $At (local time), user $env:USERNAME, logged-on only"
Write-Output "next run: $($info.NextRunTime) | working directory: $root | uv: $uv"
