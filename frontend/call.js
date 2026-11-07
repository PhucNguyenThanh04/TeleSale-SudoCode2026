import { PCMEncoder, PCMPlayer } from './audio.js';

const $ = id => document.getElementById(id);
const startButton = $('start-call');
const endButton = $('end-call');
const fields = [$('channel'), $('identity'), $('scenario-date')];
$('identity').value = `web_${crypto.randomUUID()}`;
$('scenario-date').value = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Ho_Chi_Minh', year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date());
let active = null;

const states = {
  connecting: ['Đang kết nối…', 'Đang chuẩn bị micro và kết nối trợ lý.'],
  listening: ['Đang nghe bạn', 'Cứ nói tự nhiên, rồi ngừng một chút để em trả lời.'],
  processing: ['Đang suy nghĩ…', 'Trợ lý đang xử lý lời bạn vừa nói.'],
  speaking: ['Trợ lý đang nói', 'Bạn có thể nói tiếp sau khi trợ lý trả lời xong.'],
  closed: ['Cuộc gọi đã kết thúc', 'Bấm bắt đầu gọi để mở một phiên mới.'],
};
const errors = {
  speech_unavailable: 'Chưa kết nối được dịch vụ nhận dạng giọng nói.',
  speech_disconnected: 'Kết nối nhận dạng giọng nói bị ngắt.',
  harness_failed: 'Agent chưa trả lời được. Kiểm tra dịch vụ AI và cấu hình backend.',
  tts_failed: 'Không phát được hết câu trả lời. Bạn có thể đọc nội dung và nói tiếp.',
  transcription_failed: 'Chưa nhận dạng được câu vừa nói. Bạn nói lại nhé.',
  overloaded: 'Dịch vụ giọng nói đang bận. Thử gọi lại sau.',
  service_unavailable: 'Dịch vụ giọng nói chưa sẵn sàng.',
};

function showState(state) {
  const [label, hint] = states[state] || states.connecting;
  $('status').textContent = label;
  $('hint').textContent = hint;
  $('visual').dataset.state = state;
}
function showError(message) {
  $('error').textContent = message;
  $('error').hidden = false;
}
function appendMessage(role, text) {
  $('empty')?.remove();
  const article = document.createElement('article');
  article.className = `message ${role}`;
  const label = document.createElement('div');
  label.className = 'message-label';
  label.textContent = role === 'user' ? 'BẠN' : 'TRỢ LÝ TELESALE';
  const body = document.createElement('p');
  body.textContent = text;
  article.append(label, body);
  $('messages').append(article);
  $('messages').scrollTop = $('messages').scrollHeight;
  return article;
}

const memoryFields = {
  room_area_m2: 'Diện tích phòng', budget_vnd: 'Ngân sách', has_children: 'Có trẻ nhỏ',
  product_advised: 'Sản phẩm đã tư vấn', price_quoted_vnd: 'Giá đã báo',
  promo_code: 'Mã ưu đãi', promo_expiry: 'Hạn ưu đãi', blocker: 'Băn khoăn còn mở',
  objection: 'Phản đối', preferred_size: 'Cỡ yêu thích', preferred_color: 'Màu yêu thích',
  order_id: 'Đơn hàng', in_stock: 'Còn hàng', competitor_price_vnd: 'Giá khách tham khảo',
  variant_sku: 'Phiên bản', size: 'Cỡ', color: 'Màu', payment: 'Thanh toán',
  owned_sku: 'Sản phẩm đang có', callback_scheduled: 'Đã hẹn gọi lại', alt_suggested: 'Mẫu thay thế',
};
function renderMemory(panel, update, finished = false) {
  panel.replaceChildren();
  panel.dataset.status = update.status;
  const title = document.createElement('strong');
  title.textContent = 'Bộ nhớ sau lượt này';
  const note = document.createElement('div');
  note.className = 'memory-note';
  const statusText = {
    pending: finished ? 'Chưa hoàn tất cập nhật; đã hết thời gian theo dõi.' : 'Đang cập nhật hồ sơ…',
    completed: update.changes?.length ? 'Đã cập nhật hồ sơ.' : 'Không có thay đổi hồ sơ mới.',
    failed: 'Cập nhật hồ sơ thất bại.',
    not_applicable: 'Chưa xác minh khách hàng; chỉ lưu hội thoại trong phiên.',
    unavailable: 'Chưa đọc được kết quả cập nhật hồ sơ.',
  };
  note.textContent = `${update.turn_saved ? 'Đã lưu hội thoại. ' : ''}${statusText[update.status] || statusText.unavailable}`;
  panel.append(title, note);
  if (update.status !== 'completed') return;
  const list = document.createElement('ul');
  for (const change of update.changes || []) {
    const item = document.createElement('li');
    const action = { added: 'Ghi mới', updated: 'Cập nhật', deleted: 'Xóa' }[change.action] || '';
    let value = change.value;
    if (typeof value === 'boolean') value = value ? 'Có' : 'Không';
    else if (typeof value === 'number') {
      value = value.toLocaleString('vi-VN') + (change.field === 'room_area_m2' ? ' m²'
        : change.field.endsWith('_vnd') ? ' đồng' : '');
    }
    const scope = change.scope_type !== 'global' && change.scope_id ? ` (${change.scope_id})` : '';
    const source = change.source === 'tool' ? 'công cụ xác minh' : 'khách cung cấp';
    item.textContent = `${action} · ${memoryFields[change.field] || change.field}${scope}`
      + (change.action === 'deleted' ? '' : `: ${value ?? ''}`) + ` — ${source}`;
    list.append(item);
  }
  panel.append(list);
}
function send(call, payload) {
  if (active === call && call.socket?.readyState === WebSocket.OPEN) {
    call.socket.send(JSON.stringify(payload));
  }
}
function stopCall(call = active) {
  if (!call || active !== call) return;
  active = null;
  for (const panel of call.memoryPanels?.values() || []) {
    if (panel.dataset.status === 'pending') {
      panel.querySelector('.memory-note').textContent = 'Chưa có kết quả cập nhật trước khi kết thúc cuộc gọi.';
    }
  }
  clearTimeout(call.timeout);
  clearInterval(call.clock);
  call.stream?.getTracks().forEach(track => track.stop());
  if (call.capture) { call.capture.port.onmessage = null; call.capture.disconnect(); }
  call.source?.disconnect();
  call.player?.stop();
  if (call.context) void call.context.close().catch(() => {});
  if (call.socket) {
    if (call.socket.readyState === WebSocket.OPEN) {
      call.socket.send(JSON.stringify({ event: 'end' }));
    }
    call.socket.close();
  }
  startButton.disabled = false;
  endButton.disabled = true;
  fields.forEach(field => { field.disabled = false; });
  showState('closed');
}
function fail(call, message) {
  if (active !== call) return;
  showError(message);
  stopCall(call);
}
function playbackFinished(call, turnId) {
  if (!turnId || call.acknowledged === turnId) return;
  call.player.finish(() => {
    if (active !== call || call.turnId !== turnId) return;
    call.acknowledged = turnId;
    send(call, { event: 'playback_finished', turn_id: turnId });
  });
}
function onEvent(call, event) {
  if (active !== call) return;
  switch (event.event) {
    case 'ready':
      if (event.audio.encoding !== 'pcm_s16le' || event.audio.sample_rate !== 16000 || event.audio.channels !== 1) {
        throw new Error('Dịch vụ yêu cầu định dạng micro không được hỗ trợ.');
      }
      clearTimeout(call.timeout);
      call.started = Date.now();
      $('duration').hidden = false;
      call.clock = setInterval(() => {
        const seconds = Math.floor((Date.now() - call.started) / 1000);
        $('duration').textContent = `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`;
      }, 1000);
      break;
    case 'state':
      if (event.state === 'closed') { stopCall(call); break; }
      call.state = event.state;
      if (event.state === 'listening') {
        call.encoder = new PCMEncoder(call.context.sampleRate);
        call.turnId = null;
      }
      showState(event.state);
      break;
    case 'speech_started': $('hint').textContent = 'Em đang nghe, bạn cứ nói tiếp…'; break;
    case 'speech_ended': $('hint').textContent = 'Đang nhận dạng lời bạn nói…'; break;
    case 'transcript_final': appendMessage('user', event.text); break;
    case 'agent_reply':
      call.turnId = event.turn_id;
      {
        const article = appendMessage('agent', event.agent_text);
        if (event.memory_update) {
          const panel = document.createElement('section');
          panel.className = 'memory-update';
          panel.setAttribute('aria-label', 'Bộ nhớ sau lượt này');
          panel.setAttribute('aria-live', 'polite');
          article.append(panel);
          call.memoryPanels.set(event.turn_id, panel);
          renderMemory(panel, event.memory_update);
        }
      }
      if (event.needs_handoff) $('hint').textContent = 'Trợ lý đã ghi nhận yêu cầu chuyển tư vấn viên.';
      break;
    case 'memory_update': {
      const panel = call.memoryPanels.get(event.turn_id);
      if (panel) renderMemory(panel, event.memory_update, event.tracking_finished);
      break;
    }
    case 'audio': call.player.enqueue(event); break;
    case 'audio_segment_end': call.player.pause(event.pause_ms); break;
    case 'audio_complete': playbackFinished(call, event.turn_id); break;
    case 'error':
      showError(errors[event.code] || 'Có lỗi trong cuộc gọi. Vui lòng thử lại.');
      if (event.fatal) stopCall(call);
      else if (event.stage === 'tts') playbackFinished(call, event.turn_id);
      break;
  }
}

async function startCall() {
  if (active) return;
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
    showError('Hãy mở website bằng HTTPS hoặc localhost trên Chrome/Edge để sử dụng micro.');
    return;
  }
  if (!fields.every(field => field.reportValidity())) return;
  const start = { event: 'start', channel: $('channel').value,
    channel_identity: $('identity').value.trim(), on: $('scenario-date').value };
  if (!start.channel_identity) { showError('Vui lòng nhập định danh kênh.'); return; }
  const call = { state: 'connecting', memoryPanels: new Map() };
  active = call;
  startButton.disabled = true;
  endButton.disabled = false;
  fields.forEach(field => { field.disabled = true; });
  $('error').hidden = true;
  $('duration').hidden = true;
  $('duration').textContent = '00:00';
  $('messages').replaceChildren();
  showState('connecting');
  try {
    // Resume in the button gesture, before waiting for microphone permission.
    call.context = new AudioContext();
    await call.context.resume();
    if (active !== call) return;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: {
      channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true,
    } });
    if (active !== call) { stream.getTracks().forEach(track => track.stop()); return; }
    call.stream = stream;
    stream.getAudioTracks()[0].onended = () => fail(call, 'Micro đã bị ngắt. Hãy kết nối lại và bắt đầu cuộc gọi mới.');
    await call.context.audioWorklet.addModule('/assets/capture-worklet.js');
    if (active !== call) return;
    call.player = new PCMPlayer(call.context);
    call.encoder = new PCMEncoder(call.context.sampleRate);
    call.capture = new AudioWorkletNode(call.context, 'call-capture');
    call.source = call.context.createMediaStreamSource(stream);
    call.source.connect(call.capture);
    call.capture.connect(call.context.destination);
    const url = new URL('/api/calls/stream', location.href);
    url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    call.socket = new WebSocket(url);
    call.timeout = setTimeout(() => fail(call, 'Kết nối quá lâu. Kiểm tra backend và dịch vụ speech rồi thử lại.'), 30000);
    call.socket.onopen = () => send(call, start);
    call.socket.onmessage = message => {
      try { onEvent(call, JSON.parse(message.data)); }
      catch { fail(call, 'Không xử lý được âm thanh hoặc phản hồi từ dịch vụ.'); }
    };
    call.socket.onerror = () => fail(call, 'Không kết nối được máy chủ cuộc gọi.');
    call.socket.onclose = () => {
      if (active === call) fail(call, 'Kết nối cuộc gọi đã bị ngắt. Bạn có thể bắt đầu phiên mới.');
    };
    call.capture.port.onmessage = ({ data }) => {
      if (active !== call || call.state !== 'listening' || call.socket.readyState !== WebSocket.OPEN) return;
      if (call.socket.bufferedAmount > 64000) {
        fail(call, 'Mạng không theo kịp âm thanh. Kiểm tra kết nối rồi gọi lại.');
        return;
      }
      for (const bytes of call.encoder.push(data)) call.socket.send(bytes);
    };
  } catch (error) {
    const message = error.name === 'NotAllowedError' ? 'Bạn chưa cho phép micro. Cấp quyền micro cho website rồi thử lại.'
      : error.name === 'NotFoundError' ? 'Không tìm thấy micro. Kết nối micro rồi thử lại.'
      : 'Không mở được micro hoặc thiết bị âm thanh. Kiểm tra thiết bị rồi thử lại.';
    fail(call, message);
  }
}
startButton.addEventListener('click', startCall);
endButton.addEventListener('click', () => stopCall());
window.addEventListener('pagehide', () => stopCall());
