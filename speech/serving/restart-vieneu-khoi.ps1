$ErrorActionPreference = 'Stop'
$taskName = 'TeleSaleVieNeu18111'
$port = 18111
if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
    throw "Task $taskName does not exist."
}
$listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
if ($listener) {
    $processId = $listener.OwningProcess
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId"
    if ($process.CommandLine -notlike '*uvicorn serving.vieneu_sidecar:app*--port 18111*') {
        throw "Port $port belongs to another process; refusing to stop it."
    }
}
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($listener) { Stop-Process -Id $processId -ErrorAction Stop }
Start-ScheduledTask -TaskName $taskName
