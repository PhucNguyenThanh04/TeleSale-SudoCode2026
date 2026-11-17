import { setupProfile } from './auth.js';
const $ = id => document.getElementById(id);
const fields = [$('channel'), $('identity'), $('scenario-date')];
const panels = new Map();
const replies = new Map();
let socket = null;
let busy = false;
let timelineSession = null;
let timelineNext = null;
let timelineController = null;
let timelineVersion = 0;
$('scenario-date').value = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Ho_Chi_Minh', year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date());

await setupProfile();

function controls(connected) {
  fields.forEach(field => { field.disabled = connected; });
  $('connect').disabled = connected;
  $('end').disabled = !connected;
  $('text').disabled = !connected || busy;
  $('send').disabled = !connected || busy;
}
function error(message) {
  $('error').textContent = message;
  $('error').hidden = false;
}

function resetTimeline() {
  timelineVersion++;
  timelineController?.abort();
  timelineSession = null;
  timelineNext = null;
  $('timeline-items').replaceChildren();
  $('timeline-status').textContent = 'Bắt đầu phiên để xem lịch sử.';
  $('timeline-reload').disabled = true;
  $('timeline-more').hidden = true;
}

async function loadTimeline(reset = true) {
  if (!timelineSession || !reset && timelineNext === null) return;
  const query = { ...timelineSession, offset: reset ? 0 : timelineNext, limit: 10 };
  const version = ++timelineVersion;
  timelineController?.abort();
  timelineController = new AbortController();
  $('timeline-reload').disabled = true;
  $('timeline-more').disabled = true;
  $('timeline-status').textContent = 'Đang tải lịch sử…';
  try {
    const response = await fetch('/api/chat/timeline', { method: 'POST', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(query), signal: timelineController.signal });
    if (response.status === 401) location.replace('/login');
    if (!response.ok) throw Error('timeline_unavailable');
    const data = await response.json();
    if (version !== timelineVersion) return;
    if (data.session_id !== query.session_id || !Array.isArray(data.timeline?.items)) throw Error('timeline_identity_changed');
    const page = data.timeline;
    if (reset) $('timeline-items').replaceChildren();
    const channels = { hotline: 'Hotline', chat_fanpage: 'Fanpage', zalo_oa: 'Zalo OA', web_chat: 'Website', other: 'Kênh khác' };
    const outcomes = { chot_don: 'Đã đặt hàng', hen_goi_lai: 'Hẹn liên hệ lại', tu_choi: 'Từ chối', chuyen_may: 'Chuyển nhân viên', khac: 'Đã trao đổi' };
    for (const item of page.items) {
      const row = document.createElement('li');
      const when = document.createElement('time');
      when.dateTime = item.on;
      when.textContent = `${item.on.split('-').reverse().join('/')} · ${channels[item.channel]}`;
      const summary = document.createElement('p');
      summary.textContent = item.summary;
      const outcome = document.createElement('small');
      outcome.textContent = outcomes[item.outcome] + (item.summary_status === 'pending' ? ' · Đang cập nhật tóm tắt' : '');
      row.append(when, summary, outcome);
      $('timeline-items').append(row);
    }
    timelineNext = page.next_offset;
    $('timeline-more').hidden = timelineNext === null;
    $('timeline-status').textContent = page.status === 'not_applicable'
      ? 'Chưa xác minh khách hàng để hiển thị lịch sử.'
      : page.total === 0 ? 'Chưa có tương tác đã lưu.'
        : `Đang hiển thị ${$('timeline-items').childElementCount}/${page.total} phiên.`;
  } catch (exception) {
    if (version !== timelineVersion) return;
    $('timeline-items').replaceChildren();
    timelineNext = null;
    $('timeline-more').hidden = true;
    $('timeline-status').textContent = 'Chưa tải được lịch sử. Bạn có thể tải lại.';
  } finally {
    if (version === timelineVersion) {
      $('timeline-reload').disabled = !timelineSession;
      $('timeline-more').disabled = false;
    }
  }
}
$('timeline-reload').addEventListener('click', () => loadTimeline());
$('timeline-more').addEventListener('click', () => loadTimeline(false));
function message(role, text) {
  const article = document.createElement('article');
  article.className = `message ${role}`;
  const label = document.createElement('div');
  label.className = 'message-label';
  label.textContent = role === 'user' ? 'BẠN' : 'TRỢ LÝ TELESALE';
  const body = document.createElement('p');
  body.textContent = text;
  article.append(label, body);
  $('messages').append(article);
  article.scrollIntoView({ block: 'nearest' });
  return article;
}
function brief(value) {
  if (!value?.is_returning || $('brief').childElementCount) return;
  const panel = document.createElement('details');
  panel.className = 'call-brief';
  panel.open = true;
  const title = document.createElement('summary');
  title.textContent = 'Thông tin từ các phiên trước';
  panel.append(title);
  const row = (label, text) => {
    if (!text) return;
    const item = document.createElement('p');
    item.textContent = `${label}: ${text}`;
    panel.append(item);
  };
  row('Lịch sử', `${value.n_previous_sessions ?? 0} phiên trước`);
  for (const product of value.products_advised || []) {
    row('Đã tư vấn', product.sku);
    if (typeof product.price_quoted_vnd === 'number') {
      row('Giá lịch sử', `${product.price_quoted_vnd.toLocaleString('vi-VN')} đồng${product.quoted_on ? ` (${product.quoted_on})` : ''}`);
    }
    row('Ưu đãi lịch sử', product.promo_code);
  }
  row('Đề xuất gần nhất', value.recommended_sku);
  row('Khách đã chọn', value.selected_sku || 'Chưa xác nhận');
  for (const blocker of value.open_blockers || []) row('Còn cần trao đổi', typeof blocker === 'string' ? blocker : blocker.text);
  for (const warning of value.stale_warnings || []) row('Cần kiểm tra lại', warning);
  row('Bước tiếp theo', value.suggested_next_action);
  $('brief').append(panel);
}
const labels = {
  room_area_m2: 'Diện tích phòng', budget_vnd: 'Ngân sách', has_children: 'Có trẻ nhỏ',
  product_advised: 'Sản phẩm đã tư vấn', price_quoted_vnd: 'Giá đã báo',
  promo_code: 'Mã ưu đãi', promo_expiry: 'Hạn ưu đãi', blocker: 'Băn khoăn còn mở',
  objection: 'Phản đối', preferred_size: 'Cỡ yêu thích', preferred_color: 'Màu yêu thích',
  order_id: 'Đơn hàng', in_stock: 'Còn hàng', competitor_price_vnd: 'Giá khách tham khảo',
  variant_sku: 'Phiên bản', size: 'Cỡ', color: 'Màu', payment: 'Thanh toán',
  owned_sku: 'Sản phẩm đang có', callback_scheduled: 'Đã hẹn gọi lại', alt_suggested: 'Mẫu thay thế',
};
function memory(panel, update, finished = false) {
  panel.replaceChildren();
  panel.dataset.status = update.status;
  const title = document.createElement('strong');
  title.textContent = 'Bộ nhớ sau lượt này';
  const note = document.createElement('p');
  const statuses = {
    pending: finished ? 'Chưa có kết quả cập nhật; đã dừng theo dõi.' : 'Đang cập nhật hồ sơ…',
    completed: update.changes?.length ? 'Đã cập nhật hồ sơ.' : 'Không có thay đổi hồ sơ mới.',
    failed: 'Cập nhật hồ sơ thất bại.', unavailable: 'Chưa đọc được kết quả cập nhật.',
    not_applicable: 'Chưa xác minh khách hàng; chỉ lưu hội thoại trong phiên.',
  };
  note.textContent = `${update.turn_saved ? 'Đã lưu hội thoại. ' : ''}${statuses[update.status] || statuses.unavailable}`;
  panel.append(title, note);
  if (update.status !== 'completed') return;
  for (const change of update.changes || []) {
    const item = document.createElement('p');
    const action = { added: 'Ghi mới', updated: 'Cập nhật', deleted: 'Xóa' }[change.action] || 'Thay đổi';
    let value = change.value;
    if (typeof value === 'boolean') value = value ? 'Có' : 'Không';
    else if (typeof value === 'number') value = value.toLocaleString('vi-VN')
      + (change.field.endsWith('_vnd') ? ' đồng' : change.field === 'room_area_m2' ? ' m²' : '');
    item.textContent = `${action} · ${labels[change.field] || 'Thông tin khác'}`
      + (change.scope_id ? ` (${change.scope_id})` : '')
      + (change.action === 'deleted' ? '' : `: ${value ?? ''}`);
    panel.append(item);
  }
}

$('connect').addEventListener('click', () => {
  if (!fields.every(field => field.reportValidity())) return;
  $('error').hidden = true;
  $('brief').replaceChildren();
  resetTimeline();
  panels.clear();
  replies.clear();
  busy = true;
  controls(true);
  $('status').textContent = 'Đang kết nối…';
  const current = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/chat/stream`);
  socket = current;
  current.onopen = () => current.send(JSON.stringify({ event: 'start', channel: $('channel').value,
    channel_identity: $('identity').value.trim(), on: $('scenario-date').value }));
  current.onmessage = event => {
    if (socket !== current) return;
    let data;
    try { data = JSON.parse(event.data); } catch { error('Phản hồi không hợp lệ.'); return; }
    if (data.event === 'ready') {
      brief(data.call_brief);
      timelineSession = { session_id: data.session_id, channel: $('channel').value, on: $('scenario-date').value };
      loadTimeline();
      busy = false;
      controls(true);
      $('status').textContent = 'Sẵn sàng trò chuyện';
      $('text').focus();
    } else if (data.event === 'agent_delta') {
      let article = replies.get(data.client_msg_id);
      if (!article) {
        article = message('agent', '');
        replies.set(data.client_msg_id, article);
      }
      article.querySelector('p').textContent += data.text;
      article.scrollIntoView({ block: 'nearest' });
      $('status').textContent = 'Trợ lý đang trả lời…';
    } else if (data.event === 'agent_reply') {
      brief(data.call_brief);
      const article = replies.get(data.client_msg_id) || message('agent', data.agent_text);
      const panel = document.createElement('div');
      panel.className = 'memory-update';
      article.append(panel);
      panels.set(data.client_msg_id, panel);
      memory(panel, data.memory_update);
      if (data.memory_update?.status === 'completed') loadTimeline();
      if (data.needs_handoff) message('agent', 'Yêu cầu đã được chuyển để nhân viên tiếp nhận.');
      busy = false;
      controls(true);
      $('status').textContent = 'Sẵn sàng nhận tin nhắn tiếp theo';
      $('text').focus();
    } else if (data.event === 'memory_update') {
      const panel = panels.get(data.client_msg_id);
      if (panel) memory(panel, data.memory_update, data.tracking_finished);
      if (data.memory_update?.status === 'completed') loadTimeline();
    } else if (data.event === 'error') {
      error(replies.has(data.client_msg_id) ? 'Phản hồi bị ngắt. Nội dung đã nhận vẫn được giữ lại.'
        : data.code === 'harness_failed' ? 'Trợ lý chưa xử lý được lượt này. Bạn có thể thử lại.' : 'Thông tin phiên hoặc tin nhắn chưa hợp lệ.');
      busy = false;
      controls(true);
      if (data.fatal) current.close();
    }
  };
  current.onerror = () => error('Không kết nối được trợ lý. Kiểm tra dịch vụ rồi thử lại.');
  current.onclose = event => {
    if (event.code === 4401) location.replace('/login');
    if (socket !== current) return;
    resetTimeline();
    socket = null;
    busy = false;
    controls(false);
    $('status').textContent = 'Phiên đã kết thúc. Bắt đầu phiên mới để tiếp tục.';
    for (const panel of panels.values()) {
      if (panel.dataset.status === 'pending') memory(panel, { status: 'pending', changes: [] }, true);
    }
  };
});
$('chat-form').addEventListener('submit', event => {
  event.preventDefault();
  const text = $('text').value.trim();
  if (!text || busy || socket?.readyState !== WebSocket.OPEN) return;
  $('error').hidden = true;
  message('user', text);
  socket.send(JSON.stringify({ event: 'text', client_msg_id: crypto.randomUUID(), text }));
  $('text').value = '';
  busy = true;
  controls(true);
  $('status').textContent = 'Trợ lý đang xử lý…';
});
$('end').addEventListener('click', () => {
  resetTimeline();
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ event: 'end' }));
  socket?.close();
});
