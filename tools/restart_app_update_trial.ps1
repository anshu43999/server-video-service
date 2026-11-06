param([Parameter(Mandatory=$true)][int]$ExpectedListener, [Parameter(Mandatory=$true)][int]$ExpectedParent)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backup = Join-Path $root 'backups/M42-T13-enablement-20261106'
$python = Join-Path $root '.venv/Scripts/python.exe'
$expected = ('"' + $python.Replace('/', '\') + '" -m uvicorn app.main:app --host 0.0.0.0 --port 8080')
$listener = @(Get-NetTCPConnection -LocalPort 8080 -State Listen)
$child = Get-CimInstance Win32_Process -Filter "ProcessId=$ExpectedListener"
$parent = Get-CimInstance Win32_Process -Filter "ProcessId=$ExpectedParent"
if ($listener.Count -ne 1 -or $listener[0].OwningProcess -ne $ExpectedListener -or
    $listener[0].LocalAddress -ne '0.0.0.0' -or -not $child -or -not $parent -or
    $child.ParentProcessId -ne $ExpectedParent -or $child.CommandLine.Trim() -ne $expected -or $parent.CommandLine.Trim() -ne $expected) {
    throw 'Service identity changed; refusing restart.'
}
if (-not (Test-Path -LiteralPath (Join-Path $backup 'environment-before.env'))) { throw 'Rollback backup missing.' }
$health = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/healthz' -TimeoutSec 5
if ($health.status -ne 'ok' -or $health.streams -ne 0) { throw 'Service not healthy and idle; refusing restart.' }
function Start-CurrentService([string]$label) {
    $start = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.main:app','--host','0.0.0.0','--port','8080') -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $backup ($label + '.stdout.log')) -RedirectStandardError (Join-Path $backup ($label + '.stderr.log')) -PassThru
    return $start.Id
}
function Wait-Health {
    $deadline = (Get-Date).AddSeconds(45)
    do {
        try {
            $state = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/healthz' -TimeoutSec 2
            if ($state.status -eq 'ok') { return $true }
        } catch {}
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    return $false
}
Stop-Process -Id $ExpectedParent,$ExpectedListener -ErrorAction SilentlyContinue
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    if (-not (Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 250
}
if (Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue) { throw 'Port remains occupied; did not start another service.' }
$newLauncher = Start-CurrentService 'enabled'
if (Wait-Health) {
    Write-Output "Existing HTTP backend restarted successfully; launcher=$newLauncher"
    Get-NetTCPConnection -LocalPort 8080 -State Listen | Select-Object LocalAddress,LocalPort,OwningProcess
} else {
    if (Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue) {
        throw 'New listener is unhealthy; manual inspection required, no unrelated process stopped.'
    }
    Copy-Item -LiteralPath (Join-Path $backup 'environment-before.env') -Destination (Join-Path $root '.env') -Force
    $recovered = Start-CurrentService 'rollback'
    $healthy = Wait-Health
    throw "Enablement startup failed; original configuration restored; recovery launcher=$recovered; healthy=$healthy"
}
