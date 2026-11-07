// Keep fractional positions across worklet blocks (including 44.1 kHz devices).
export class PCMEncoder {
  constructor(sampleRate, targetRate = 16000, chunkSize = 800) {
    this.ratio = sampleRate / targetRate;
    this.chunkSize = chunkSize;
    this.pending = [];
    this.position = 0;
    this.chunk = [];
  }
  push(samples) {
    this.pending.push(...samples);
    const chunks = [];
    while (this.position + 1 < this.pending.length) {
      const i = Math.floor(this.position);
      const fraction = this.position - i;
      const value = Math.max(-1, Math.min(1,
        this.pending[i] * (1 - fraction) + this.pending[i + 1] * fraction));
      this.chunk.push(Math.round(value * (value < 0 ? 32768 : 32767)));
      this.position += this.ratio;
      if (this.chunk.length === this.chunkSize) {
        const bytes = new ArrayBuffer(this.chunkSize * 2);
        const view = new DataView(bytes);
        this.chunk.forEach((sample, j) => view.setInt16(j * 2, sample, true));
        chunks.push(bytes);
        this.chunk = [];
      }
    }
    const consumed = Math.min(Math.floor(this.position), this.pending.length);
    this.pending = this.pending.slice(consumed);
    this.position -= consumed;
    return chunks;
  }
}

export class PCMPlayer {
  constructor(context) {
    this.context = context;
    this.until = 0;
    this.sources = new Set();
    this.timer = null;
  }
  enqueue(event) {
    if (event.format.encoding !== 'pcm_s16le' || event.format.channels !== 1) {
      throw new Error('Định dạng âm thanh trả về không được hỗ trợ.');
    }
    const raw = Uint8Array.from(atob(event.audio_base64), c => c.charCodeAt(0));
    if (raw.length % 2) throw new Error('Âm thanh trả về không hợp lệ.');
    const view = new DataView(raw.buffer);
    const buffer = this.context.createBuffer(1, raw.length / 2, event.format.sample_rate);
    const output = buffer.getChannelData(0);
    for (let i = 0; i < output.length; i++) output[i] = view.getInt16(i * 2, true) / 32768;
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.context.destination);
    this.sources.add(source);
    source.onended = () => { this.sources.delete(source); source.disconnect(); };
    const start = Math.max(this.context.currentTime + 0.025, this.until);
    source.start(start);
    this.until = start + buffer.duration;
  }
  pause(milliseconds) {
    this.until = Math.max(this.context.currentTime, this.until) + milliseconds / 1000;
  }
  finish(callback) {
    // Check the audio clock, since a suspended/background context may stop advancing.
    const check = () => {
      if (this.context.state === 'closed') return;
      if (this.context.currentTime >= this.until && this.sources.size === 0) callback();
      else this.timer = setTimeout(check, 40);
    };
    clearTimeout(this.timer);
    check();
  }
  stop() {
    clearTimeout(this.timer);
    for (const source of this.sources) { source.stop(); source.disconnect(); }
    this.sources.clear();
  }
}
