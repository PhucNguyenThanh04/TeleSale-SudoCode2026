import asyncio
from copy import deepcopy
from pathlib import Path

from eval_harness.customer_simulator import CustomerSimulator, summarize_runs


BTC = Path(__file__).resolve().parents[3] / 'BTC-Data-Vong1-TEAMS'


class Observer:
    def __init__(self, **values):
        self.values = values
        self.payloads = []

    async def observe(self, payload):
        self.payloads.append(deepcopy(payload))
        return {'on_topic': True, 'answered_outline_indexes': [], 'proposal_matches': True,
                'price_change_explained': False, 'agent_ended': False, **self.values}


def scenario(persona='khach_hoi_nhieu_khong_mua', outcome='hen_goi_lai'):
    return {'scenario_id': 'S', 'persona': persona, 'calls': {'call_3': {
        'customer_goal': 'Hỏi máy, chưa mua nếu chưa xác minh.',
        'customer_turns': ['Chị hỏi máy.', 'Giá bao nhiêu?', 'Chị đồng ý mua khi đã rõ giá.'],
        'facts_established': {'budget_vnd': 1000000, 'address': 'Hà Nội'},
        'must_not_ask': ['room_area_m2'], 'ground_truth_facts': {'price_vnd': 500000},
        'expected_outcome': outcome, 'success_if': {'tool_called': 'pricing.get_quote'}}}}


def simulator(observer=None, **kwargs):
    return CustomerSimulator(scenario(**kwargs), 'call_3', btc_root=BTC, seed=7,
                             prior_facts={'room_area_m2': 25}, observer=observer or Observer())


def reply(text, **extra):
    return {'agent_text': text, 'tool_calls': [], **extra}


def test_first_confirmation_is_free_but_repeat_is_penalized():
    async def run():
        sim = simulator()
        await sim.next_turn(None)
        await sim.next_turn(reply('Phòng 25m² đúng không ạ?'))
        assert sim.patience == 3
        await sim.next_turn(reply('Phòng 25m² đúng không ạ?'))
        assert sim.patience == 2
    asyncio.run(run())


def test_impatient_third_call_ends_on_first_repeated_open_question():
    async def run():
        sim = simulator(persona='khach_goi_lan_3_het_kien_nhan')
        assert sim.patience == 1
        await sim.next_turn(None)
        closing = await sim.next_turn(reply('Phòng chị rộng bao nhiêu mét vuông?'))
        assert closing and sim.patience == 0
        assert await sim.next_turn(reply('Dạ.')) is None
        log = sim.log()
        assert log['outcome'] == 'tu_choi' and log['ended_by'] == 'customer'
        assert log['patience_trace'] == [1, 0]
    asyncio.run(run())


def test_unknown_questions_cannot_make_customer_invent_facts():
    async def run():
        sim = simulator()
        await sim.next_turn(None)
        answer = await sim.next_turn(reply('Mã đơn hàng nào ạ?'))
        assert 'không rõ' in answer
        assert 'generated_by_order.create' not in answer
        assert sim.patience == 3
    asyncio.run(run())


def test_new_needed_slot_is_answered_without_penalty_then_becomes_known():
    async def run():
        sim = simulator()
        await sim.next_turn(None)
        assert 'Hà Nội' in await sim.next_turn(reply('Địa chỉ giao đến đâu ạ?'))
        assert sim.patience == 3
        await sim.next_turn(reply('Địa chỉ giao đến đâu ạ?'))
        assert sim.patience == 2
    asyncio.run(run())


def test_wrong_price_blocks_commitment_and_costs_patience():
    async def run():
        sim = simulator(outcome='chot_don')
        await sim.next_turn(None)
        answer = await sim.next_turn(reply('Giá 900.000đ ạ.'))
        assert sim.patience == 2 and not sim.committed
        assert '500' in answer
    asyncio.run(run())


def test_higher_historical_price_requires_explanation_and_current_truth():
    async def run():
        data = scenario(outcome='chot_don')
        data['calls']['call_3']['ground_truth_facts']['price_vnd'] = 600000
        sim = CustomerSimulator(data, 'call_3', btc_root=BTC, seed=7,
            prior_facts={'price_quoted_vnd': 500000}, observer=Observer(price_change_explained=True))
        await sim.next_turn(None)
        await sim.next_turn(reply('Giá 600.000đ vì khuyến mãi cũ hết hạn.'))
        assert sim.patience == 3
    asyncio.run(run())


def test_customer_keeps_callback_intent_even_when_proposal_matches():
    async def run():
        sim = simulator()
        outputs = [await sim.next_turn(None)]
        while (text := await sim.next_turn(reply('Giá 500.000đ, phù hợp nhu cầu.'))) is not None:
            outputs.append(text)
        assert not any('đồng ý mua' in t for t in outputs)
        assert sim.log()['outcome'] == 'hen_goi_lai'
    asyncio.run(run())


def test_off_topic_second_turn_checks_presence_and_third_ends():
    async def run():
        sim = simulator(observer=Observer(on_topic=False))
        await sim.next_turn(None)
        await sim.next_turn(reply('Nội dung không liên quan.'))
        assert 'còn đó' in await sim.next_turn(reply('Nội dung không liên quan.'))
        await sim.next_turn(reply('Nội dung không liên quan.'))
        assert sim.log()['outcome'] == 'tu_choi'
        assert sim.log()['ended_by'] == 'customer'
    asyncio.run(run())


def test_already_answered_question_is_skipped_but_consent_is_not():
    async def run():
        sim = simulator(observer=Observer(answered_outline_indexes=[1, 2]), outcome='chot_don')
        await sim.next_turn(None)
        text = await sim.next_turn(reply('Giá 500.000đ.'))
        assert 'đồng ý mua' in text
        assert 'Giá bao nhiêu' not in text
    asyncio.run(run())


def test_maximum_twelve_customer_turns_and_log_contract():
    async def run():
        data = scenario()
        data['calls']['call_3']['customer_turns'] = ['Chị tiếp tục tham khảo.'] * 20
        sim = CustomerSimulator(data, 'call_3', btc_root=BTC, seed=7,
                                prior_facts={}, observer=Observer())
        await sim.next_turn(None)
        for _ in range(11):
            assert await sim.next_turn(reply('Em đang tư vấn theo yêu cầu.'))
        assert await sim.next_turn(reply('Em đang tư vấn theo yêu cầu.')) is None
        log = sim.log()
        assert log['n_turns'] == 12 and log['outcome'] == 'timeout'
        assert set(log) >= {'scenario_id', 'call', 'persona_id', 'seed', 'patience_trace',
                            'outcome', 'n_turns', 'ended_by'}
    asyncio.run(run())


def test_three_seed_summary_requires_all_runs_and_reports_spread():
    logs = [{'seed': seed, 'scenario_id': 'S', 'call': 'call_1', 'task_success': value}
            for seed, value in [(7, True), (17, True), (27, False)]]
    result = summarize_runs(logs, seeds=[7, 17, 27], expected_calls={('S', 'call_1')})
    assert result['tsr_by_seed'] == {'7': 100.0, '17': 100.0, '27': 0.0}
    assert result['repeatability_pass'] is False
    assert summarize_runs(logs[:2], seeds=[7, 17, 27], expected_calls={('S', 'call_1')})['complete'] is False


def test_skipping_answered_question_cannot_bypass_wrong_proposal():
    async def run():
        sim = simulator(observer=Observer(answered_outline_indexes=[1], proposal_matches=False),
                        outcome='chot_don')
        await sim.next_turn(None)
        text = await sim.next_turn(reply('Em đã trả lời giá nhưng chọn sai sản phẩm.'))
        assert 'đồng ý mua' not in text or 'chưa đồng ý mua' in text
        assert sim.committed is False
    asyncio.run(run())


def test_finish_does_not_record_customer_words_that_were_never_sent():
    async def run():
        sim = simulator()
        await sim.next_turn(None)
        await sim.finish(reply('Dạ.'))
        assert sim.log()['n_turns'] == 1
    asyncio.run(run())


def test_seed_summary_does_not_treat_a_missing_later_call_as_complete():
    logs = [{'seed': seed, 'scenario_id': 'S', 'call': 'call_1', 'task_success': True}
            for seed in (7, 17, 27)]
    assert summarize_runs(logs, seeds=[7, 17, 27],
                          expected_calls={('S', 'call_1'), ('S', 'call_2')})['complete'] is False


def test_old_fact_outside_must_not_ask_can_be_requested_again_after_expiry():
    async def run():
        data = scenario()
        data['calls']['call_3']['must_not_ask'] = []
        sim = CustomerSimulator(data, 'call_3', btc_root=BTC, seed=7,
                                prior_facts={'room_area_m2': 25}, observer=Observer())
        await sim.next_turn(None)
        await sim.next_turn(reply('Phòng chị rộng bao nhiêu mét vuông?'))
        assert sim.patience == 3
    asyncio.run(run())
