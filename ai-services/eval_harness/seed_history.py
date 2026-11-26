from copy import deepcopy
from datetime import date
import json
import math
import re

from eval_harness.trace_evidence import contains_sensitive_pii


def parse_seed_history(value: object, *, call_date: date) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError('seed_history_unsupported')
    result = {}
    for item in value:
        if (not isinstance(item, dict) or set(item) - {'session_id','date','channel','summary','outcome','facts'}
                or not all(isinstance(item.get(k), str) and item[k].strip()
                           for k in ('session_id','date','channel','summary'))
                or item['channel'] not in {'phone','hotline','chat_fanpage','zalo_oa'}
                or item.get('outcome', 'khac') not in {'khac','chot_don','hen_goi_lai','chuyen_may','tu_choi'}):
            raise ValueError('seed_history_invalid')
        try:
            historical_date = date.fromisoformat(item['date'])
        except ValueError:
            raise ValueError('seed_history_date_invalid') from None
        if historical_date >= call_date:
            raise ValueError('seed_history_not_prior')
        item = deepcopy(item)
        item['channel'] = 'hotline' if item['channel'] == 'phone' else item['channel']
        if 'facts' in item:
            if not isinstance(item['facts'], list):
                raise ValueError('seed_history_facts_invalid')
            for fact in item['facts']:
                if (not isinstance(fact, dict) or set(fact) - {'field','value','as_of'}
                        or not isinstance(fact.get('field'), str)
                        or not re.fullmatch(r'[a-z][a-z0-9_]{1,63}', fact['field'])
                        or fact['field'] in {'cccd','national_id','bank_account','account_number','cmnd','stk'}
                        or type(fact.get('value')) not in {str,int,float,bool}
                        or isinstance(fact['value'], float) and not math.isfinite(fact['value'])
                        or isinstance(fact['value'], str) and (not fact['value'].strip() or len(fact['value']) > 1000)):
                    raise ValueError('seed_history_facts_invalid')
                if contains_sensitive_pii(fact['value'], field=fact['field']):
                    raise ValueError('seed_history_sensitive_pii')
                from app.constants import SLOT_SPEC_BY_KEY
                spec = SLOT_SPEC_BY_KEY.get(fact['field'])
                if spec:
                    types = spec.value_type if isinstance(spec.value_type, tuple) else (spec.value_type,)
                    if type(fact['value']) not in types:
                        raise ValueError('seed_history_fact_type_invalid')
                if fact['field'] in {'address','shipping_address','interest_sku'} and not isinstance(fact['value'], str):
                    raise ValueError('seed_history_fact_type_invalid')
                try:
                    observed = date.fromisoformat(fact.get('as_of', item['date']))
                except (ValueError, TypeError):
                    raise ValueError('seed_history_fact_date_invalid') from None
                if observed >= call_date:
                    raise ValueError('seed_history_fact_not_prior')
                fact['as_of'] = observed.isoformat()
        sid = item['session_id']
        if sid in result and result[sid] != item:
            raise ValueError('seed_history_conflict')
        result[sid] = deepcopy(item)
    return sorted(result.values(), key=lambda s: (s['date'], s['session_id']))


class SeedHistoryGateway:
    def __init__(self, inner, *, materialize=None):
        self.inner = inner
        self.scenario = None
        self.history = {}
        self.identities = {}
        self.customer_id = None
        self.materialize = materialize
        self.materialized = {}
        self.call_date = None

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def select(self, scenario_id: str, identities: dict, history: list[dict], *, call_date=None):
        if scenario_id != self.scenario:
            self.history, self.customer_id = {}, None
            self.materialized = {}
        self.scenario = scenario_id
        self.call_date = call_date
        self.identities = {key: set(value) if isinstance(value, (list, tuple, set)) else {value}
                           for key, value in identities.items()}
        for item in history:
            sid = item['session_id']
            if sid in self.history and self.history[sid] != item:
                raise ValueError('seed_history_conflict')
            self.history[sid] = deepcopy(item)

    async def prepare_history(self, channel, identity, *, verified_customer_id=None, verified_phone=None):
        if self.materialize is not None and self.history:
            if verified_customer_id and verified_phone:
                await self.invoke_trusted('crm.get_customer', {'phone': verified_phone},
                                          verified_customer_id, channel, identity)
                return
            key = {'hotline': 'phone', 'zalo_oa': 'zalo_id', 'chat_fanpage': 'fb_id'}[channel]
            await self.invoke('crm.get_customer', {key: identity})

    async def invoke(self, name, args):
        result = await self.inner.invoke(name, args)
        return await self._apply_history(name, args, result)

    async def invoke_trusted(self, name, args, customer_id, *context, **kwargs):
        if hasattr(self.inner, 'invoke_trusted'):
            result = await self.inner.invoke_trusted(name, args, customer_id, *context, **kwargs)
        else:
            result = await self.inner.invoke(name, args)
        return await self._apply_history(name, args, result, customer_id)

    async def _apply_history(self, name, args, result, verified_customer_id=None):
        if name != 'crm.get_customer' or not self.history:
            return result
        channel = 'zalo_oa' if 'zalo_id' in args else 'chat_fanpage' if 'fb_id' in args else 'hotline'
        identity = args.get('phone') or args.get('zalo_id') or args.get('fb_id')
        if identity not in self.identities.get(channel, set()):
            return result
        if result.get('ambiguous'):
            if not verified_customer_id:
                return result
            candidates = result.get('candidates', [])
            selected = next((item for item in candidates if item['customer_id'] == verified_customer_id), None)
            if selected is None:
                return result
            with_history = await self._attach_history(selected)
            return {**result, 'candidates': [with_history if item is selected else item for item in candidates]}
        if not result.get('found') or not result.get('customer_id'):
            raise RuntimeError('seed_history_identity_unresolved')
        if verified_customer_id and verified_customer_id != result['customer_id']:
            return result
        return await self._attach_history(result)

    async def _attach_history(self, result):
        if self.customer_id and self.customer_id != result['customer_id']:
            raise RuntimeError('seed_history_identity_conflict')
        self.customer_id = result['customer_id']
        sessions = {s['session_id']: s for s in result.get('sessions', [])}
        for sid, item in self.history.items():
            if sid in sessions and (any(sessions[sid].get(k, 'khac' if k == 'outcome' else None)
                    != item.get(k, 'khac' if k == 'outcome' else None)
                    for k in ('date','summary','outcome'))
                    or ('hotline' if sessions[sid].get('channel') == 'phone' else sessions[sid].get('channel')) != item['channel']):
                raise RuntimeError('seed_history_conflict')
            sessions[sid] = item
        if self.materialize is not None:
            history = sorted(self.history.values(), key=lambda s: (s['date'], s['session_id']))
            key = json.dumps(history, sort_keys=True)
            if key not in self.materialized:
                dates = {'call_date': self.call_date} if self.call_date is not None else {}
                self.materialized[key] = await self.materialize(self.scenario, self.customer_id, deepcopy(history), **dates)
            for original, loaded in zip(history, self.materialized[key], strict=True):
                sessions.pop(original['session_id'], None)
                sessions[loaded['session_id']] = loaded
        return {**result, 'sessions': deepcopy(sorted(sessions.values(), key=lambda s: (s['date'], s['session_id'])))}
