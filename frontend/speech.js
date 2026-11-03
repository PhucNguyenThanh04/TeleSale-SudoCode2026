(() => {
  "use strict";

  const API = "https://sudoapi.ktoxz.id.vn";
  const recordButton = document.getElementById("record-button");
  const stopButton = document.getElementById("stop-voice");
  const label = document.getElementById("voice-label");
  const debug = document.getElementById("pipeline-status");
  const stages = {micro: "sẵn sàng", vad: "chờ âm thanh", stt: "chờ âm thanh", agent: "chờ lời khách", tts: "chờ câu trả lời"};
  let input = null;
  let capture = null;
  let playback = null;
  let playbackRequest = null;
  let playbackSources = [];
  let playbackGeneration = 0;
  let onTranscript = null;
  let canRecord = () => true;
  const ACKNOWLEDGEMENT = "Dạ, em đang kiểm tra thông tin cho mình ạ.";

  function render() {
    debug.textContent = [
      `Micro: ${stages.micro}`,
      `VAD: ${stages.vad}`,
      `STT: ${stages.stt}`,
      `Agent: ${stages.agent}`,
      `VieNeu: ${stages.tts}`,
    ].join("\n");
    for (const [name, value] of Object.entries(stages)) {
      const badge = document.getElementById(`stage-${name}`);
      if (!badge) continue;
      badge.textContent = value.split(" · ")[0];
      badge.parentElement.dataset.state = /lỗi|chưa sẵn sàng/.test(value) ? "error"
        : /đang|chờ khung/.test(value) ? "active"
        : /xong|ms|giây đã thu|đã dừng/.test(value) ? "complete" : "idle";
    }
  }

  function setStage(name, value) {
    stages[name] = value;
    render();
  }

  async function checkHealth() {
    const [core, voices] = await Promise.allSettled([
      fetch(`${API}/health`).then(async (response) => response.ok && (await response.json()).status === "ready"),
      fetch(`${API}/v1/speech/vieneu/voices`).then((response) => response.ok),
    ]);
    const speechReady = core.status === "fulfilled" && core.value;
    const ttsReady = voices.status === "fulfilled" && voices.value;
    if (!speechReady) {
      setStage("vad", "dịch vụ chưa sẵn sàng");
      setStage("stt", "dịch vụ chưa sẵn sàng");
    }
    if (!ttsReady) setStage("tts", "dịch vụ chưa sẵn sàng");
    return speechReady && ttsReady;
  }

  function primePlayback() {
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!Context) { setStage("tts", "trình duyệt không hỗ trợ Web Audio"); return false; }
    if (!playback) playback = new Context();
    if (playback.state === "suspended") playback.resume();
    return true;
  }

  function stopPlayback() {
    playbackGeneration += 1;
    if (playbackRequest) playbackRequest.abort();
    playbackRequest = null;
    for (const source of playbackSources) {
      try { source.stop(); } catch (_) { /* frame has already ended */ }
    }
    playbackSources = [];
    stopButton.hidden = true;
    label.textContent = "Giọng trả lời: VieNeu · Trúc Ly";
  }

  function wav(samples, rate) {
    const bytes = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(bytes);
    const write = (offset, value) => {
      for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
    };
    write(0, "RIFF"); view.setUint32(4, bytes.byteLength - 8, true);
    write(8, "WAVEfmt "); view.setUint32(16, 16, true);
    view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true);
    view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    write(36, "data"); view.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i++) {
      view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, samples[i])) * 32767, true);
    }
    return bytes;
  }

  async function startRecording() {
    if (!canRecord()) return;
    primePlayback();
    stopPlayback();
    let stream;
    let context;
    try {
      stream = await navigator.mediaDevices.getUserMedia({audio: true});
      const Context = window.AudioContext || window.webkitAudioContext;
      if (!Context) throw new Error("Trình duyệt không hỗ trợ Web Audio");
      context = new Context();
      const source = context.createMediaStreamSource(stream);
      const processor = context.createScriptProcessor(4096, 1, 1);
      const chunks = [];
      processor.onaudioprocess = (event) => chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
      source.connect(processor);
      processor.connect(context.destination);
      capture = {stream, context, source, processor, chunks, started: performance.now()};
      recordButton.textContent = "■ Dừng và gửi";
      recordButton.classList.add("recording");
      setStage("micro", "đang ghi âm (tối đa 30 giây)");
      capture.timer = setTimeout(() => stopRecording(), 30000);
    } catch (error) {
      stream?.getTracks().forEach((track) => track.stop());
      await context?.close();
      setStage("micro", `lỗi: ${error.message}`);
    }
  }

  async function stopRecording() {
    const current = capture;
    if (!current) return;
    capture = null;
    clearTimeout(current.timer);
    current.processor.disconnect();
    current.source.disconnect();
    current.stream.getTracks().forEach((track) => track.stop());
    const rate = current.context.sampleRate;
    await current.context.close();
    recordButton.textContent = "● Bắt đầu ghi âm";
    recordButton.classList.remove("recording");
    const length = current.chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    if (!length) { setStage("micro", "không có âm thanh"); return; }
    const samples = new Float32Array(length);
    let offset = 0;
    for (const chunk of current.chunks) { samples.set(chunk, offset); offset += chunk.length; }
    setStage("micro", `${(length / rate).toFixed(2)} giây đã thu`);
    setStage("vad", "đang xử lý…");
    setStage("stt", "đang chép lời…");
    recordButton.disabled = true;
    const started = performance.now();
    try {
      const response = await fetch(`${API}/v1/speech/transcribe`, {
        method: "POST", headers: {"Content-Type": "audio/wav"}, body: wav(samples, rate),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || `HTTP ${response.status}`);
      setStage("vad", `${result.debug.vad_ms} ms · ${result.segments.length} đoạn`);
      setStage("stt", `${result.debug.stt_ms} ms · tổng ${(performance.now() - started).toFixed(0)} ms`);
      const transcript = result.text.trim();
      if (!transcript) { setStage("stt", "không phát hiện lời nói"); return; }
      onTranscript?.(transcript);
    } catch (error) {
      setStage("vad", "lỗi xử lý âm thanh");
      setStage("stt", error.message);
    } finally {
      recordButton.disabled = false;
    }
  }

  function parseEvent(block) {
    let name = "";
    const lines = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) name = line.slice(6).trim();
      if (line.startsWith("data:")) lines.push(line.slice(5).trimStart());
    }
    return lines.length ? {name, data: JSON.parse(lines.join("\n"))} : null;
  }

  async function speak(text, {acknowledgement = false} = {}) {
    stopPlayback();
    if (!primePlayback()) return;
    const generation = playbackGeneration;
    const controller = new AbortController();
    playbackRequest = controller;
    stopButton.hidden = false;
    label.textContent = acknowledgement ? "VieNeu đang xác nhận…" : "VieNeu đang tạo âm thanh…";
    setStage("tts", acknowledgement ? "đang tạo câu xác nhận…" : "đang chờ khung đầu…");
    const started = performance.now();
    let nextAt = playback.currentTime + 0.03;
    let firstFrameMs = null;
    let frames = 0;
    let completedSegments = 0;
    let totalSegments = 0;
    let doneEvent = false;
    try {
      const response = await fetch(`${API}/v1/speech/vieneu/stream`, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({text, voice: "Trúc Ly"}), signal: controller.signal,
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${response.status}`);
      }
      if (!response.body) throw new Error("Trình duyệt không hỗ trợ luồng âm thanh");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const {done, value} = await reader.read();
        if (generation !== playbackGeneration) return;
        buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
        let boundary;
        while ((boundary = buffer.indexOf("\n\n")) !== -1) {
          const event = parseEvent(buffer.slice(0, boundary));
          buffer = buffer.slice(boundary + 2);
          if (!event) continue;
          const {name, data} = event;
          if (name === "start") totalSegments = data.segments_total;
          if (name === "audio_chunk") {
            const binary = atob(data.pcm16_base64);
            const audio = playback.createBuffer(1, binary.length / 2, data.sample_rate);
            const channel = audio.getChannelData(0);
            for (let i = 0; i < channel.length; i++) {
              let sample = binary.charCodeAt(i * 2) | (binary.charCodeAt(i * 2 + 1) << 8);
              if (sample >= 32768) sample -= 65536;
              channel[i] = sample / 32768;
            }
            const source = playback.createBufferSource();
            source.buffer = audio;
            source.connect(playback.destination);
            source.onended = () => {
              const position = playbackSources.indexOf(source);
              if (position !== -1) playbackSources.splice(position, 1);
              source.disconnect();
            };
            nextAt = Math.max(nextAt, playback.currentTime + 0.03);
            source.start(nextAt);
            nextAt += audio.duration;
            playbackSources.push(source);
            frames += 1;
            if (firstFrameMs === null) firstFrameMs = Math.round(performance.now() - started);
            setStage("tts", acknowledgement
              ? `đang xác nhận · khung đầu ${firstFrameMs} ms`
              : `đang phát câu ${data.index + 1}/${totalSegments} · khung đầu ${firstFrameMs} ms · ${frames} khung`);
            label.textContent = acknowledgement ? "VieNeu · đang xác nhận" : "VieNeu · Trúc Ly đang phát";
          }
          if (name === "segment_end") {
            completedSegments += 1;
            if (completedSegments < totalSegments) nextAt += 0.2;
          }
          if (name === "done") doneEvent = true;
          if (name === "error") throw new Error(data.message || "VieNeu lỗi tạo âm thanh");
        }
        if (done) break;
      }
      if (!doneEvent) throw new Error("Luồng VieNeu kết thúc sớm");
      await new Promise((resolve) => setTimeout(resolve, Math.max(0, (nextAt - playback.currentTime) * 1000)));
      if (generation !== playbackGeneration) return;
      setStage("tts", acknowledgement
        ? `đã xác nhận · chờ AI · khung đầu ${firstFrameMs} ms`
        : `xong ${completedSegments} câu · khung đầu ${firstFrameMs} ms · ${frames} khung`);
      label.textContent = acknowledgement ? "VieNeu · đang chờ kết quả tra cứu" : "Giọng trả lời: VieNeu · Trúc Ly";
      stopButton.hidden = true;
    } catch (error) {
      if (error.name !== "AbortError" && generation === playbackGeneration) {
        setStage("tts", `lỗi: ${error.message}`);
        label.textContent = "VieNeu chưa phát được";
        stopButton.hidden = true;
      }
    }
  }

  recordButton.addEventListener("click", () => capture ? stopRecording() : startRecording());
  stopButton.addEventListener("click", () => { stopPlayback(); setStage("tts", "đã dừng phát"); });
  render();
  window.TeleSaleSpeech = {
    primePlayback, speak, stopPlayback, setStage, checkHealth,
    acknowledge() { return speak(ACKNOWLEDGEMENT, {acknowledgement: true}); },
    setTranscriptHandler(handler) { onTranscript = handler; },
    setCanRecord(handler) { canRecord = handler; },
  };
})();
