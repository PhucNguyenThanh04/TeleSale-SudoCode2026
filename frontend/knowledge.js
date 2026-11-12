const $ = id => document.getElementById(id);
const categories = {content:'Thiếu nội dung', retrieval:'Truy xuất chưa đúng', source_conflict:'Nguồn mâu thuẫn', generation:'Lỗi sinh câu trả lời', technical:'Lỗi kỹ thuật', correct_refusal:'Từ chối đúng', insufficient_evidence:'Chưa đủ bằng chứng'};
const statuses = {new:'Mới phát hiện', triaged:'Đã phân loại', waiting_for_source:'Chờ nguồn', technical_followup:'Xử lý kỹ thuật', closed_correct_refusal:'Từ chối đúng', awaiting_verification:'Chờ kiểm chứng', resolved:'Đã giải quyết', draft:'Bản nháp', approved:'Đã duyệt', rejected:'Đã từ chối', ready:'Sẵn sàng'};
let offset = 0, active = null, tab = 'gaps', generation = 0, busy = false;
const selectedRevisions = new Map();
function el(tag, text, cls) { const node = document.createElement(tag); if (text != null) node.textContent = text; if (cls) node.className = cls; return node; }
function badge(value) { return el('span', statuses[value] || categories[value] || value || 'Chưa có', 'badge' + (['technical','generation','technical_followup','insufficient_evidence','waiting_for_source'].includes(value) ? ' warn' : '')); }
function note(parent, text, warning = false) { parent.append(el('p', text, 'subtle-note' + (warning ? ' warning-note' : ''))); }
function field(form, title, value = '', type = 'textarea', required = true) {
  const label = el('label', title); const input = document.createElement(type === 'textarea' ? 'textarea' : 'input');
  if (type !== 'textarea') input.type = type;
  input.value = value ?? ''; input.required = required; if (type !== 'checkbox') input.maxLength = 8000;
  label.append(input); form.append(label); return input;
}
function select(form, title, options, value) {
  const label = el('label', title), input = document.createElement('select');
  for (const [key, text] of Object.entries(options)) { const option = el('option', text); option.value = key; input.append(option); }
  input.value = value; label.append(input); form.append(label); return input;
}
function check(parent, title) { const label = el('label', null, 'check-label'), input = document.createElement('input'); input.type = 'checkbox'; label.append(input, el('span', title)); parent.append(label); return input; }
function button(parent, text, action, cls = '') { const b = el('button', text, cls); b.type = 'button'; b.addEventListener('click', () => perform(action)); parent.append(b); return b; }
function details(parent, title, value) { const d = el('details'); d.append(el('summary', title), el('pre', typeof value === 'string' ? value : JSON.stringify(value, null, 2))); parent.append(d); return d; }
function notice(text) { $('notice').textContent = text; }
function showError(error) {
  const messages = {401:'Gateway không xác thực được với AI service. Kiểm tra token nội bộ của server.',403:'Reviewer chưa có quyền duyệt hoặc yêu cầu khác origin bị từ chối.',409:'Dữ liệu đã thay đổi. Hãy làm mới và kiểm tra lại trước khi lưu.',422:'Nội dung chưa hợp lệ. Kiểm tra nguồn, phạm vi hiệu lực, lý do, test đã duyệt và trạng thái release.',503:'Chưa cấu hình dịch vụ duyệt. Kiểm tra reviewer ở gateway.',502:'Không kết nối được dịch vụ tri thức. Thử làm mới sau.'};
  $('error').textContent = messages[error.status] || error.message || 'Không thực hiện được thao tác.'; $('error').hidden = false;
}
async function perform(action) {
  if (busy) return;
  busy = true; document.body.setAttribute('aria-busy', 'true'); $('error').hidden = true;
  $('workspace').inert = true;
  try { await action(); } catch (error) { showError(error); }
  finally { $('workspace').inert = false; busy = false; document.body.removeAttribute('aria-busy'); }
}
async function api(resource, params = {}, body) {
  const url = '/api/knowledge/' + resource + (body ? '' : '?' + new URLSearchParams(params));
  const response = await fetch(url, {method:body ? 'POST' : 'GET', headers:body ? {'Content-Type':'application/json'} : {}, ...(body ? {body:JSON.stringify(body)} : {})});
  if (!response.ok) { const error = new Error('Không thực hiện được yêu cầu.'); error.status = response.status; throw error; }
  return response.json();
}
const command = (action, payload) => api('commands', {}, {action, payload});
async function record(resource, id) { const result = await api(resource, {item_id:id,limit:1}); if (!result.items.length) throw new Error('Bản ghi không còn tồn tại. Hãy làm mới.'); return result.items[0]; }
async function all(resource, params = {}) {
  let items = [], page = 0, result;
  do { result = await api(resource, {...params, offset:page, limit:100}); items.push(...result.items); page += 100; } while (page < result.total);
  return items;
}
async function bulkReview() {
  generation++;
  notice('Đang nạp toàn bộ bản nháp, nguồn và test…');
  const [drafts, gaps, sources, tests] = await Promise.all([
    all('revisions', {status:'draft'}), all('gaps'), all('sources'), all('regression_cases')]);
  const eligible = new Set(gaps.filter(g => !['technical','generation','correct_refusal'].includes(g.category)).map(g => g.id));
  const revisions = drafts.filter(r => eligible.has(r.gap_id));
  const root = $('detail'); root.replaceChildren(el('h2', `Duyệt hết · ${revisions.length} bản nháp`));
  note(root, 'Danh sách gồm mọi trang, không phụ thuộc bộ lọc gap. Chỉ duyệt bản nháp đã có nguồn và test; gap chưa có đề xuất cần được soạn riêng.');
  if (!revisions.length) { notice('Không có bản nháp phù hợp để duyệt.'); return; }
  for (const revision of revisions) {
    const item = el('details'); item.append(el('summary', `${revision.question} · ${revision.id}`));
    details(item, 'Nội dung đã lưu', {question:revision.question, answer:revision.answer,
      aliases:revision.aliases, scope:revision.scope, source_review_note:revision.source_review_note});
    const attached = sources.filter(s => (revision.source_ids || []).includes(s.chunk_id));
    details(item, 'Nguồn và hiệu lực', attached);
    details(item, 'Regression test', tests.find(t => t.id === revision.id) || 'Thiếu test.');
    root.append(item);
  }
  const form = el('form', null, 'form-grid'); root.append(form);
  const reason = field(form, 'Lý do duyệt hàng loạt', '');
  const reviewed = check(form, 'Tôi đã đối chiếu nội dung, nguồn và test của các bản nháp trong danh sách này.');
  button(form, `Duyệt ${revisions.length} bản nháp`, async () => {
    if (!reason.value.trim()) throw new Error('Nhập lý do duyệt hàng loạt.');
    if (!reviewed.checked) throw new Error('Cần xác nhận đã review nội dung, nguồn và test.');
    const failed = []; let approved = 0;
    for (const revision of revisions) {
      notice(`Đang duyệt ${approved + failed.length + 1}/${revisions.length}…`);
      try {
        const saved = await command('approve', {id:revision.id, content_hash:revision.content_hash,
          reason:reason.value, approve_test:true});
        selectedRevisions.set(saved.id, saved); approved++;
      } catch (error) { failed.push({id:revision.id, status:error.status || 'Không kết nối được'}); }
    }
    const summary = `Đã duyệt ${approved}/${revisions.length} bản nháp. Chưa phát hành.`;
    root.replaceChildren(el('h2', 'Kết quả duyệt hàng loạt'), el('p', summary));
    if (failed.length) {
      note(root, 'Chưa duyệt được: ' + failed.map(item => `${item.id} (${item.status})`).join(', ') + '. Làm mới để kiểm tra lại.', true);
      button(root, 'Làm mới danh sách còn lại', bulkReview, 'secondary');
    }
    note(root, 'Các bản duyệt thành công đã được chọn trong tab Phát hành.');
    notice(summary);
  });
  notice(`Đã nạp ${revisions.length} bản nháp để đối chiếu trước khi duyệt.`);
}
async function refresh() {
  generation++; $('detail').replaceChildren(el('p', 'Chọn một gap để xem bằng chứng và bản đề xuất.', 'empty'));
  if (tab === 'releases') return releases();
  const result = await api('gaps', {offset, status:$('status-filter').value}); active = result.active_release_id;
  $('gap-count').textContent = result.total + ' gap'; $('page-number').textContent = `Trang ${Math.floor(offset / 30) + 1}`;
  $('previous').disabled = offset === 0; $('next').disabled = offset + 30 >= result.total;
  $('gap-list').replaceChildren();
  for (const gap of result.items) {
    const row = el('button', null, 'gap-row'); row.type = 'button'; row.dataset.gapId = gap.id;
    row.append(el('strong', gap.title || 'Gap chưa có tiêu đề'), badge(gap.status), badge(gap.category), el('small', `${(gap.event_ids || []).length} phản hồi · ${gap.id}`));
    row.addEventListener('click', () => perform(() => openGap(gap.id))); $('gap-list').append(row);
  }
  if (!result.items.length) $('gap-list').append(el('p', 'Chưa có gap trong trạng thái này.', 'empty'));
  notice('Đã nạp hàng đợi. Chọn gap để bắt đầu.');
}
async function openGap(id) {
  const epoch = ++generation; notice('Đang nạp bằng chứng…');
  const gap = await record('gaps', id);
  const [revisions, events] = await Promise.all([all('revisions', {gap_id:id}), Promise.all((gap.event_ids || []).map(event => record('events', event)))]);
  if (epoch !== generation) return;
  const root = $('detail'); root.replaceChildren(el('h2', gap.title || 'Chi tiết gap'), badge(gap.status), badge(gap.category));
  document.querySelectorAll('.gap-row').forEach(row => row.setAttribute('aria-current', String(row.dataset.gapId === id)));
  root.append(el('p', `Mã ${gap.id} · phiên bản ${gap.version}`, 'muted'));
  if (gap.status === 'awaiting_verification') note(root, 'Nội dung đã phát hành, nhưng gap vẫn cần kiểm chứng trước/sau để được giải quyết.');
  if (gap.verification_run_id) details(root, 'Kết quả kiểm chứng', await record('verification_runs', gap.verification_run_id));
  root.append(el('h3', 'Bằng chứng từ phản hồi'));
  for (const event of events) {
    const box = el('article', null, 'evidence'); box.append(badge(event.source), badge(event.signal), el('small', event.created_at || ''));
    box.append(el('p', 'Khách hỏi', 'muted'), el('p', event.question || 'Không có câu hỏi.', 'speech'), el('p', 'Câu trả lời đã ghi nhận', 'muted'), el('p', event.answer || 'Không có câu trả lời.', 'speech'));
    if (event.reason) box.append(el('p', event.reason));
    details(box, 'Ngữ cảnh và công cụ đã ghi nhận', {context:event.context, tool_calls:event.tool_calls, release_id:event.release_id}); root.append(box);
  }
  if (!events.length) note(root, 'Chưa có bằng chứng phản hồi đính kèm. Không suy ra đáp án từ tiêu đề gap.');
  const triage = el('form', null, 'form-grid'); root.append(el('h3', 'Phân loại nguyên nhân'), triage);
  const category = select(triage, 'Loại vấn đề', categories, gap.category), reason = field(triage, 'Lý do phân loại', gap.reason || gap.source_review || '');
  const classify = el('button', 'Lưu phân loại'); classify.type = 'submit'; triage.append(classify);
  triage.addEventListener('submit', event => { event.preventDefault(); perform(async () => { await command('classify', {id:gap.id,version:gap.version,category:category.value,reason:reason.value}); await openGap(id); notice('Đã cập nhật phân loại.'); }); });
  root.append(el('h3', 'Đề xuất nội dung'));
  for (const revision of revisions) {
    const row = el('div', null, 'revision-row'); row.append(el('span', revision.question || revision.id), badge(revision.status));
    button(row, 'Xem bản đề xuất', () => editor(gap, revision)); root.append(row);
  }
  const blocked = ['technical','generation','correct_refusal'].includes(gap.category);
  if (blocked) note(root, 'Nhóm này cần xử lý kỹ thuật hoặc không cần sửa tri thức. Không tạo FAQ để che lỗi model.', true);
  else button(root, 'Tạo đề xuất mới', () => editor(gap));
  notice('Đã nạp bằng chứng và các bản đề xuất.');
}
async function editor(gap, revision = null) {
  const epoch = ++generation; notice('Đang nạp nguồn và regression test…');
  const [sources, test] = await Promise.all([all('sources'), revision ? record('regression_cases', revision.id) : Promise.resolve(null)]);
  if (epoch !== generation) return;
  const root = $('detail'); root.replaceChildren(); button(root, '← Quay lại bằng chứng', () => openGap(gap.id), 'secondary');
  root.append(el('h2', revision ? 'Duyệt bản đề xuất' : 'Soạn đề xuất có nguồn'), el('p', gap.title, 'muted'));
  if (revision) root.append(badge(revision.status), el('p', `Revision ${revision.id}`, 'muted'));
  if (['technical','generation','correct_refusal'].includes(gap.category)) { note(root, 'Gap đã được phân loại không cần sửa nội dung. Hãy quay lại bằng chứng.', true); return; }
  const form = el('form', null, 'form-grid'); root.append(form);
  const kind = select(form, 'Loại bổ sung', {faq:'FAQ có nguồn',aliases:'Cách hỏi / từ đồng nghĩa'}, revision?.kind || 'faq');
  const question = field(form, 'Câu hỏi', revision?.question || gap.title);
  const answer = field(form, 'Câu trả lời đề xuất', revision?.answer || '', 'textarea', false);
  const aliases = field(form, 'Cách hỏi khác (mỗi dòng một câu)', (revision?.aliases || []).join('\n'), 'textarea', false);
  const scope = field(form, 'Phạm vi áp dụng', revision?.scope || '', 'textarea', false);
  const label = el('label', 'Nguồn công khai làm căn cứ (giữ Ctrl/⌘ để chọn nhiều)'), sourceSelect = document.createElement('select'); sourceSelect.multiple = true; sourceSelect.required = true; label.append(sourceSelect); form.append(label);
  const chosenSources = revision?.source_ids || gap.suggested_source_ids || [];
  for (const source of sources) { const option = el('option', `${source.title} · ${source.chunk_id}`); option.value = source.chunk_id; option.selected = chosenSources.includes(source.chunk_id); sourceSelect.append(option); }
  const sourcePreview = el('div'); form.append(sourcePreview);
  function preview() {
    sourcePreview.replaceChildren();
    for (const source of sources.filter(s => [...sourceSelect.selectedOptions].some(o => o.value === s.chunk_id))) {
      const item = el('details'), body = el('div', null, 'source-body'); item.append(el('summary', `${source.title} · ${source.chunk_id}`));
      body.append(el('p', `Hiệu lực: ${source.effective_from || '—'} → ${source.effective_until || 'không ghi ngày kết thúc'} · Căn cứ ngày: ${source.date_basis || '—'}`, 'muted'), el('p', source.body || ''), el('p', `Hash nguồn: ${source.source_hash || '—'}`, 'muted')); item.append(body); sourcePreview.append(item);
    }
  }
  sourceSelect.addEventListener('change', preview); preview();
  const sourceNote = field(form, 'Kết quả đối chiếu nguồn và điều kiện áp dụng', revision?.source_review_note || '');
  note(form, 'Giá, tồn kho và quyền lợi động phải lấy từ công cụ nghiệp vụ. Không viết thành cam kết cố định trong FAQ.');
  function changeKind() { answer.required = kind.value === 'faq'; answer.parentElement.hidden = kind.value !== 'faq'; aliases.required = kind.value === 'aliases'; aliases.parentElement.hidden = kind.value !== 'aliases'; }
  kind.addEventListener('change', changeKind); changeKind();
  const save = el('button', revision ? 'Lưu thành bản nháp mới' : 'Lưu bản nháp'); save.type = 'submit'; form.append(save);
  form.addEventListener('submit', event => { event.preventDefault(); perform(async () => {
    const payload = {kind:kind.value,question:question.value,answer:answer.value,aliases:aliases.value.split('\n').map(x => x.trim()).filter(Boolean),scope:scope.value,source_ids:[...sourceSelect.selectedOptions].map(x => x.value),source_review_note:sourceNote.value};
    const saved = await command(revision ? 'edit_revision' : 'create_revision', revision ? {id:revision.id,content_hash:revision.content_hash,changes:payload} : {gap_id:gap.id,...payload});
    await editor(gap, saved); notice('Đã lưu bản nháp. Chưa phê duyệt hoặc phát hành.');
  }); });
  if (!revision) { notice('Soạn nội dung từ bằng chứng và nguồn hợp lệ.'); return; }
  root.append(el('h3', 'Regression test cần duyệt'));
  note(root, 'Bản nháp test là kỳ vọng cần kiểm tra, không phải bằng chứng model đã trả lời đúng.');
  details(root, 'Input và kỳ vọng test hiện tại', test);
  const testForm = el('form', null, 'form-grid'); root.append(testForm);
  const expected = field(testForm, 'Câu trả lời kỳ vọng', test.expected?.answer || '', 'textarea', false);
  const variations = field(testForm, 'Biến thể kiểm thử (mỗi dòng một câu)', (test.variations || []).join('\n'));
  const editTest = el('button', 'Lưu test thành bản nháp mới', 'secondary'); editTest.type = 'submit'; testForm.append(editTest);
  testForm.addEventListener('submit', event => { event.preventDefault(); perform(async () => {
    const saved = await command('edit_test', {id:test.id,test_hash:test.record_hash,expected:{answer:expected.value},variations:variations.value.split('\n').map(x => x.trim()).filter(Boolean)});
    await editor(gap, saved); notice('Test đã thay đổi: cần duyệt lại bản nháp mới.');
  }); });
  const decision = el('form', null, 'form-grid'); root.append(el('h3', 'Quyết định duyệt'), decision);
  const decisionReason = field(decision, 'Lý do quyết định', '');
  const reviewed = check(decision, 'Tôi đã đọc bản nội dung đã lưu, nguồn và regression test hiện tại.');
  const actions = el('div', null, 'button-row'); decision.append(actions);
  button(actions, 'Phê duyệt nội dung và test', async () => {
    if (!decisionReason.value.trim()) throw new Error('Nhập lý do quyết định.');
    if (!reviewed.checked) throw new Error('Cần xác nhận đã review nội dung, nguồn và test.');
    if (formChanged()) throw new Error('Có chỉnh sửa chưa lưu. Lưu bản nháp mới trước khi duyệt.');
    const saved = await command('approve', {id:revision.id,content_hash:revision.content_hash,reason:decisionReason.value,approve_test:true});
    await editor(gap, saved); notice('Đã phê duyệt. Nội dung chưa được phát hành.');
  });
  button(actions, 'Từ chối bản này', async () => { if (!decisionReason.value.trim()) throw new Error('Nhập lý do quyết định.'); const saved = await command('reject', {id:revision.id,content_hash:revision.content_hash,reason:decisionReason.value}); selectedRevisions.delete(revision.id); await editor(gap, saved); notice('Đã từ chối bản đề xuất.'); }, 'danger');
  // Approve only the displayed stored bytes, including the test being reviewed.
  const initialValues = [...form.querySelectorAll('input,textarea,select')].map(n => n.multiple ? [...n.selectedOptions].map(o => o.value).join(',') : n.value);
  const initialTest = [expected.value,variations.value];
  function formChanged() { return [...form.querySelectorAll('input,textarea,select')].some((n,i) => (n.multiple ? [...n.selectedOptions].map(o => o.value).join(',') : n.value) !== initialValues[i]) || expected.value !== initialTest[0] || variations.value !== initialTest[1]; }
  if (revision.status === 'approved') button(root, 'Thêm vào danh sách phát hành', async () => { if (formChanged()) throw new Error('Có chỉnh sửa chưa lưu.'); selectedRevisions.set(revision.id, revision); notice(`Đã chọn ${selectedRevisions.size} bản đã duyệt. Mở tab Phát hành để chuẩn bị release.`); }, 'secondary');
  notice('Đang xem nội dung đã lưu; mọi thay đổi cần lưu trước khi duyệt.');
}
async function releases() {
  const epoch = ++generation; notice('Đang tải các phiên bản…');
  const [result, approved] = await Promise.all([all('releases'), all('revisions', {status:'approved'})]);
  const state = await api('releases', {limit:1}); if (epoch !== generation) return;
  active = state.active_release_id; const root = $('releases-view'); root.replaceChildren(el('h2', 'Phát hành tri thức đã duyệt'), el('p', `Đang hoạt động: ${active || 'Chưa có release'}`, 'muted'));
  note(root, 'Duyệt nội dung không tự phát hành. Release mới chỉ chứa các bản được chọn; hãy giữ đủ nội dung muốn tiếp tục phục vụ. Phát hành xong vẫn cần eval trước/sau để xác minh gap.');
  root.append(el('h3', 'Chọn bản đã duyệt'));
  const available = new Set(approved.map(r => r.id)); for (const id of selectedRevisions.keys()) if (!available.has(id)) selectedRevisions.delete(id);
  for (const revision of approved) {
    const box = check(root, `${revision.question} · ${revision.id}`); box.checked = selectedRevisions.has(revision.id);
    box.addEventListener('change', () => box.checked ? selectedRevisions.set(revision.id, revision) : selectedRevisions.delete(revision.id));
  }
  if (!approved.length) note(root, 'Chưa có bản đề xuất đã duyệt. Quay lại tab Duyệt gap để xem nguồn và test.');
  if (approved.length > 100) note(root, 'Mỗi release chứa tối đa 100 bản. Bỏ chọn các bản chưa muốn phát hành trong release này.');
  button(root, 'Chuẩn bị release từ các bản đã chọn', async () => {
    if (!selectedRevisions.size) throw new Error('Chọn ít nhất một bản đã duyệt.');
    if (selectedRevisions.size > 100) throw new Error('Mỗi release chứa tối đa 100 bản. Hãy điều chỉnh danh sách đã chọn.');
    notice('Đang chuẩn bị chỉ mục và kiểm tra regression…');
    const release = await command('prepare_release', {revision_ids:[...selectedRevisions.keys()],expected_active_id:active});
    await releases(); await releaseDetail(root, release); notice('Release đã sẵn sàng. Chưa thay đổi phiên bản hoạt động.');
  });
  root.append(el('h3', 'Các release và kết quả kiểm tra'));
  for (const release of result) {
    const row = el('div', null, 'release-row'); row.append(el('span', release.id), badge(release.id === active ? 'Đang hoạt động' : release.status));
    button(row, 'Xem và phát hành', () => releaseDetail(root, release), 'secondary'); root.append(row);
  }
  if (!result.length) note(root, 'Chưa có release.');
  notice('Đã nạp các phiên bản và nội dung đã duyệt.');
}
async function releaseDetail(root, release) {
  root.querySelector('#release-detail')?.remove(); const box = el('section'); box.id = 'release-detail'; root.append(box);
  box.append(el('h3', `Release ${release.id}`), badge(release.status));
  details(box, 'Nội dung, nguồn và kết quả kiểm tra', release.manifest || release);
  const current = active && active !== release.id ? await record('releases', active) : null;
  const targetIds = new Set((release.manifest?.items || []).map(r => r.id));
  const removed = (current?.manifest?.items || []).filter(r => !targetIds.has(r.id));
  if (removed.length) note(box, `Release này sẽ không còn ${removed.length} bản đang phục vụ: ${removed.map(r => r.question || r.id).join('; ')}`, true);
  note(box, 'Kiểm tra retrieval offline không chứng minh chất lượng trả lời của LLM. Không đánh dấu gap đã giải quyết chỉ vì release sẵn sàng.');
  if (release.id !== active && release.status === 'ready') {
    const actions = el('div', null, 'button-row'); box.append(actions);
    for (const [action,label] of [['activate_release','Phát hành release này'],['rollback_release','Khôi phục về release này']]) button(actions, label, async () => {
      if (!window.confirm(`${label}: ${release.id}? Phiên bản đang hoạt động: ${active || 'chưa có'}.`)) return;
      await command(action, {id:release.id,expected_active_id:active}); selectedRevisions.clear(); await releases(); notice('Đã đổi phiên bản hoạt động. Các gap liên quan vẫn cần kiểm chứng.');
    }, action === 'rollback_release' ? 'secondary' : '');
  }
  box.scrollIntoView({block:'nearest',behavior:'auto'});
}
$('refresh').addEventListener('click', () => perform(refresh));
$('approve-all').addEventListener('click', () => perform(async () => {
  tab = 'gaps';
  for (const view of ['gaps','releases']) {
    $(view + '-tab').setAttribute('aria-selected', String(view === tab));
    $(view + '-view').hidden = view !== tab;
  }
  await bulkReview();
}));
$('status-filter').addEventListener('change', () => { offset = 0; perform(refresh); });
$('previous').addEventListener('click', () => { offset = Math.max(0,offset - 30); perform(refresh); });
$('next').addEventListener('click', () => { offset += 30; perform(refresh); });
for (const view of ['gaps','releases']) $(view + '-tab').addEventListener('click', () => perform(async () => {
  tab = view; generation++; for (const name of ['gaps','releases']) { $(name + '-tab').setAttribute('aria-selected', String(name === view)); $(name + '-view').hidden = name !== view; }
  await refresh();
}));

perform(refresh);
