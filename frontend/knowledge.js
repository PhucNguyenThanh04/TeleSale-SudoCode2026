(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const node = (tag, text) => { const n = document.createElement(tag); if (text != null) n.textContent = text; return n; };
  const visitor = location.hostname === 'telesale.ktoxz.id.vn';
  if (visitor) $('knowledge-nav').hidden = true;
  let offset = 0, total = 0, active = null, selected = null;
  const status = text => { $('knowledge-status').textContent = text; };
  async function api(path, body) {
    const response = await fetch('/api/knowledge/' + path, {credentials: 'same-origin',
      method: body ? 'POST' : 'GET', headers: body ? {'Content-Type': 'application/json'} : {},
      body: body ? JSON.stringify(body) : undefined});
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : `Yêu cầu thất bại (${response.status})`);
    return result;
  }
  function button(parent, text, fn) {
    const b = node('button', text); b.type = 'button';
    b.addEventListener('click', async () => { b.disabled = true; try { await fn(); } catch (e) { status(e.message); } finally { b.disabled = false; } });
    parent.append(b); return b;
  }
  function field(parent, label, value = '', multiline = false) {
    const wrap = node('label', label); const input = node(multiline ? 'textarea' : 'input');
    input.value = value || ''; wrap.append(input); parent.append(wrap); return input;
  }
  function select(parent, label, values, value) {
    const wrap = node('label', label), input = node('select');
    for (const [key, text] of values) { const o = node('option', text); o.value = key; input.append(o); }
    input.value = value; wrap.append(input); parent.append(wrap); return input;
  }
  async function cmd(action, payload) {
    const result = await api('commands', {action, payload});
    status('Đã lưu.'); return result;
  }
  async function get(resource, id) { return (await api(resource + '?item_id=' + encodeURIComponent(id))).items[0]; }
  async function refresh() {
    if (visitor) return;
    try {
      const identity = await api('identity'); $('knowledge-actor').textContent = 'Danh tính nội bộ: ' + identity.actor_id;
      const resource = $('knowledge-resource').value;
      const params = new URLSearchParams({offset, limit: 30});
      if ($('knowledge-filter-status').value) params.set('status', $('knowledge-filter-status').value);
      if ($('knowledge-filter-source').value) params.set('source', $('knowledge-filter-source').value);
      const result = await api(resource + '?' + params);
      active = result.active_release_id; total = result.total;
      $('knowledge-active').textContent = 'Đang phục vụ: ' + (active || 'Chỉ nguồn BTC');
      $('knowledge-list').replaceChildren();
      for (const row of result.items) {
        const b = button($('knowledge-list'), `${row.title || row.question || row.id} · ${row.status || row.source || ''}`, () => show(resource, row));
        b.className = 'call-card';
      }
      $('knowledge-prev').disabled = offset === 0; $('knowledge-next').disabled = offset + 30 >= total;
      status(`${offset + 1 > total ? 0 : offset + 1}–${Math.min(offset + 30, total)} / ${total} mục`);
    } catch (e) { status(e.message); }
  }
  async function show(resource, row) {
    selected = row; const detail = $('knowledge-detail'); detail.replaceChildren(node('h3', row.title || row.question || row.id));
    const raw = node('details'); raw.append(node('summary', 'Bằng chứng và metadata'), node('pre', JSON.stringify(row, null, 2))); detail.append(raw);
    if (resource === 'gaps' && row.status !== 'erased') {
      for (const id of row.event_ids || []) { const e = await get('events', id); if (e) detail.append(node('p', `Khách: ${e.question || ''}\nAgent: ${e.answer || ''}\nPhản ánh: ${e.reason || e.signal || ''}`)); }
      const category = select(detail, 'Nguyên nhân', [['content','Thiếu nội dung'],['retrieval','Khó truy hồi'],['source_conflict','Nguồn mâu thuẫn'],['generation','Lỗi diễn giải'],['technical','Lỗi kỹ thuật'],['correct_refusal','Từ chối đúng'],['insufficient_evidence','Chưa đủ bằng chứng']], row.category);
      const reason = field(detail, 'Lý do phân loại', row.reason, true);
      button(detail, 'Lưu phân loại', async () => { await cmd('classify', {id: row.id, version: row.version, category: category.value, reason: reason.value}); await refresh(); await show('gaps', await get('gaps', row.id)); });
      const other = field(detail, 'Mã vấn đề cần gộp vào mục này');
      button(detail, 'Gộp vấn đề', async () => { await cmd('merge', {id: row.id, version: row.version, other_id: other.value}); await refresh(); });
      const split = field(detail, 'Mã feedback cần tách (mỗi dòng một mã)', '', true);
      button(detail, 'Tách thành vấn đề mới', async () => { await cmd('split', {id: row.id, version: row.version, event_ids: split.value.split(/\s+/).filter(Boolean)}); await refresh(); });
      revisionEditor(detail, row.id);
      if (row.draft_revision_id) button(detail, 'Mở bản nháp từ worker', async () => show('revisions', await get('revisions', row.draft_revision_id)));
      if (row.status === 'awaiting_verification') {
        const verification = field(detail, 'Mã báo cáo xác minh đã đăng ký');
        const resolution = field(detail, 'Bằng chứng vấn đề đã được giải quyết', '', true);
        button(detail, 'Xác nhận đã giải quyết', async () => { await cmd('verify_gap', {id: row.id, version: row.version, verification_run_id: verification.value, reason: resolution.value, resolved: true}); await refresh(); });
      }
    }
    if (resource === 'revisions' && row.status !== 'erased') {
      revisionEditor(detail, row.gap_id, row);
      const test = await get('regression_cases', row.id);
      detail.append(node('h4', 'Test cần kiểm tra trước khi duyệt'), node('pre', JSON.stringify(test, null, 2)));
      const expected = field(detail, 'Đáp án kỳ vọng của người duyệt', test?.expected?.answer || '', true);
      const variations = field(detail, 'Cách hỏi kiểm thử (mỗi dòng một câu)', (test?.variations || []).join('\n'), true);
      button(detail, 'Lưu chỉnh sửa test thành bản nháp mới', async () => {
        const result = await cmd('edit_test', {id: row.id, test_hash: await hash(test), expected: {answer: expected.value}, variations: variations.value.split('\n').filter(Boolean)});
        await show('revisions', result);
      });
      const label = node('label', 'Tôi đã kiểm tra nội dung, nguồn và toàn bộ kỳ vọng test'); const checked = node('input'); checked.type = 'checkbox'; label.prepend(checked); detail.append(label);
      const reason = field(detail, 'Lý do quyết định', '', true);
      button(detail, 'Duyệt nội dung và test', async () => { if (!checked.checked) throw new Error('Cần xác nhận đã kiểm tra test.'); await cmd('approve', {id: row.id, content_hash: row.content_hash, approve_test: true, reason: reason.value}); await refresh(); await show('revisions', await get('revisions', row.id)); });
      button(detail, 'Từ chối', async () => { await cmd('reject', {id: row.id, content_hash: row.content_hash, reason: reason.value}); await refresh(); });
      button(detail, 'Thêm mã vào danh sách phát hành', () => { const values = new Set($('knowledge-release-items').value.split('\n').filter(Boolean)); values.add(row.id); $('knowledge-release-items').value = [...values].join('\n'); });
    }
    if (resource === 'releases' && row.status === 'ready') {
      button(detail, 'Phát hành phiên bản này', async () => { await cmd('activate_release', {id: row.id, expected_active_id: active}); await refresh(); });
      button(detail, 'Khôi phục phiên bản này', async () => { await cmd('rollback_release', {id: row.id, expected_active_id: active}); await refresh(); });
    }
    if (resource === 'backend_outbox' && row.status === 'failed') button(detail, 'Gửi lại feedback', async () => { await cmd('retry_outbox', {id: row.id}); await refresh(); });
    if (resource === 'jobs' && row.status === 'failed') button(detail, 'Thử phân tích lại', async () => { await cmd('retry_job', {id: row.id}); await refresh(); });
    if (resource === 'regression_cases') button(detail, 'Tải test', () => download('regression-' + row.id + '.json', row));
  }
  function revisionEditor(parent, gapId, row = null) {
    const box = node('fieldset'); box.append(node('legend', row ? 'Chỉnh sửa thành bản nháp mới' : 'Đề xuất bản sửa')); parent.append(box);
    const kind = select(box, 'Loại nội dung', [['faq','FAQ có nguồn'],['aliases','Cách hỏi bổ sung']], row?.kind || 'faq');
    const question = field(box, 'Câu hỏi', row?.question, true), answer = field(box, 'Câu trả lời FAQ', row?.answer, true);
    const aliases = field(box, 'Cách hỏi bổ sung (mỗi dòng một câu)', (row?.aliases || []).join('\n'), true);
    const ids = field(box, 'Mã chunk nguồn (cách nhau dấu phẩy)', (row?.source_ids || []).join(', '));
    const scope = field(box, 'Phạm vi sản phẩm và điều kiện', row?.scope, true);
    const review = field(box, 'Kết quả rà soát nguồn và phạm vi hiệu lực', row?.source_review_note, true);
    button(box, 'Lưu bản nháp', async () => {
      const changes = {kind: kind.value, question: question.value, answer: answer.value, aliases: aliases.value.split('\n').filter(Boolean), source_ids: ids.value.split(',').map(v => v.trim()).filter(Boolean), scope: scope.value, source_review_note: review.value};
      const result = await cmd(row ? 'edit_revision' : 'create_revision', row ? {id: row.id, content_hash: row.content_hash, changes} : {gap_id: gapId, ...changes});
      await show('revisions', result);
    });
  }
  async function hash(value) {
    // Python's canonical digest is returned by the API; no browser JSON ordering assumptions.
    if (!value?.record_hash) throw new Error('Hãy làm mới test để lấy mã phiên bản.');
    return value.record_hash;
  }
  function download(name, value) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type: 'application/json'}));
    const a = node('a'); a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url);
  }
  function attachFeedback(parent, session, turn) {
    if (visitor || !session) return;
    const box = node('details'); box.append(node('summary', 'Đánh giá câu trả lời'));
    const rating = select(box, 'Đánh giá', [['false','Cần sửa'],['true','Hữu ích']], 'false');
    const reason = field(box, 'Lý do', '', true), correction = field(box, 'Đề nghị sửa (nếu có)', '', true);
    let key = crypto.randomUUID(), previousPayload = '';
    button(box, 'Gửi phản ánh', async () => {
      const content = JSON.stringify([rating.value, reason.value, correction.value]);
      if (previousPayload && previousPayload !== content) key = crypto.randomUUID();
      previousPayload = content;
      await api('feedback', {session_id: session, turn_no: turn, rating: rating.value === 'true', reason: reason.value, correction: correction.value, idempotency_key: key});
      const receipt = node('p', 'Đã lưu phản ánh, đang chờ phân tích.'); box.append(receipt);
    }); parent.append(box);
  }
  $('knowledge-refresh').addEventListener('click', () => { offset = 0; refresh(); });
  $('knowledge-resource').addEventListener('change', () => { offset = 0; refresh(); });
  $('knowledge-prev').addEventListener('click', () => { offset = Math.max(0, offset - 30); refresh(); });
  $('knowledge-next').addEventListener('click', () => { offset += 30; refresh(); });
  button($('knowledge-release-items').parentElement, 'Kiểm tra quyền và làm mới', refresh);
  button($('knowledge-release-items').parentElement, 'Khôi phục chỉ nguồn BTC', async () => { await cmd('rollback_release', {id: 'btc-only', expected_active_id: active}); await refresh(); });
  $('knowledge-prepare').addEventListener('click', async event => {
    event.target.disabled = true;
    try { const result = await cmd('prepare_release', {revision_ids: $('knowledge-release-items').value.split(/\s+/).filter(Boolean), expected_active_id: active}); await show('releases', result); }
    catch (e) { status(e.message); } finally { event.target.disabled = false; }
  });
  window.TeleSaleKnowledge = {refresh, attachFeedback};
})();
