import os
import socket
import subprocess
import sys


def test_profile_blocks_network_and_development_settings():
    from app.configs import Settings
    assert Settings.model_config['env_file'] is None
    assert os.environ.get('EVAL_RESET_TEST_DB') != '1'
    try:
        socket.create_connection(('127.0.0.1', 1))
    except AssertionError as exc:
        assert 'offline' in str(exc)
    else:
        raise AssertionError('network was not blocked')
    child = subprocess.run([sys.executable, '-c',
        "from app.configs import Settings; assert Settings.model_config['env_file'] is None"],
        capture_output=True, text=True)
    assert child.returncode == 0, child.stderr
