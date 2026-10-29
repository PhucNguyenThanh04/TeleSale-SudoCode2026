const player = $('player');
const speakButton = $('speak');
const ttsDebug = $('ttsDebug');
const engineSelect = $('engine');
const voiceSelect = $('voice');
const korvaVoices = voiceSelect.innerHTML;
let vieneuContext = null;

let pendingAudio = [];
let activeUrl = null;
let pauseTimer = null;
let receivedCount = 0;
let totalCount = 0;
let streamFinished = false;
let streamError = null;
let playing = false;
let readyToPlay = true;
let currentAudio = null;
let requestController = null;

function releaseActiveAudio() {
  if (activeUrl) URL.revokeObjectURL(activeUrl);
  activeUrl = null;
}

function resetPlayback() {
  if (requestController) requestController.abort();
  if (pauseTimer) window.clearTimeout(pauseTimer);
  player.pause();
  if (vieneuContext) vieneuContext.close();
  vieneuContext = null;
  player.onended = null;
  releaseActiveAudio();
  pendingAudio = [];
  receivedCount = 0;
  totalCount = 0;
  streamFinished = false;
  streamError = null;
  playing = false;
  readyToPlay = true;
  currentAudio = null;
  requestController = new AbortController();
}

engineSelect.onchange = async () => {
  resetPlayback();
  speakButton.disabled = false;
  if (engineSelect.value === 'korva') {
    voiceSelect.innerHTML = korvaVoices;
    player.hidden = false;
    ttsDebug.textContent = 'KorvaTTS: chờ yêu cầu';
    return;
  }
  player.hidden = true;
  voiceSelect.replaceChildren(new Option('Đang tải giọng đọc…', ''));
  speakButton.disabled = true;
  try {
    const response = await fetch(`${api}/v1/speech/vieneu/voices`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    voiceSelect.replaceChildren(...data.voices.map(item => new Option(item.label, item.id)));
    if (!data.voices.length) throw new Error('Không có giọng VieNeu');
    const preferred = data.voices.find(item => item.id === 'Trúc Ly');
    if (preferred) voiceSelect.value = preferred.id;
    speakButton.disabled = false;
    ttsDebug.textContent = `VieNeu: ${data.voices.length} giọng đọc sẵn sàng.`;
  } catch (error) {
    ttsDebug.textContent = `Không tải được VieNeu: ${error.message}`;
  }
};

function parseSseBlock(block) {
  let name = 'message';
  const dataLines = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) name = line.slice(6).trim();
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
  }
  return dataLines.length ? {name, data: JSON.parse(dataLines.join('\n'))} : null;
}

async function speakVieNeu() {
  vieneuContext = new AudioContext();
  await vieneuContext.resume();
  const context = vieneuContext;
  const started = performance.now();
  let nextAt = context.currentTime + 0.03;
  let frames = 0;
  let segments = 0;
  let firstFrameMs = null;
  let completed = false;
  const response = await fetch(`${api}/v1/speech/vieneu/stream`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({text: $('text').value, voice: voiceSelect.value}),
    signal: requestController.signal,
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || response.status);
  }
  if (!response.body) throw new Error('Trình duyệt không hỗ trợ luồng âm thanh');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const {done, value} = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
    let boundary;
    while ((boundary = buffer.indexOf('\n\n')) !== -1) {
      const event = parseSseBlock(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      if (!event) continue;
      const {name, data} = event;
      if (name === 'start') {
        totalCount = data.segments_total;
        ttsDebug.textContent = `VieNeu: đang tạo câu 1/${totalCount}…`;
      } else if (name === 'audio_chunk') {
        const binary = atob(data.pcm16_base64);
        const pcm = new Int16Array(binary.length / 2);
        for (let i = 0; i < pcm.length; i++) pcm[i] = binary.charCodeAt(i * 2) | (binary.charCodeAt(i * 2 + 1) << 8);
        const audio = context.createBuffer(1, pcm.length, data.sample_rate);
        const channel = audio.getChannelData(0);
        for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 32768;
        const source = context.createBufferSource();
        source.buffer = audio;
        source.connect(context.destination);
        nextAt = Math.max(nextAt, context.currentTime + 0.03);
        source.start(nextAt);
        nextAt += audio.duration;
        frames += 1;
        if (firstFrameMs === null) firstFrameMs = Math.round(performance.now() - started);
        ttsDebug.textContent = `VieNeu: đang phát câu ${data.index + 1}/${totalCount} · khung ${frames} · khung đầu ${firstFrameMs} ms`;
      } else if (name === 'segment_end') {
        segments += 1;
        if (segments < totalCount) nextAt += 0.2;
      } else if (name === 'done') {
        completed = true;
      } else if (name === 'error') {
        throw new Error(data.message || 'VieNeu generation failed');
      }
    }
    if (done) break;
  }
  if (!completed) throw new Error('Luồng VieNeu kết thúc sớm');
  const remainingMs = Math.max(0, (nextAt - context.currentTime) * 1000);
  await new Promise(resolve => window.setTimeout(resolve, remainingMs));
  ttsDebug.textContent = `VieNeu: đã phát ${segments} câu · ${frames} khung · khung đầu ${firstFrameMs} ms.`;
  speakButton.disabled = false;
}

function showPlayback() {
  if (!currentAudio) return;
  ttsDebug.textContent = `Đang phát câu ${currentAudio.index + 1}/${totalCount}: ${currentAudio.text}\nTTS: ${currentAudio.tts_ms} ms · âm thanh ${currentAudio.audio_s} s · đã nhận ${receivedCount}/${totalCount}`;
}

function finishIfComplete() {
  if (playing || pendingAudio.length || !streamFinished || !readyToPlay) return;
  speakButton.disabled = false;
  ttsDebug.textContent = streamError || `TTS: đã phát xong ${receivedCount} câu.`;
}

function playReadyAudio() {
  if (playing || !readyToPlay) return;
  if (!pendingAudio.length) {
    if (!streamFinished && receivedCount) ttsDebug.textContent = `Đang chờ câu tiếp theo (${receivedCount}/${totalCount})…`;
    finishIfComplete();
    return;
  }

  currentAudio = pendingAudio.shift();
  const bytes = Uint8Array.from(atob(currentAudio.audio_base64), character => character.charCodeAt(0));
  activeUrl = URL.createObjectURL(new Blob([bytes], {type: 'audio/wav'}));
  player.src = activeUrl;
  playing = true;
  readyToPlay = false;
  showPlayback();
  player.onended = () => {
    playing = false;
    releaseActiveAudio();
    pauseTimer = window.setTimeout(() => {
      pauseTimer = null;
      readyToPlay = true;
      playReadyAudio();
    }, 200);
  };
  player.play().catch(error => {
    requestController.abort();
    player.onended = null;
    playing = false;
    readyToPlay = true;
    pendingAudio = [];
    releaseActiveAudio();
    streamError = `Không phát được âm thanh: ${error.message}`;
    streamFinished = true;
    finishIfComplete();
  });
}

function acceptEvent(block) {
  let name = 'message';
  const dataLines = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) name = line.slice(6).trim();
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
  }
  if (!dataLines.length) return;
  const data = JSON.parse(dataLines.join('\n'));
  if (name === 'start') {
    totalCount = data.segments_total;
    ttsDebug.textContent = `Đang tạo câu 1/${totalCount}…`;
  } else if (name === 'segment') {
    if (data.index !== receivedCount) throw new Error('Các câu TTS về sai thứ tự');
    pendingAudio.push(data);
    receivedCount += 1;
    if (playing) showPlayback();
    playReadyAudio();
  } else if (name === 'done') {
    streamFinished = true;
    playReadyAudio();
  } else if (name === 'error') {
    streamError = data.message || 'Lỗi tạo âm thanh';
    streamFinished = true;
    playReadyAudio();
  }
}

speakButton.onclick = async () => {
  resetPlayback();
  speakButton.disabled = true;
  ttsDebug.textContent = 'Đang kết nối TTS…';
  if (engineSelect.value === 'vieneu') {
    try {
      await speakVieNeu();
    } catch (error) {
      if (error.name !== 'AbortError') ttsDebug.textContent = `Lỗi VieNeu: ${error.message}`;
      speakButton.disabled = false;
    }
    return;
  }
  try {
    const response = await fetch(`${api}/v1/speech/synthesize/stream`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text: $('text').value, voice: $('voice').value}),
      signal: requestController.signal,
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || response.status);
    }
    if (!response.body) throw new Error('Trình duyệt không hỗ trợ đọc luồng âm thanh');

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const {done, value} = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        acceptEvent(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
      }
      if (done) break;
    }
    if (!streamFinished) throw new Error('Luồng TTS kết thúc trước khi nhận đủ câu');
  } catch (error) {
    if (error.name !== 'AbortError') {
      streamError = `Lỗi TTS: ${error.message}`;
      streamFinished = true;
      playReadyAudio();
    }
  }
};

if (engineSelect.value === 'vieneu') engineSelect.onchange();
