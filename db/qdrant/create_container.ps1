<#
Create the ports-qdrant container once (RAG plan Phase 3, ADR-001; same pattern as ports-mongo, ADR-027).

  powershell -NoProfile -ExecutionPolicy Bypass -File db\qdrant\create_container.ps1

QDRANT_API_KEY is read from .env into this process only and passed to `docker run -e NAME` without its value, so the key
never appears in a command line, in the PowerShell history or in the output. Qdrant then requires it on every request.
Ports are published on 127.0.0.1 only. Telemetry is switched off. Refuses to run if the container already exists.
#>
$ErrorActionPreference = "Stop"
$image = "qdrant/qdrant:v1.19.1@sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")

if (docker ps -a --filter "name=^ports-qdrant$" --format "{{.Names}}") { throw "ports-qdrant already exists" }
$cfg = @{}
Get-Content (Join-Path $root ".env") | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2; $cfg[$k.Trim()] = $v.Trim()
}
if (-not $cfg.QDRANT_API_KEY) { throw "QDRANT_API_KEY missing in .env" }
$env:QDRANT__SERVICE__API_KEY = $cfg.QDRANT_API_KEY
$env:QDRANT__TELEMETRY_DISABLED = "true"
try {
    docker volume create ports-qdrant-data | Out-Null
    docker run -d --name ports-qdrant `
        -p 127.0.0.1:6333:6333 -p 127.0.0.1:6334:6334 `
        -v ports-qdrant-data:/qdrant/storage `
        -e QDRANT__SERVICE__API_KEY -e QDRANT__TELEMETRY_DISABLED `
        $image | Out-Null
    docker ps --filter name=ports-qdrant --format "{{.Names}} | {{.Image}} | {{.Status}} | {{.Ports}}"
} finally {
    foreach ($n in "QDRANT__SERVICE__API_KEY", "QDRANT__TELEMETRY_DISABLED") {
        [Environment]::SetEnvironmentVariable($n, $null, "Process")
    }
    Remove-Variable cfg
}
