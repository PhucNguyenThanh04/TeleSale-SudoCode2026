"""Run the real browser audio scheduler against a deterministic audio clock."""
from test_voice_browser import site, browser, open_site


def test_interrupt_clears_queued_audio_marks_and_resets_clock(site, browser):
    js = open_site(browser, site[0])
    assert js(r'''(async () => {
      const { PCMPlayer } = await import('/assets/audio.js');
      const assert = { equal(a, b) { if (a !== b) throw Error(`${a} != ${b}`); } };
      const callbacks = new Map(); let next = 0;
      globalThis.setTimeout = callback => { callbacks.set(++next, callback); return next; };
      globalThis.clearTimeout = id => callbacks.delete(id);
      const sources = [];
      const context = { currentTime: 0, state: 'running', destination: {},
        createBuffer(channels, size, rate) {
          return { duration: size / rate, getChannelData: () => new Float32Array(size) };
        },
        createBufferSource() {
          const source = { connect() {}, disconnect() {}, stop() { this.stopped = true; },
            start(time) { this.startTime = time; } };
          sources.push(source); return source;
        },
      };
      const player = new PCMPlayer(context);
      const audio = { format: { encoding: 'pcm_s16le', channels: 1, sample_rate: 16000 },
        audio_base64: btoa(String.fromCharCode(...new Uint8Array(32000))) };
      player.enqueue(audio);
      let played = 0; player.mark(() => played++);
      assert.equal(played, 0);
      context.currentTime = 0.5;
      for (const [id, fn] of [...callbacks]) { callbacks.delete(id); fn(); }
      assert.equal(played, 0);
      player.stop();
      assert.equal(sources[0].stopped, true);
      assert.equal(callbacks.size, 0);
      context.currentTime = 10;
      player.enqueue(audio);
      assert.equal(sources[1].startTime, 10.025);
      player.mark(() => played++);
      context.currentTime = 11.1;
      for (const [id, fn] of [...callbacks]) { callbacks.delete(id); fn(); }
      assert.equal(played, 1);
      player.stop();
      return true;
    })()''')
