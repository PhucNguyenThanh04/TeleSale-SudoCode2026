$ErrorActionPreference = 'Stop'
$port = 18110
if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
    throw "Port $port is already in use; refusing to overwrite an existing service."
}
$env:SPEECH_MODEL_DIR = 'H:\TeleSaleSpeech\models'
$env:KORVATTS_ASSETS_DIR = 'C:\Users\KHOI\.cache\huggingface\hub\models--dogenthq--KorvaTTS\snapshots\e5c8c218e93c1d8daa53bfe0e62b8fbc5a5e991d'
$env:HF_HUB_OFFLINE = '1'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location 'C:\Users\KHOI\TeleSaleSpeech'
& 'H:\TeleSaleSpeech\.venv\Scripts\python.exe' -m uvicorn serving.app:app --host 127.0.0.1 --port $port --no-access-log
