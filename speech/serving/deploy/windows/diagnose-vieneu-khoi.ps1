$task = Get-ScheduledTask -TaskName 'TeleSaleVieNeu18111' -ErrorAction SilentlyContinue
$info = Get-ScheduledTaskInfo -TaskName 'TeleSaleVieNeu18111'
$port = Get-NetTCPConnection -State Listen -LocalPort 18111 -ErrorAction SilentlyContinue
$processes = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*vieneu*' -or $_.CommandLine -like '*uvicorn*' } | Select-Object ProcessId, CommandLine
@{state=[string]$task.State; taskResult=$info.LastTaskResult; lastRun=[string]$info.LastRunTime; port=@($port | Select-Object LocalAddress,LocalPort,OwningProcess); processes=@($processes); vieneuPython=(Test-Path 'H:\TeleSaleVieNeu\.venv\Scripts\python.exe'); korvaPython=(Test-Path 'H:\TeleSaleSpeech\.venv\Scripts\python.exe'); action=$task.Actions[0].Arguments} | ConvertTo-Json -Depth 5 -Compress
