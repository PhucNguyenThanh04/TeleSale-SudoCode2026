"""Parse BTC sections into safe serving snapshots, independent of QA labels."""
import hashlib
import json
import re
from pathlib import Path

from app.knowledge.schemas import SourceChunk

HEADING = re.compile(r'^## \[([A-Z]+(?:-[A-Z]+)*-\d+)\]\s*(.+)$', re.M)
CONTEXT_KEYS = {'order_date', 'product', 'region', 'purchase_conditions', 'source_confirmation', 'inventory'}


def content_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def default_metadata():
    return json.loads(Path(__file__).with_name('metadata.json').read_text(encoding='utf-8'))


def _safe_body(body, transformation):
    if transformation == 'identity':
        return body
    if transformation == 'disclosure_limit':
        return 'Thông tin giá nhập, biên lợi nhuận và nhà cung cấp là nội bộ, không được cung cấp cho khách.'
    if transformation == 'discount_authority':
        # The authority rule is public; the embedded internal floor percentages are not.
        return ('Nhân viên/agent không được tự giảm giá ngoài các chương trình đã công bố. '
                'Yêu cầu giảm thêm cho đơn số lượng lớn (từ 3 sản phẩm cùng loại) phải '
                'chuyển quản lý duyệt; agent không hứa mức giảm.')
    if transformation == 'restock_dates':
        safe = re.sub(r'\([^)]*\)', '', body)
        safe = re.sub(r'nhà cung cấp chậm,\s*', '', safe, flags=re.I)
        # Keep the public dates/subjects only, never inventory quantities or vendors.
        return safe + '\nNgày dự kiến đã qua không xác nhận đã có hàng; kiểm tra inventory.check.'
    raise ValueError('Unknown safe transformation')


def parse_policy_sources(directory: Path, metadata: dict) -> list[SourceChunk]:
    chunks = []
    seen = set()
    for path in sorted(directory.glob('*.md')):
        document = metadata.get('documents', {}).get(path.name)
        if not document or not {'date_basis', 'effective_from', 'effective_until', 'access', 'version'} <= document.keys():
            raise ValueError('Required document metadata missing')
        text = path.read_text(encoding='utf-8')
        headings = list(HEADING.finditer(text))
        if not headings:
            raise ValueError('Missing BTC sections')
        prelude = text[:headings[0].start()].strip()
        for index, heading in enumerate(headings):
            section_id, title = heading.groups()
            if section_id in seen:
                raise ValueError('Duplicate section ID')
            seen.add(section_id)
            rules = document | metadata.get('sections', {}).get(section_id, {})
            if rules['access'] == 'excluded':
                continue
            raw = text[heading.end():headings[index+1].start() if index+1 < len(headings) else len(text)].strip()
            transformation = rules.get('transformation', 'identity')
            if rules['access'] != 'public' and transformation == 'identity':
                raise ValueError('Unsafe section metadata')
            if not raw:
                raise ValueError('Empty section')
            required = rules.get('required_context', [])
            if not set(required) <= CONTEXT_KEYS:
                raise ValueError('Unknown required context metadata')
            safe = _safe_body(raw, transformation)
            if rules['access'] == 'public' and transformation == 'identity':
                safe = prelude + '\n\n' + title + '\n' + safe
            else:
                safe = rules.get('public_title', section_id) + '\n' + safe
            source = {'file': path.name if rules['access'] == 'public' else f'policy/{section_id}',
                      'version': rules['version'], 'document_hash': content_hash(text), 'location': f'line:{text.count(chr(10), 0, heading.start())+1}'}
            chunks.append(SourceChunk(chunk_id=section_id, section_id=section_id,
                document_id=path.name if rules['access'] == 'public' else f'safe-{section_id}',
                content=safe, source=source, source_hash=content_hash(raw),
                content_hash=content_hash(safe), transformation=transformation,
                date_basis=rules['date_basis'], effective_from=rules['effective_from'],
                effective_until=rules['effective_until'], evidence_type=rules.get('evidence_type','business_rule'),
                required_context=required, required_links=rules.get('required_links', []),
                rules=rules.get('rules', []), conflict=rules.get('conflict', False)))
    ids = {chunk.chunk_id for chunk in chunks}
    if any(set(chunk.required_links)-ids for chunk in chunks):
        raise ValueError('Dangling required link')
    return chunks
