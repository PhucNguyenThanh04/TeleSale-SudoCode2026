import os

from speech import __main__ as cli


def test_host_asr_reads_root_env_and_btc_path_before_building_parser(tmp_path, monkeypatch):
    (tmp_path / '.env').write_text('ASR_MODEL=whisper-small\nASR_DEVICE=cpu\nASR_COMPUTE_TYPE=int8\nBTC_ROOT=./official data\n')
    monkeypatch.setattr(cli, 'PACKAGE_DIR', tmp_path / 'speech')
    monkeypatch.setattr(os, 'environ', dict(os.environ))
    for key in ('ASR_MODEL', 'ASR_DEVICE', 'ASR_COMPUTE_TYPE', 'BTC_ROOT', 'BTC_DATA_DIR'):
        monkeypatch.delenv(key, raising=False)
    captured = []
    monkeypatch.setattr(cli, 'cmd_transcribe', captured.append)
    cli.main(['transcribe', '--audio', './audio', '--out', './results'])
    args = captured[0]
    assert (args.model, args.device, args.compute_type) == ('whisper-small', 'cpu', 'int8')
    assert os.environ['BTC_DATA_DIR'] == str(tmp_path / 'official data')
