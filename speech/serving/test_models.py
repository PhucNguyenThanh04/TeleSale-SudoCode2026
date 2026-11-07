import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
from speech.serving.models import Models


class ModelsTests(unittest.TestCase):
    def test_segment_and_rest_contract(self):
        model = Models.__new__(Models)
        stream = SimpleNamespace(accept_waveform=Mock(), result=SimpleNamespace(text=' xin chào '))
        model.recognizer = SimpleNamespace(create_stream=lambda: stream, decode_stream=Mock())
        audio = np.zeros(3200, dtype=np.float32)
        self.assertEqual(model.transcribe_segment(audio), 'xin chào')
        model.segments = lambda _: [(0.0, audio)]
        result = model.transcribe(audio)
        self.assertEqual(result['text'], 'xin chào')
        self.assertEqual(result['segments'], [{'start_s': 0.0, 'end_s': 0.2, 'text': 'xin chào'}])
        self.assertEqual(set(result['debug']), {'vad_ms', 'stt_ms', 'audio_s', 'streaming_stt'})

    def test_streaming_vad_does_not_change_rest_config(self):
        import sherpa_onnx
        from unittest.mock import patch
        model = Models.__new__(Models)
        model.vad_config = sherpa_onnx.VadModelConfig()
        model.vad_config.silero_vad.model = 'offline-test.onnx'
        model.vad_config.silero_vad.min_silence_duration = 0.35
        with patch('speech.serving.models.sherpa_onnx.VoiceActivityDetector') as detector:
            model.create_vad()
            config = detector.call_args.args[0]
            self.assertAlmostEqual(config.silero_vad.min_silence_duration, 0.7)
            self.assertAlmostEqual(config.silero_vad.min_speech_duration, 0.2)
            self.assertAlmostEqual(model.vad_config.silero_vad.min_silence_duration, 0.35)
