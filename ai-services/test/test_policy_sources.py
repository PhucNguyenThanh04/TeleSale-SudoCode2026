import json
import pytest
import re
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


def test_parser_rejects_missing_policy_documents(tmp_path):
    from app.knowledge.policy.source import parse_policy_sources, default_metadata
    with pytest.raises(ValueError, match='documents missing'):
        parse_policy_sources(tmp_path, default_metadata())


def test_every_original_section_is_served_or_explicitly_excluded():
    from app.knowledge.policy.source import parse_policy_sources, default_metadata, HEADING
    root = btc_data_dir() / 'policy'
    raw = [h[0] for p in root.glob('*.md') for h in HEADING.findall(p.read_text())]
    served = {c.chunk_id for c in parse_policy_sources(root, default_metadata())}
    excluded = {'NB-04', *{f'NQ-0{i}' for i in range(1, 6)}}
    assert len(raw) == len(set(raw)) == 99
    assert served.isdisjoint(excluded)
    assert served | excluded == set(raw)


def test_chunk_keeps_document_prelude_title_table_and_notes(tmp_path):
    from app.knowledge.policy.source import parse_policy_sources, content_hash
    prelude = '# Document\n\nApplies to old orders too.'
    body = '| Size | cm |\n|---|---|\n| 38 | 24 |\n| 39 | 25 |\nNote: use catalog.'
    text = prelude + '\n\n## [XX-01] Sizes\n' + body + '\n\n## [XX-02] Other\nOther content.'
    (tmp_path/'source.md').write_text(text)
    meta = {'documents': {'source.md': dict(access='public', version='v1', date_basis='on',
                                         effective_from=None, effective_until=None)}}
    a, b = parse_policy_sources(tmp_path, meta)
    assert a.content == prelude + '\n\nSizes\n' + body
    assert 'Other content' not in a.content and body not in b.content
    assert a.source_hash == content_hash(body)
    assert a.content_hash == content_hash(a.content)
    assert a.source['document_hash'] == content_hash(text)
    assert a.chunk_id == a.section_id == 'XX-01'


def test_declared_section_cannot_silently_disappear(tmp_path):
    from app.knowledge.policy.source import parse_policy_sources
    (tmp_path/'source.md').write_text('## [XX-01] First\nContent')
    meta = {'documents': {'source.md': dict(access='public', version='v1', date_basis='on',
                                         effective_from=None, effective_until=None)},
            'sections': {'XX-02': {'required_context': ['product']}}}
    with pytest.raises(ValueError, match='sections missing'):
        parse_policy_sources(tmp_path, meta)


@pytest.mark.parametrize('text,reason', [
    ('## [XX-01] First\nA\n## [XX-01] Duplicate\nB', 'Duplicate'),
    ('## [XX-01] Empty\n', 'Empty'),
])
def test_invalid_section_boundaries_fail(tmp_path, text, reason):
    from app.knowledge.policy.source import parse_policy_sources
    (tmp_path/'source.md').write_text(text)
    meta = {'documents': {'source.md': dict(access='public', version='v1', date_basis='on',
                                         effective_from=None, effective_until=None)}}
    with pytest.raises(ValueError, match=reason):
        parse_policy_sources(tmp_path, meta)


def test_explicit_document_versions_match_btc_headers():
    from app.knowledge.policy.source import default_metadata
    meta = default_metadata()
    for name in ['chinh-sach-bao-hanh.md', 'chinh-sach-van-chuyen-thanh-toan.md', 'faq.md']:
        header = (btc_data_dir()/'policy'/name).read_text().splitlines()[0]
        assert '(phiên bản 2026-10)' in header
        assert meta['documents'][name]['version'] == '2026-10'


def test_safe_transformations_do_not_copy_restricted_details():
    from app.knowledge.policy.source import parse_policy_sources, default_metadata
    rows = {c.chunk_id:c for c in parse_policy_sources(btc_data_dir()/'policy', default_metadata())}
    assert '19/10/2026' in rows['NB-02'].content and '200 máy' not in rows['NB-02'].content
    assert 'nhà cung cấp chậm' not in rows['NB-02'].content.lower()
    for key in ['NB-01', 'NB-03']:
        assert rows[key].transformation == 'disclosure_limit'
        assert not re.search(r'\d', rows[key].content)
    assert not re.search(r'\b(?:80|90)%', rows['KM-06'].content)
    assert {'PB-01', 'PB-06', 'PB-11'} <= rows.keys()
