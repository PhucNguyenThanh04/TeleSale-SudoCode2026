import asyncio
import json

import pytest

from rag_eval import runner
from rag_eval.dataset import load_cases
from rag_eval.test_dataset import BTC


class Retriever:
    async def pin(self):
        return {'release_id': 'release-one', 'manifest_hash': 'hash-one'}

    async def search(self, inputs, release, top_k):
        if 'giày về chật' in inputs['query']:
            raise RuntimeError('secret-api-key')
        return {'retrieval_status': 'ok', 'context': {'knowledge_release_id': release['release_id']},
                'evidence': [{'chunk_id': 'DT-01', 'content': '7 ngày',
                              'retrieved_via': 'vector', 'applicability': {'status': 'applicable'}}]}


class Generator:
    identity = {'model': 'offline-test', 'prompt_hash': 'fixture'}

    async def generate(self, payload):
        text = json.dumps(payload, ensure_ascii=False)
        assert 'expected_answer' not in text and 'relevant_chunk_ids' not in text
        assert 'labels' not in text and 'Q01' not in text
        return {'answer': '7 ngày', 'action': 'answer', 'usage': {'total_tokens': 4}}


def test_collect_durable_failures_pinning_and_no_label_leak(tmp_path):
    out = tmp_path / 'run'
    asyncio.run(runner.collect(BTC, out, Retriever(), Generator()))
    manifest = runner.verify_run(out)
    rows = runner.read_trace(out)
    assert manifest['status'] == 'complete'
    assert len(rows) == len(load_cases(BTC)) == 60
    assert rows[0]['status'] == 'failed'
    assert 'secret-api-key' not in (out / 'trace.jsonl').read_text()
    assert rows[1]['answer'] == '7 ngày'
    assert manifest['release']['release_id'] == 'release-one'
    assert rows[1]['generation_input']['policy_evidence'][0]['chunk_id'] == 'DT-01'
    with pytest.raises(FileExistsError):
        asyncio.run(runner.collect(BTC, out, Retriever()))


def test_wrong_release_is_failed_not_accepted(tmp_path):
    class Changed(Retriever):
        async def search(self, inputs, release, top_k):
            return {'retrieval_status': 'ok', 'context': {'knowledge_release_id': 'different'}, 'evidence': []}
    out = tmp_path / 'run'
    asyncio.run(runner.collect(BTC, out, Changed()))
    assert all(r['status'] == 'failed' for r in runner.read_trace(out))


def test_interrupted_run_is_sealed_and_keeps_completed_rows(tmp_path):
    class Interrupted(Retriever):
        count = 0

        async def search(self, inputs, release, top_k):
            self.count += 1
            if self.count == 3:
                raise KeyboardInterrupt()
            return await super().search(inputs, release, top_k)
    out = tmp_path / 'run'
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(runner.collect(BTC, out, Interrupted()))
    assert len(runner.read_trace(out)) == 2
    assert runner.verify_run(out)['status'] == 'interrupted'


def test_nested_output_cannot_mutate_or_invalidate_collection(tmp_path):
    from rag_eval.scoring import score_run
    out = tmp_path / 'run'
    asyncio.run(runner.collect(BTC, out, Retriever()))
    with pytest.raises(ValueError, match='outside'):
        score_run(out, out / 'scores')
    assert runner.verify_run(out)['status'] == 'complete'


def test_nested_manifests_are_hashed(tmp_path):
    from rag_eval.dataset import write_json
    nested = tmp_path / 'nested'
    nested.mkdir()
    write_json(nested / 'manifest.json', {'source': 'one'})
    runner.seal(tmp_path, {'schema_version': 1})
    write_json(nested / 'manifest.json', {'source': 'changed'})
    with pytest.raises(ValueError, match='hash'):
        runner.verify_run(tmp_path)
