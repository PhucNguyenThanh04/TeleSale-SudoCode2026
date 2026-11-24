from copy import deepcopy
from datetime import date
import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from app.constants import TOOL_ONLY_SLOT_KEYS
from app.mcp_servers.mcp_shared.pii import mask_pii


class SeedMemoryLoader:
    def __init__(self, repo, projector, extract, *, catalog=()):
        self.repo, self.projector, self.extract = repo, projector, extract
        self.extracted = {}
        self.catalog = catalog

    async def __call__(self, scenario_id, customer_id, history, *, call_date=None):
        from eval_harness.seed_history import parse_seed_history
        from datetime import timedelta
        latest = max(date.fromisoformat(value) for h in history
                     for value in [h['date'], *[f.get('as_of', h['date']) for f in h.get('facts', [])]])
        history = parse_seed_history(history, call_date=call_date or latest + timedelta(days=1))
        prepared = []
        raw_summaries = {}
        for item in history:
            sid = str(uuid5(NAMESPACE_URL, f'btc-seed:{scenario_id}:{customer_id}:{item["session_id"]}'))
            raw_summaries[sid] = item['summary']
            summary = mask_pii(item['summary'])
            for fact in item.get('facts', []):
                if fact['field'] in {'address', 'shipping_address', 'phone', 'customer_phone'}:
                    summary = summary.replace(str(fact['value']), '[PII ĐÃ ẨN]')
            item['summary'] = summary
            tid = str(uuid5(NAMESPACE_URL, sid + ':summary'))
            turn = {'turn_id': tid, 'customer_id': customer_id, 'session_id': sid,
                    'on': item['date'], 'customer_text': mask_pii(item['summary']), 'agent_text': ''}
            explicit = item.get('facts') or []
            if explicit:
                facts = [{'key': 'product_advised' if f['field'] == 'interest_sku' else f['field'],
                          'value': f['value'], 'on': f['as_of'],
                          'source_kind': 'tool' if f['field'] in TOOL_ONLY_SLOT_KEYS or f['field'] in {'interest_sku','product_advised'} else 'customer',
                          'source_tool': 'crm.get_customer', 'evidence_quote': mask_pii(item['summary'])[:200]}
                         for f in explicit]
            else:
                from app.mcp_servers.mcp_memory.services.langmem_admission import admit_profile_candidates
                cache_key = (sid, hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest())
                if cache_key not in self.extracted:
                    self.extracted[cache_key] = await self.extract([{'role': 'user', 'content': json.dumps(
                        {'customer_id': customer_id, 'session_id': sid, 'source_turn_id': tid,
                         'on': item['date'], 'customer_text': turn['customer_text'], 'agent_text': ''}, ensure_ascii=False)}], [])
                candidates, _ = self.extracted[cache_key]
                admitted, _ = admit_profile_candidates(customer_id, sid, candidates, [turn], [])
                from eval_harness.reference_adapter import _spoken_fact
                from app.mcp_servers.mcp_shared.commerce_entities import resolve_claim_skus
                commercial = {'product_advised', 'variant_sku', 'price_quoted_vnd', 'promo_code', 'promo_expiry', 'in_stock'}
                for candidate in candidates:
                    quote = candidate.evidence_quote
                    if (candidate.key not in commercial or candidate.op == 'delete'
                            or candidate.source_turn_id != tid or candidate.observed_on.isoformat() != item['date']
                            or not quote or quote not in turn['customer_text']):
                        continue
                    supported = _spoken_fact(candidate.key, candidate.value, quote)
                    if candidate.key in {'product_advised', 'variant_sku'}:
                        supported = supported or candidate.value in resolve_claim_skus(quote, [
                            {'name': 'catalog.search', 'args': {}, 'result': {'items': list(self.catalog)}}])
                    if supported:
                        admitted.append({'key': candidate.key, 'value': candidate.value, 'op': 'set',
                            'source_kind': 'tool', 'source_tool': 'crm.get_customer', 'evidence_quote': quote})
                facts = [{**f, 'on': item['date']} for f in admitted if f['op'] != 'delete']
            prepared.append((item, sid, tid, facts))
        newest = {}
        for item, sid, tid, facts in prepared:
            for fact in facts:
                key = (fact.get('scope_type', 'global'), fact.get('scope_id', ''), fact['key'])
                previous = newest.get(key)
                if previous and previous[0]['on'] == fact['on'] and previous[0]['value'] != fact['value']:
                    raise ValueError('seed_history_fact_conflict')
                if previous is None or previous[0]['on'] < fact['on']:
                    newest[key] = (fact, sid, tid)
        async with self.repo.transaction() as conn:
            await self.repo.lock_key(conn, f'erasure:{customer_id}')
            if await self.repo.is_erasure_blocked(conn, customer_id):
                raise RuntimeError('seed_history_customer_erased')
            await self.repo.lock_key(conn, f'langmem:{customer_id}')
            existing = {(f.get('scope_type', 'global'), f.get('scope_id', ''), f['key']): f
                        for f in await self.projector.list_facts(customer_id)}
            for item, sid, tid, facts in prepared:
                operation = f'btc-seed:{sid}'
                digest = hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                previous = await self.repo.claim_operation(conn, operation, digest)
                if previous is not None:
                    if previous.get('error'):
                        raise ValueError('seed_history_conflict')
                    continue
                from app.mcp_servers.mcp_shared.pii import private_delivery_context
                delivery_id = str(uuid5(NAMESPACE_URL, sid + ':address'))
                addresses = [f for f in facts if f['key'] in {'address', 'shipping_address'}]
                address = max(addresses, key=lambda f: f['on'], default=None)
                delivery = ({'address': address['value'], 'source_turn_id': delivery_id,
                    'source_on': address['on'], 'source_customer_text': mask_pii(item['summary'])}
                    if address else private_delivery_context(raw_summaries[sid], delivery_id, item['date']))
                if delivery:
                    from eval_harness.trace_evidence import contains_sensitive_pii
                    if contains_sensitive_pii(delivery['address']):
                        raise ValueError('seed_history_sensitive_pii')
                    await self.repo.insert_turn(conn, sid, 1, customer_id, item['channel'],
                        date.fromisoformat(delivery['source_on']), mask_pii(item['summary']), '', delivery_id,
                        private_delivery=delivery)
                await self.repo.insert_turn(conn, sid, 2 if delivery else 1, customer_id, item['channel'],
                    date.fromisoformat(item['date']), mask_pii(item['summary']), '', tid, [], item.get('outcome', 'khac'))
                await self.projector.put_episode(customer_id, sid, {'on_date': item['date'],
                    'channel': item['channel'], 'summary': mask_pii(item['summary']),
                    'outcome': item.get('outcome', 'khac')}, revision=0)
                await self.repo.finish_operation(conn, operation, {'seeded': True})
            for key, (fact, sid, tid) in newest.items():
                previous = existing.get(key)
                if previous and (previous.get('revision', 0) > 0 or previous.get('on', '') > fact['on']):
                    continue
                if previous and previous.get('on') == fact['on']:
                    expected = mask_pii(fact['value']) if isinstance(fact['value'], str) else fact['value']
                    if previous.get('value') != expected:
                        raise ValueError('seed_history_fact_conflict')
                    continue
                value = deepcopy(fact)
                value.update(op='set', source_kind=fact.get('source_kind', 'tool'))
                if value['source_kind'] == 'tool':
                    value['source_tool'] = value.get('source_tool', 'crm.get_customer')
                await self.projector.put_facts(customer_id, sid, tid, fact['on'], [value], revision=0)
        return [{k: v for k, v in {**item, 'session_id': sid}.items() if k != 'facts'}
                for item, sid, _, _ in prepared]


def build_seed_loader(settings, btc_root):
    from app.infarstructure.llm import build_llm
    from app.agent.memory.langmem_extractor import extract_candidates
    from app.mcp_servers.mcp_shared.config import database_url
    from app.mcp_servers.mcp_memory.repos.postgres import MemoryRepo
    from app.mcp_servers.mcp_memory.repos.langmem_projection import LangMemProjection
    dsn = database_url(settings)
    model = build_llm(settings.model_copy(update={'llm_model': settings.langmem_model or settings.llm_model}))
    async def extract(turns, existing):
        return await extract_candidates(model, turns, existing)
    from pathlib import Path
    catalog = json.loads((Path(btc_root) / 'catalog/products.json').read_text())['products']
    return SeedMemoryLoader(MemoryRepo(dsn), LangMemProjection(dsn), extract, catalog=catalog)
