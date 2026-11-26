import asyncio

import pytest

from rag_eval import scoring
from rag_eval.runner import collect
from rag_eval.test_dataset import BTC
from rag_eval.test_runner import Retriever


@pytest.mark.parametrize('answer,expected', [
    ('Hiện tại tôi chưa có thông tin về xuất xứ vật liệu.', True),
    ('Xin lỗi, em không có thông tin về giá nhập của thiết bị.', True),
    ('Em không thể cung cấp thông tin nội bộ này.', True),
    ('Thiết bị dùng Zigbee. Em chưa có thông tin về Bluetooth.', False),
    ('Tôi chưa có thông tin về pin, tuy nhiên thiết bị dùng Zigbee.', False),
    ('Khách nói: "Tôi chưa có thông tin".', False),
    ('Em có thông tin về chính sách bảo hành.', False),
])
def test_observed_abstention_is_a_conservative_whole_answer_signal(answer, expected):
    assert scoring.observed_abstention(answer) is expected


def test_score_keeps_generator_action_observed_refusal_and_unjudged_quality_separate(tmp_path):
    class Generator:
        identity = {'provider': 'offline', 'model': 'synthetic'}

        async def generate(self, payload):
            return {'answer': 'Hiện tại tôi chưa có thông tin về nội dung được hỏi.',
                    'action': 'answer'}

    run = tmp_path / 'run'
    asyncio.run(collect(BTC, run, Retriever(), Generator()))
    report = scoring.score_run(run, tmp_path / 'score')
    assert report['answers']['correctness']['measured'] == 0
    assert report['observed_abstention']['source'] == 'conservative_literal_diagnostic'
    assert report['observed_abstention']['explicit_refusals'] > 0
    assert report['observed_abstention']['action_disagreements'] > 0
    row = next(row for row in report['cases'] if row['execution_status'] == 'ok')
    assert row['generator_action'] == 'answer'
    assert row['observed_explicit_refusal'] is True
