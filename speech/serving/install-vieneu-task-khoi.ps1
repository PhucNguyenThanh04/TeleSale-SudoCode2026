$ErrorActionPreference = 'Stop'
$taskName = 'TeleSaleVieNeu18111'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw "Task $taskName already exists; refusing to replace it."
}
if (Get-NetTCPConnection -State Listen -LocalPort 18111 -ErrorAction SilentlyContinue) {
    throw 'Port 18111 already has a listener; refusing to replace it.'
}
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File C:\Users\KHOI\TeleSaleSpeech\serving\run-vieneu-khoi.ps1'
$trigger = New-ScheduledTaskTrigger -AtLogOn -User 'pc\khoi'
$principal = New-ScheduledTaskPrincipal -UserId 'pc\khoi' -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal | Out-Null
Start-ScheduledTask -TaskName $taskName
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
