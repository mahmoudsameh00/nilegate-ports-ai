<#
Create (or update) the Power BI login user that joins finance_bi (migration 013, ADR-047; Agents plan Phase 3).
Run by the owner from the project root:

    powershell -NoProfile -ExecutionPolicy Bypass -File db\create_finance_bi_user.ps1

If .env has no PG_BI_USER / PG_BI_PASSWORD yet, the script adds them (user ports_bi, a random 24-character alphanumeric
password) — .env stays git-ignored. The login joins finance_bi only (SELECT on schema finance, nothing in public), and
gets default_transaction_read_only itself (role settings of finance_bi are not inherited by its members). The values
reach psql inside the container as environment variables passed by name; they never appear on a command line or in the
output. Finally db\check_finance_bi_user.py checks from the host: finance readable, everything else refused.
#>
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$envPath = Join-Path $root ".env"
$cfg = @{}
Get-Content $envPath | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object { $k, $v = $_ -split '=', 2; $cfg[$k.Trim()] = $v.Trim() }
if (-not $cfg.PG_BI_USER -or -not $cfg.PG_BI_PASSWORD) {
    $pwd = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
    Add-Content -Path $envPath -Value "`r`n# Power BI login, member of finance_bi (ADR-047)`r`nPG_BI_USER=ports_bi`r`nPG_BI_PASSWORD=$pwd" -Encoding ascii
    $cfg.PG_BI_USER = "ports_bi"; $cfg.PG_BI_PASSWORD = $pwd
    Write-Output "added PG_BI_USER / PG_BI_PASSWORD to .env"
}
$sql = @'
SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'u')
            THEN format('ALTER ROLE %I LOGIN PASSWORD %L', :'u', :'p')
            ELSE format('CREATE ROLE %I LOGIN PASSWORD %L', :'u', :'p') END \gexec
SELECT format('GRANT finance_bi TO %I', :'u') \gexec
SELECT format('ALTER ROLE %I SET default_transaction_read_only = on', :'u') \gexec
SELECT rolname, rolcanlogin, (SELECT string_agg(b.rolname, ',') FROM pg_auth_members m JOIN pg_roles b ON b.oid = m.roleid
       WHERE m.member = r.oid) AS member_of FROM pg_roles r WHERE rolname = :'u';
'@
$tmp = Join-Path $env:TEMP "bi_user.sql"
[IO.File]::WriteAllText($tmp, $sql, (New-Object Text.UTF8Encoding $false))
$env:BI_USER = $cfg.PG_BI_USER; $env:BI_PWD = $cfg.PG_BI_PASSWORD
try {
    docker cp $tmp ports-postgres:/tmp/bi_user.sql | Out-Null
    docker exec -e BI_USER -e BI_PWD ports-postgres sh -c 'psql -U postgres -d ports_logistics -X -q -v ON_ERROR_STOP=1 -v u=$BI_USER -v p=$BI_PWD -f /tmp/bi_user.sql; rm -f /tmp/bi_user.sql'
    if ($LASTEXITCODE -ne 0) { throw "psql failed" }
} finally {
    foreach ($n in "BI_USER", "BI_PWD") { [Environment]::SetEnvironmentVariable($n, $null, "Process") }
    [IO.File]::Delete($tmp)
}
# check from the host through the published port with the password (inside the container 127.0.0.1 is 'trust')
uv run python (Join-Path $PSScriptRoot "check_finance_bi_user.py")
