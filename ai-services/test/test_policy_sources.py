import json
import pytest
from btc_data import btc_data_dir


def test_all_btc_sections_are_accounted_for_and_safe():
    from app.knowledge.policy.source import parse_policy_sources, default_metadata
    chunks = parse_policy_sources(btc_data_dir() / 'policy', default_metadata())
    ids = {c.chunk_id for c in chunks}
    assert len(ids) == 93  # 99 original sections, five administrative + NB-04 excluded.
    assert 'NQ-01' not in ids and 'NB-04' not in ids
    assert {'NB-01', 'NB-02', 'NB-03', 'PB-06', 'KM-06'} <= ids
    rows = {c.chunk_id: c for c in chunks}
    assert '19/10/2026' in rows['NB-02'].content
    assert '90%' not in rows['KM-06'].content
    assert '80%' not in rows['KM-06'].content
    assert rows['NB-01'].evidence_type == 'disclosure_limit'
    assert rows['PB-06'].evidence_type == 'handoff_guidance'
    assert '|' in rows['SP-AIR-01'].content
    assert all(c.source_hash and c.content_hash and c.source['location'] for c in chunks)
    assert 'NOI-BO' not in json.dumps([c.source for c in chunks])


def test_parser_rejects_unclassified_sections_and_dangling_links(tmp_path):
    from app.knowledge.policy.source import parse_policy_sources
    (tmp_path/'source.md').write_text('# Test\n\n## [XX-01] Rule\nA rule')
    with pytest.raises(ValueError, match='metadata'):
        parse_policy_sources(tmp_path, {'documents': {}})
    metadata = {'documents': {'source.md': {'version': 'v1', 'date_basis': 'on',
        'effective_from': None, 'effective_until': None, 'access': 'public'}},
        'sections': {'XX-01': {'required_links': ['MISSING-01']}}}
    with pytest.raises(ValueError, match='link'):
        parse_policy_sources(tmp_path, metadata)
