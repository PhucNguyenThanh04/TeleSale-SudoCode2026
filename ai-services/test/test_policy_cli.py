from unittest.mock import patch
from types import SimpleNamespace
import asyncio


def test_hybrid_cli_build_has_no_enclosing_database_transaction():
    from app.knowledge.cli import execute
    class Repo:
        async def close(self):
            pass
        def transaction(self):
            raise AssertionError('GPU build must not run inside CLI transaction')
    async def build(*args,**kwargs):
        return {'id':'synthetic','status':'prepared'}
    args=SimpleNamespace(action='policy-prepare',actor='reviewer',source_dir='synthetic',
        metadata=None,revision_id=[],expected_active=None,release_id=None,runtime_config='synthetic')
    with patch('app.knowledge.cli.configured_url',return_value='fake'), \
         patch('app.knowledge.cli.KnowledgeRepo',return_value=Repo()), \
         patch('app.knowledge.services.publish.build_configured_policy_release',new=build):
        assert asyncio.run(execute(args))['status']=='prepared'
