import os
import subprocess
import sys
from pathlib import Path

import pytest

from rag_eval import __main__ as cli


@pytest.mark.parametrize('argv', [
    ['run', '--btc-root', '/missing', '--out', '/not-created'],
    ['judge', '--run', '/missing', '--out', '/not-created'],
])
def test_live_requires_explicit_opt_in_before_config_or_paths(argv, monkeypatch):
    monkeypatch.setenv('LLM_API_KEY', '')
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2


def test_help_and_replay_do_not_require_credentials(tmp_path):
    env = {'PATH': os.environ['PATH'], 'PYTHONPATH': str(Path(__file__).resolve().parents[1]),
           'HOME': str(tmp_path)}
    help_result = subprocess.run([sys.executable, '-m', 'rag_eval', '--help'],
                                 env=env, text=True, capture_output=True)
    assert help_result.returncode == 0
    assert 'retrieval' in help_result.stdout
    replay = subprocess.run([sys.executable, '-m', 'rag_eval', 'score',
        '--run', str(tmp_path / 'missing'), '--out', str(tmp_path / 'scores')],
        env=env, text=True, capture_output=True)
    assert replay.returncode == 2
    assert 'LLM_API_KEY' not in replay.stderr


def test_cli_offline_score_and_compare(tmp_path):
    import asyncio
    from rag_eval.runner import collect
    from rag_eval.test_dataset import BTC
    from rag_eval.test_runner import Retriever
    run = tmp_path / 'run'
    asyncio.run(collect(BTC, run, Retriever()))
    assert cli.main(['score', '--run', str(run), '--out', str(tmp_path / 'scores')]) == 0
    assert cli.main(['compare', '--before', str(tmp_path / 'scores'), '--after',
                     str(tmp_path / 'scores'), '--out', str(tmp_path / 'comparison')]) == 0
    assert (tmp_path / 'comparison/comparison.json').is_file()


def test_retrieval_configuration_does_not_require_generator_credentials(monkeypatch):
    from rag_eval import adapters
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    settings = adapters.RetrievalSettings(_env_file=None,
        mcp_knowledge_url='http://localhost:8014/mcp', mcp_internal_token='offline')
    assert settings.mcp_knowledge_url.endswith('/mcp')
