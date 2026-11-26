import asyncio
from datetime import date

import pytest

from test_policy_rules import chunk
from test_policy_search import search_fixture, request_context


@pytest.mark.parametrize('case', ['chain', 'cycle', 'missing', 'limit', 'two_hits'])
def test_dependency_closure_is_bounded_complete_and_preserves_unknowns(case):
    async def run():
        def source(key, links):
            return chunk(chunk_id=key, section_id=key, required_links=links,
                         effective_from='2033-01-01')
        first = source('RULE-81', ['RULE-92'])
        second = source('RULE-92', ['RULE-103'])
        third = source('RULE-103', ['RULE-81'] if case == 'cycle' else [])
        rows = [first, second, third]
        hits = [first]
        expected = ['RULE-81', 'RULE-92']
        missing = 'RULE-103'
        if case not in {'missing', 'limit'}:
            expected.append('RULE-103')
        if case == 'missing':
            rows.pop()
        if case == 'limit':
            rows = [source(f'RULE-L{i}', [f'RULE-L{i+1}'] if i < 10 else []) for i in range(11)]
            hits = rows[:1]
            expected = [row.chunk_id for row in rows[:10]]
            missing = 'RULE-L10'
        if case == 'two_hits':
            extra = source('RULE-204', [])
            rows.append(extra)
            hits.append(extra)
            expected.append('RULE-204')
        service, _, _ = await search_fixture(rows, hits=hits)
        request, context = request_context(2 if case == 'two_hits' else 1)
        request = request.model_copy(update={'on': date(2033, 5, 10)})
        context = context.model_copy(update={'on': request.on,
            'verified_order_date': date(2033, 4, 1)})
        try:
            result = await service.search(request, context)
        finally:
            await service.close()
        assert [row.chunk_id for row in result.evidence] == expected
        assert result.evidence_set.required_dependencies_complete == (case not in {'missing', 'limit'})
        if case in {'missing', 'limit'}:
            assert result.evidence_set.missing_required_section_ids == [missing]
            assert all(row.applicability.status == 'conditional' for row in result.evidence)
            assert result.evidence[0].applicability.missing_required_section_ids == [missing]
    asyncio.run(run())
