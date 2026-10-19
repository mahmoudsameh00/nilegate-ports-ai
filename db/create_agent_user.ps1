<#
Create (or update) the agents' checkpointer login that joins agent_writer (migration 016; Agents plan §5b S4, P5-3).
Run by the owner from the project root, after migration 016:

    powershell -NoProfile -ExecutionPolicy Bypass -File db\create_agent_user.ps1

If .env has no PG_AGENT_USER / PG_AGENT_PASSWORD yet, the script adds them (user ports_agent, a random 24-character
alphanumeric password) — .env stays git-ignored. The login joins agent_writer only (DML on schema agent_state,
nothing elsewhere) and gets search_path = agent_state itself (role settings of agent_writer are not inherited by its
members). The values reach psql inside the container as environment variables passed by name; they never appear on a
command line or in the output. Then run, in this order:
    uv run python pipelines/scripts/agents/Checkpointer_setup.py   (creates the checkpoint tables, as the owner)
    uv run python db/check_agent_user.py                           (checks the login from the host)
#>
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$envPath = Join-Path $root ".env"
$cfg = @{}
Get-Content $envPath | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object { $k, $v = $_ -split '=', 2; $cfg[$k.Trim()] = $v.Trim() }
if (-not $cfg.PG_AGENT_USER -or -not $cfg.PG_AGENT_PASSWORD) {
    $pwd = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
    Add-Content -Path $envPath -Value "`r`n# Agents' checkpointer login, member of agent_writer (migration 016)`r`nPG_AGENT_USER=ports_agent`r`nPG_AGENT_PASSWORD=$pwd" -Encoding ascii
    $cfg.PG_AGENT_USER = "ports_agent"; $cfg.PG_AGENT_PASSWORD = $pwd
    Write-Output "added PG_AGENT_USER / PG_AGENT_PASSWORD to .env"
}
$sql = @'
SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'u')
            THEN format('ALTER ROLE %I LOGIN PASSWORD %L', :'u', :'p')
            ELSE format('CREATE ROLE %I LOGIN PASSWORD %L', :'u', :'p') END \gexec
SELECT format('GRANT agent_writer TO %I', :'u') \gexec
SELECT format('ALTER ROLE %I SET search_path = agent_state', :'u') \gexec
SELECT rolname, rolcanlogin, (SELECT string_agg(b.rolname, ',') FROM pg_auth_members m JOIN pg_roles b ON b.oid = m.roleid
       WHERE m.member = r.oid) AS member_of FROM pg_roles r WHERE rolname = :'u';
'@
$tmp = Join-Path $env:TEMP "agent_user.sql"
[IO.File]::WriteAllText($tmp, $sql, (New-Object Text.UTF8Encoding $false))
$env:AG_USER = $cfg.PG_AGENT_USER; $env:AG_PWD = $cfg.PG_AGENT_PASSWORD
try {
    docker cp $tmp ports-postgres:/tmp/agent_user.sql | Out-Null
    docker exec -e AG_USER -e AG_PWD ports-postgres sh -c 'psql -U postgres -d ports_logistics -X -q -v ON_ERROR_STOP=1 -v u=$AG_USER -v p=$AG_PWD -f /tmp/agent_user.sql; rm -f /tmp/agent_user.sql'
    if ($LASTEXITCODE -ne 0) { throw "psql failed" }
} finally {
    foreach ($n in "AG_USER", "AG_PWD") { [Environment]::SetEnvironmentVariable($n, $null, "Process") }
    [IO.File]::Delete($tmp)
}
