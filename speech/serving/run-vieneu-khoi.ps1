$ErrorActionPreference = 'Stop'
$port = 18111
if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
    throw "Port $port already has a listener; refusing to replace it."
}
$env:HF_HOME = 'H:\TeleSaleVieNeu\hf-cache'
$env:HF_HUB_OFFLINE = '1'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location 'C:\Users\KHOI\TeleSaleSpeech'
& 'H:\TeleSaleVieNeu\.venv\Scripts\python.exe' -m uvicorn serving.vieneu_sidecar:app --host 127.0.0.1 --port $port --no-access-log
