import asyncio
import json

from rag_eval import judging
from rag_eval.runner import collect, verify_run
from rag_eval.test_dataset import BTC
from rag_eval.test_runner import Generator, Retriever


class Judge:
    identity = {'model': 'fake-judge', 'prompt_sha256': 'test', 'ragas_version': 'fake'}

    async def business(self, case, row):
        return {'correct': True, 'action': 'answer', 'version_correct': True
                if case['labels']['type'] == 'version_conflict' else None,
                'numeric_correct': None, 'restricted_leak': False, 'reason': 'fixture'}

    async def faithfulness(self, case, row):
        raise RuntimeError('credential-in-provider-error')

    async def factual_correctness(self, case, row):
        return .5


def test_judge_partial_metric_errors_are_visible_and_replayable(tmp_path):
    run = tmp_path / 'run'
    asyncio.run(collect(BTC, run, Retriever(), Generator()))
    out = tmp_path / 'judged'
    report = asyncio.run(judging.judge_run(run, out, Judge()))
    assert report['answers']['correctness']['measured'] == 59
    assert report['answers']['faithfulness']['measured'] == 0
    assert report['answers']['factual_correctness_f1']['value'] == .5
    assert report['coverage']['judge_business_failed_or_skipped'] == 1
    assert report['btc']['false_abstain_rate'] is None
    text = (out / 'judgments.jsonl').read_text()
    assert 'faithfulness_failed' in text and 'credential-in-provider-error' not in text
    assert verify_run(out)['kind'] == 'judgments'
    assert verify_run(out / 'scores')['kind'] == 'scores'


def test_refusal_skips_faithfulness_and_invalid_business_is_not_scored(tmp_path):
    class Refusing(Judge):
        async def business(self, case, row):
            value = await super().business(case, row)
            value['action'] = 'refuse'
            if case['qid'] == 'Q03': value['correct'] = 'yes'
            return value

        async def faithfulness(self, case, row):
            raise AssertionError('Must not be called on refusal')
    run = tmp_path / 'run'
    asyncio.run(collect(BTC, run, Retriever(), Generator()))
    out = tmp_path / 'judged'
    asyncio.run(judging.judge_run(run, out, Refusing()))
    rows = [json.loads(line) for line in (out / 'judgments.jsonl').read_text().splitlines()]
    q2 = next(r for r in rows if r['qid'] == 'Q02')
    q3 = next(r for r in rows if r['qid'] == 'Q03')
    assert q2['faithfulness_skip_reason'] == 'non_answer_action'
    assert q3['business'] is None and 'business_failed' in q3['errors']
