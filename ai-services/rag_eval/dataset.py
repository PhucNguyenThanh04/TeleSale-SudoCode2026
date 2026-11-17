"""BTC inputs and explicit component fixtures; labels never enter runtime input."""
import importlib.util
import json
import shutil
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_CONTEXTS = Path(__file__).parent / 'fixtures/contexts.json'
DEFAULT_ASSERTIONS = Path(__file__).parent / 'fixtures/assertions.json'
TYPES = {'single', 'multi_hop', 'version_conflict', 'unanswerable', 'restricted', 'numeric'}
READ_TOOLS = {'catalog.search': 'catalog_search', 'pricing.get_quote': 'pricing_get_quote',
              'pricing.quote_order': 'pricing_quote_order', 'inventory.check': 'inventory_check'}


class ToolFixture(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str
    args: dict = Field(default_factory=dict)
    owned_sku: str | None = None


class CaseContext(BaseModel):
    model_config = ConfigDict(extra='forbid')
    on: date
    verified_order_date: date | None = None
    customer_reported_order_date: date | None = None
    date_source: str | None = None
    read_tools: list[ToolFixture] = Field(default_factory=list)

    @model_validator(mode='after')
    def provenance(self):
        if self.verified_order_date and not self.date_source:
            raise ValueError('Verified date needs explicit provenance')
        for tool in self.read_tools:
            if tool.name not in READ_TOOLS or any(k.startswith('_') for k in tool.args):
                raise ValueError('Only allowlisted read tool fixtures are accepted')
        return self


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def load_cases(root, context_path=DEFAULT_CONTEXTS):
    questions = read_json(Path(root) / 'rag/qa_labeled.json')['questions']
    seen = set()
    for q in questions:
        if not isinstance(q.get('qid'), str) or not q['qid'] or q['qid'] in seen:
            raise ValueError('Missing or duplicate qid')
        seen.add(q['qid'])
        if (q.get('type') not in TYPES or not isinstance(q.get('question'), str)
                or not q['question'].strip() or not isinstance(q.get('expected_answer'), str)
                or not q['expected_answer'].strip() or not isinstance(q.get('relevant_chunk_ids'), list)
                or any(not isinstance(key, str) or not key for key in q['relevant_chunk_ids'])):
            raise ValueError('Invalid QA labels: ' + q['qid'])
    if not questions:
        raise ValueError('Empty QA dataset')
    config = read_json(context_path)
    if set(config) != {'schema_version', 'description', 'defaults', 'cases'} or config['schema_version'] != 1:
        raise ValueError('Invalid context schema')
    if set(config['cases']) - seen:
        raise ValueError('Context contains unknown qids')
    from app.knowledge.policy.source import HEADING
    source_ids = {key for p in (Path(root) / 'policy').glob('*.md')
                  for key, _ in HEADING.findall(p.read_text(encoding='utf-8'))}
    cases = []
    for q in questions:
        if set(q['relevant_chunk_ids']) - source_ids:
            raise ValueError('Unknown source IDs: ' + q['qid'])
        context = CaseContext.model_validate(config['defaults'] | config['cases'].get(q['qid'], {}))
        cases.append({'qid': q['qid'], 'input': {'query': q['question'],
            **context.model_dump(mode='json', exclude_none=True)},
            'labels': {k: q[k] for k in ('type', 'expected_answer', 'relevant_chunk_ids')}})
    return cases


def freeze_inputs(root, out, context_path=DEFAULT_CONTEXTS, assertions_path=DEFAULT_ASSERTIONS):
    root, out = Path(root), Path(out)
    target = out / 'btc'
    target.mkdir()
    for name in ('rag', 'policy', 'catalog'):
        shutil.copytree(root / name, target / name)
    (target / 'eval').mkdir()
    for name in ('reference_eval.py', 'mock_tools.py'):
        shutil.copy2(root / 'eval' / name, target / 'eval' / name)
    shutil.copy2(context_path, out / 'contexts.json')
    shutil.copy2(assertions_path, out / 'assertions.json')


def load_module(path):
    spec = importlib.util.spec_from_file_location('rag_eval_btc_' + Path(path).stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def safe_tool_value(value):
    if isinstance(value, dict):
        return {k: safe_tool_value(v) for k, v in value.items()
                if not k.startswith('_') and k not in {'customer_phone', 'phone', 'name',
                    'identities', 'address', 'sessions', 'customer_name'}}
    if isinstance(value, list):
        return [safe_tool_value(v) for v in value]
    return value


def reference_observations(root, inputs):
    tools = inputs.get('read_tools', [])
    if not tools:
        return []
    module = load_module(Path(root) / 'eval/mock_tools.py')
    observations = []
    for raw in tools:
        tool = ToolFixture.model_validate(raw)
        if tool.name not in READ_TOOLS or any(k.startswith('_') for k in tool.args):
            raise ValueError('Only allowlisted read tool fixtures are accepted')
        args = dict(tool.args)
        if tool.name != 'catalog.search':
            args['on'] = inputs['on']
        if tool.owned_sku:
            owners = [c for c in module.CRM if any(o.get('sku') == tool.owned_sku
                      and o.get('status') == 'delivered' for o in c.get('orders', []))]
            owner = next((c for c in owners if sum(x['phone'] == c['phone'] for x in module.CRM) == 1), None)
            if owner is None or tool.name not in {'pricing.get_quote', 'pricing.quote_order'}:
                raise ValueError('Reference ownership fixture unavailable')
            args['customer_phone'] = owner['phone']
        result = getattr(module, READ_TOOLS[tool.name])(**args)
        if 'error' in result:
            raise ValueError('Reference read tool fixture failed')
        observations.append({'name': tool.name, 'args': safe_tool_value(args),
            'owned_sku_fixture': tool.owned_sku, 'result': safe_tool_value(result),
            'source': 'frozen_btc_reference_tool'})
    return observations
