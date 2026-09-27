<#
Run a mongosh script inside the ports-mongo container (ADR-027).

  .\db\mongo\run.ps1 001_create_app_user.js            # as root (default)
  .\db\mongo\run.ps1 003_check_app_user.js -AsApp      # as the application user

The MONGO_* values are read from .env into this process only and passed to `docker exec -e NAME` without values, so no
password appears in a command line, in the PowerShell history or in the output. The script file is copied into the
container (/tmp) and run with `mongosh --file`, which avoids the PowerShell 5.1 quoting problems of `--eval`.
#>
param(
    [Parameter(Mandatory = $true)][string]$Script,
    [switch]$AsApp
)
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$cfg = @{}
Get-Content (Join-Path $root ".env") | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2; $cfg[$k.Trim()] = $v.Trim()
}
$env:APP_USER = $cfg.MONGO_APP_USER
$env:APP_PWD = $cfg.MONGO_APP_PASSWORD
$env:APP_DB = $cfg.MONGO_DB
$env:ROOT_USER = $cfg.MONGO_ROOT_USER
$env:ROOT_PWD = $cfg.MONGO_ROOT_PASSWORD
try {
    docker cp (Join-Path $PSScriptRoot $Script) "ports-mongo:/tmp/$Script" | Out-Null
    if ($AsApp) {
        docker exec -e APP_USER -e APP_PWD -e APP_DB ports-mongo sh -c `
            'mongosh --quiet -u $APP_USER -p $APP_PWD --authenticationDatabase admin $APP_DB --file /tmp/$0' $Script
    } else {
        docker exec -e APP_USER -e APP_PWD -e APP_DB -e ROOT_USER -e ROOT_PWD ports-mongo sh -c `
            'mongosh --quiet -u $ROOT_USER -p $ROOT_PWD --authenticationDatabase admin --file /tmp/$0' $Script
    }
    $code = $LASTEXITCODE
    docker exec ports-mongo rm -f "/tmp/$Script" | Out-Null
    exit $code
} finally {
    foreach ($n in "APP_USER", "APP_PWD", "APP_DB", "ROOT_USER", "ROOT_PWD") {
        [Environment]::SetEnvironmentVariable($n, $null, "Process")
    }
}
