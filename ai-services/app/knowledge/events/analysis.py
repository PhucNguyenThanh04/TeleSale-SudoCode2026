import re
from app.knowledge.schemas import CATEGORIES, KnowledgeError


async def analyze_event(evidence, source_catalog, model=None):
    public = [s for s in source_catalog if s.get('access_level') == 'public']
    words = set(re.findall(r'\w+', evidence['question'].lower()))
    ranked = sorted(public, key=lambda s: -len(words & set(re.findall(r'\w+',
                    (s.get('title', '')+' '+s.get('body', '')).lower()))))
    matches = [s for s in ranked if len(words & set(re.findall(r'\w+',
                       (s.get('title', '')+' '+s.get('body', '')).lower()))) >= 2][:5]
    signal = evidence.get('signal', '')
    category = 'technical' if signal in {'tool_timeout', 'degraded_lexical', 'mcp_unavailable', 'execution_unverified'} else 'insufficient_evidence'
    if signal == 'no_evidence' and matches:
        category = 'retrieval'
    if signal == 'correct_refusal':
        category = 'correct_refusal'
    result = {'category': category, 'title': evidence['question'][:160],
              'suggested_source_ids': [s['chunk_id'] for s in matches],
              'source_review': 'Full public corpus searched; reviewer must verify applicability.'}
    if model:
        result = await model(evidence, matches)
    if not isinstance(result, dict) or result.get('category') not in CATEGORIES:
        raise KnowledgeError('Invalid analysis output')
    if (not isinstance(result.get('title'), str) or len(result['title']) > 160
            or not isinstance(result.get('suggested_source_ids', []), list)):
        raise KnowledgeError('Invalid analysis fields')
    allowed = {s['chunk_id'] for s in public}
    if not set(result.get('suggested_source_ids', [])) <= allowed:
        raise KnowledgeError('Analysis cited an unauthorized source')
    return {k: result.get(k) for k in ('category', 'title', 'suggested_source_ids', 'source_review')}
