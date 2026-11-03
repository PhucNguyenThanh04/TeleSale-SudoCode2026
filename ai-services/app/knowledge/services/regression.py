"""Draft cases separate task input from reviewer-owned expectations."""
from app.knowledge.schemas import timestamp
import re


def _lexical_rank(query, chunks):
    """Offline review check only; never serves policy.search or a hybrid release."""
    words = set(re.findall(r"\w+", query.casefold()))
    ranked = []
    for chunk in chunks:
        haystack = f"{chunk['title']} {chunk['body']}".casefold()
        score = sum(word in haystack for word in words if len(word) > 1)
        if score:
            ranked.append((chunk['chunk_id'], score))
    return sorted(ranked, key=lambda item: (-item[1], item[0]))


def build_regression_draft(revision):
    return {'id': revision['id'], 'revision_hash': revision['content_hash'],
            'input': {'question': revision['question'], 'on': revision.get('effective_from')},
            'expected': {'source_ids': revision['source_ids'],
                         'answer': revision.get('answer', ''),
                         'must_abstain_without_valid_sources': True},
            'variations': [revision['question']], 'approved': False, 'created_at': timestamp()}


def check_offline_retrieval(revision, case, source_rows):
    """Run cheap retrieval assertions; this does not claim to evaluate the LLM."""
    from app.knowledge.schemas import KnowledgeError
    if not case.get('variations') or not case.get('expected', {}).get('source_ids'):
        raise KnowledgeError('Reviewed test requires variations and source expectations')
    chunks = [dict(r) for r in source_rows if r.get('access_level') == 'public']
    if revision['kind'] == 'faq':
        target = 'KG-'+revision['id']
        chunks.append({'chunk_id': target, 'title': revision['question'], 'body': revision['answer']})
        expected = {target}
    else:
        expected = set(revision['source_ids'])
        for row in chunks:
            if row['chunk_id'] in expected:
                row['title'] += ' '+revision['question']+' '+' '.join(revision['aliases'])
    for variation in case['variations']:
        if not isinstance(variation, str) or not 1 <= len(variation.strip()) <= 8000:
            raise KnowledgeError('Invalid regression variation')
        top = {key for key, _ in _lexical_rank(variation, chunks)[:5]}
        if not top & expected:
            raise KnowledgeError('Offline retrieval check failed; improve content or aliases')
    return {'status': 'passed', 'kind': 'lexical_retrieval', 'n_variations': len(case['variations']),
            'llm_answer_evaluated': False}
