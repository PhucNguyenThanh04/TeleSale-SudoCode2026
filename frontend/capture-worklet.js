class CallCapture extends AudioWorkletProcessor {
  process(inputs, outputs) {
    // Silent output keeps this node running without monitoring the microphone.
    const channels = inputs[0];
    if (channels?.length) {
      const mono = new Float32Array(channels[0].length);
      for (const channel of channels) {
        for (let i = 0; i < mono.length; i++) mono[i] += channel[i] / channels.length;
      }
      this.port.postMessage(mono, [mono.buffer]);
    }
    return true;
  }
}
registerProcessor('call-capture', CallCapture);
