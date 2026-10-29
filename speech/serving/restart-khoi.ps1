$ErrorActionPreference = 'Stop'
$taskName = 'TeleSaleSpeech18110'
$port = 18110
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
$listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
if ($listener) {
    $processId = $listener.OwningProcess
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId"
    if ($process.CommandLine -notlike '*uvicorn serving.app:app*--port 18110*') {
        throw "Port $port belongs to another process; refusing to stop it."
    }
    Stop-Process -Id $processId -ErrorAction Stop
}
Start-ScheduledTask -TaskName $taskName
