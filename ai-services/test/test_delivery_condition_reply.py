from copy import deepcopy

import pytest

from test_commerce_evidence import state, catalog, quote, stock, bind_history_observations


def delivery_state():
    s = state('Mua Aster giá 900.000đ, bắt buộc giao trong tuần này.')
    s['history'] = [{'customer': 'Tôi xem Aster.', 'agent': 'Aster giá 900.000đ.'}]
    s['session_tool_calls'] = [catalog(), quote(), stock()]
    bind_history_observations(s)
    s['tool_calls'] = [quote(), stock()]
    s['tool_calls'][0]['result']['estimated_delivery'] = '2026-11-10'
    return s
