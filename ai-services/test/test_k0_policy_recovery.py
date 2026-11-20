import json
from pathlib import Path
from test_commerce_evidence import state

RUN = Path(__file__).resolve().parents[1] / 'eval_harness/results/knowledge-k0-current/20261111T170857Z-b5ed4233'






def test_sourced_extended_warranty_formula_is_not_a_product_quote():
    from app.agent.guardrails.checks import check_answer
    text = ('Gói bảo hành mở rộng thêm 12 tháng, giá bằng 8% giá sản phẩm, '
            'chỉ áp dụng cho gia dụng trên 3.000.000đ, mua trong vòng 15 ngày kể từ ngày nhận hàng.')
    call = {'name': 'policy.search', 'result': {'evidence': [{'content': text,
        'applicability': {'status': 'applicable'}, 'evidence_type': 'business_rule'}]}}
    assert check_answer(text, [call], 'Có bán gói bảo hành mở rộng không?')[1] is None
    wrong = text.replace('8%', '5%').replace('3.000.000', '2.000.000')
    assert check_answer(wrong, [call], 'Có bán gói bảo hành mở rộng không?')[1] is not None
