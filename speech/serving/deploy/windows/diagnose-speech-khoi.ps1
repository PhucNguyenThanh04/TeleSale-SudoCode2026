$task = Get-ScheduledTask -TaskName 'TeleSaleSpeech18110' -ErrorAction SilentlyContinue
$info = Get-ScheduledTaskInfo -TaskName 'TeleSaleSpeech18110'
$port = Get-NetTCPConnection -State Listen -LocalPort 18110 -ErrorAction SilentlyContinue
$processes = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*serving.app:app*' } | Select-Object ProcessId,CommandLine
@{state=[string]$task.State; result=$info.LastTaskResult; lastRun=[string]$info.LastRunTime; port=@($port | Select-Object LocalAddress,LocalPort,OwningProcess); processes=@($processes)} | ConvertTo-Json -Depth 5 -Compress
