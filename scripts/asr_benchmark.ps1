# ASR benchmark B0/B1/B2 (speech/README.md §10). Chạy từ gốc repo:
#   powershell -ExecutionPolicy Bypass -File scripts\asr_benchmark.ps1 [-Device cuda|cpu] [-Tag v2]
param(
    [string]$Device = "cuda",
    [string]$Tag = (Get-Date -Format "yyyyMMdd-HHmm"),
    [string]$BtcDir = $(if ($env:BTC_DATA_DIR) { $env:BTC_DATA_DIR } else { "D:\Github\TeleSale-SudoCode2026\BTC-Data-Vong1-TEAMS" })
)
$ErrorActionPreference = "Stop"
$env:BTC_DATA_DIR = $BtcDir
$env:PYTHONIOENCODING = "utf-8"
$py = ".\.venv-speech\Scripts\python.exe"

if (-not (Test-Path $py)) {
    py -3.12 -m venv .venv-speech
    & .\.venv-speech\Scripts\pip install -r speech\requirements.txt "av==18.1.0" nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
}
# DLL CUDA cài qua pip không tự vào PATH trên Windows
$nv = Resolve-Path ".\.venv-speech\Lib\site-packages\nvidia"
$env:PATH = "$nv\cublas\bin;$nv\cudnn\bin;$env:PATH"
$ct = if ($Device -eq "cuda") { "float16" } else { "int8" }

# Audio proxy bằng edge-tts (cần mạng, có cache). BTC chưa phát audio thật.
$ds = "speech\data\datasets"
$sets = @(
    @{ out = "btc-edge";          args = @("--dialogues", "btc") },
    @{ out = "team22-edge-synth"; args = @("--dialogues", "speech\dialogues\team_synthetic.json") },
    @{ out = "team22-edge-clone"; args = @("--dialogues", "speech\dialogues\team_clone.template.json", "--preview-team") }
)
foreach ($s in $sets) {
    if (-not (Test-Path "$ds\$($s.out)\audio")) {
        & $py -m speech synth --engine edge @($s.args) --out "$ds\$($s.out)"
    }
}

& $py -m speech baseline --datasets "$ds\btc-edge" `
    --out "speech\data\runs\btc-edge-baseline-$Tag" --device $Device --compute-type $ct
& $py -m speech baseline --datasets "$ds\team22-edge-synth" "$ds\team22-edge-clone" `
    --out "speech\data\runs\team22-baseline-$Tag" --device $Device --compute-type $ct
Write-Host "Reports: speech\data\runs\*-baseline-$Tag\report.md"
