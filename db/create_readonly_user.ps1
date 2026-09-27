<#
Create (or update) the read-only PostgreSQL login user that joins ports_readonly (migration 007, ADR-034).
Run by the owner from the project root:

    powershell -NoProfile -ExecutionPolicy Bypass -File db\create_readonly_user.ps1

If .env has no PG_RO_USER / PG_RO_PASSWORD yet, the script adds them (user ports_ro, a random 24-character alphanumeric
password) — .env stays git-ignored. The values reach psql inside the container as environment variables passed by name;
they never appear on a command line or in the output. Finally db\check_readonly_user.py checks from the host (password
authentication through the published port): the user can SELECT and cannot write.
#>
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$envPath = Join-Path $root ".env"
$cfg = @{}
Get-Content $envPath | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object { $k, $v = $_ -split '=', 2; $cfg[$k.Trim()] = $v.Trim() }
if (-not $cfg.PG_RO_USER -or -not $cfg.PG_RO_PASSWORD) {
    $pwd = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
    Add-Content -Path $envPath -Value "`r`n# read-only PostgreSQL user (ADR-034)`r`nPG_RO_USER=ports_ro`r`nPG_RO_PASSWORD=$pwd" -Encoding ascii
    $cfg.PG_RO_USER = "ports_ro"; $cfg.PG_RO_PASSWORD = $pwd
    Write-Output "added PG_RO_USER / PG_RO_PASSWORD to .env"
}
$sql = @'
SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'u')
            THEN format('ALTER ROLE %I LOGIN PASSWORD %L', :'u', :'p')
            ELSE format('CREATE ROLE %I LOGIN PASSWORD %L', :'u', :'p') END \gexec
SELECT format('GRANT ports_readonly TO %I', :'u') \gexec
SELECT format('ALTER ROLE %I SET default_transaction_read_only = on', :'u') \gexec
SELECT rolname, rolcanlogin, (SELECT string_agg(b.rolname, ',') FROM pg_auth_members m JOIN pg_roles b ON b.oid = m.roleid
       WHERE m.member = r.oid) AS member_of FROM pg_roles r WHERE rolname = :'u';
'@
$tmp = Join-Path $env:TEMP "ro_user.sql"
[IO.File]::WriteAllText($tmp, $sql, (New-Object Text.UTF8Encoding $false))
$env:RO_USER = $cfg.PG_RO_USER; $env:RO_PWD = $cfg.PG_RO_PASSWORD
try {
    docker cp $tmp ports-postgres:/tmp/ro_user.sql | Out-Null
    docker exec -e RO_USER -e RO_PWD ports-postgres sh -c 'psql -U postgres -d ports_logistics -X -q -v ON_ERROR_STOP=1 -v u=$RO_USER -v p=$RO_PWD -f /tmp/ro_user.sql; rm -f /tmp/ro_user.sql'
    if ($LASTEXITCODE -ne 0) { throw "psql failed" }
} finally {
    foreach ($n in "RO_USER", "RO_PWD") { [Environment]::SetEnvironmentVariable($n, $null, "Process") }
    [IO.File]::Delete($tmp)
}
# check from the host through the published port with the password (inside the container 127.0.0.1 is 'trust')
uv run python (Join-Path $PSScriptRoot "check_readonly_user.py")
