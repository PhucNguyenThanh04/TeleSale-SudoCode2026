from copy import deepcopy
from datetime import date


def parse_seed_history(value: object, *, call_date: date) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError('seed_history_unsupported')
    result = {}
    for item in value:
        if (not isinstance(item, dict) or set(item) - {'session_id','date','channel','summary','outcome'}
                or not all(isinstance(item.get(k), str) and item[k].strip()
                           for k in ('session_id','date','channel','summary'))
                or item['channel'] not in {'hotline','chat_fanpage','zalo_oa'}
                or item.get('outcome', 'khac') not in {'khac','chot_don','hen_goi_lai','chuyen_may','tu_choi'}):
            raise ValueError('seed_history_invalid')
        try:
            historical_date = date.fromisoformat(item['date'])
        except ValueError:
            raise ValueError('seed_history_date_invalid') from None
        if historical_date >= call_date:
            raise ValueError('seed_history_not_prior')
        sid = item['session_id']
        if sid in result and result[sid] != item:
            raise ValueError('seed_history_conflict')
        result[sid] = deepcopy(item)
    return list(result.values())


class SeedHistoryGateway:
    def __init__(self, inner):
        self.inner = inner
        self.scenario = None
        self.history = {}
        self.identities = {}
        self.customer_id = None

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def select(self, scenario_id: str, identities: dict, history: list[dict]):
        if scenario_id != self.scenario:
            self.history, self.customer_id = {}, None
        self.scenario, self.identities = scenario_id, identities
        for item in history:
            sid = item['session_id']
            if sid in self.history and self.history[sid] != item:
                raise ValueError('seed_history_conflict')
            self.history[sid] = deepcopy(item)

    async def invoke(self, name, args):
        result = await self.inner.invoke(name, args)
        if name != 'crm.get_customer' or not self.history:
            return result
        channel = 'zalo_oa' if 'zalo_id' in args else 'chat_fanpage' if 'fb_id' in args else 'hotline'
        identity = args.get('phone') or args.get('zalo_id') or args.get('fb_id')
        if self.identities.get(channel) != identity:
            return result
        if not result.get('found') or not result.get('customer_id') or result.get('ambiguous'):
            raise RuntimeError('seed_history_identity_unresolved')
        if self.customer_id and self.customer_id != result['customer_id']:
            raise RuntimeError('seed_history_identity_conflict')
        self.customer_id = result['customer_id']
        sessions = {s['session_id']: s for s in result.get('sessions', [])}
        for sid, item in self.history.items():
            if sid in sessions and sessions[sid] != item:
                raise RuntimeError('seed_history_conflict')
            sessions[sid] = item
        return {**result, 'sessions': deepcopy(list(sessions.values()))}
