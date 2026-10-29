const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const elements = {
  player: {pause() {}, play() { plays.push(this.src); return Promise.resolve(); }, onended: null},
  speak: {disabled: false},
  ttsDebug: {textContent: ''},
  text: {value: 'Câu một. Câu hai.'},
  voice: {value: 'khanh_vy', innerHTML: '<option value="khanh_vy">Khánh Vy</option>'},
  engine: {value: 'korva'},
};
const plays = [];
const delays = [];
let resumeStream;
let resumeTimer;
let reads = 0;
let urlNumber = 0;
const encode = text => new TextEncoder().encode(text);
const segment = (index, text) => `event: segment\ndata: ${JSON.stringify({index, text, audio_base64: Buffer.from('RIFF').toString('base64'), tts_ms: 100, audio_s: 0.5})}\n\n`;

const context = {
  $: id => elements[id],
  api: '',
  AbortController,
  Blob,
  TextDecoder,
  Uint8Array,
  atob: value => Buffer.from(value, 'base64').toString('binary'),
  URL: {createObjectURL: () => `blob:${++urlNumber}`, revokeObjectURL() {}},
  window: {setTimeout(fn, ms) {delays.push(ms); resumeTimer = fn; return 1;}, clearTimeout() {}},
  fetch: async () => ({
    ok: true,
    body: {getReader: () => ({read: () => {
      reads += 1;
      if (reads === 1) return Promise.resolve({done: false, value: encode(`event: start\ndata: {"segments_total":2,"pause_ms":200}\n\n${segment(0, 'Câu một.')}`)});
      if (reads === 2) return new Promise(resolve => {resumeStream = resolve;});
      return Promise.resolve({done: true});
    }})},
  }),
};

vm.runInNewContext(fs.readFileSync(__dirname + '/tts.js', 'utf8'), context);

(async () => {
  const request = elements.speak.onclick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(plays.length, 1, 'first sentence must play before the second is synthesized');
  assert.equal(reads, 2, 'client must keep reading the stream while sentence one plays');

  resumeStream({done: false, value: encode(`${segment(1, 'Câu hai.')}event: done\ndata: {"segments_total":2}\n\n`)});
  await request;
  assert.equal(plays.length, 1, 'queued sentence must wait for the first audio to end');
  elements.player.onended();
  assert.deepEqual(delays, [200]);
  assert.equal(plays.length, 1, 'queued sentence must wait for the 200 ms timer');
  resumeTimer();
  assert.equal(plays.length, 2);
  elements.player.onended();
  resumeTimer();
  assert.equal(elements.speak.disabled, false);
  console.log('TTS stream queue and 200 ms pause: OK');
})().catch(error => { console.error(error); process.exitCode = 1; });
