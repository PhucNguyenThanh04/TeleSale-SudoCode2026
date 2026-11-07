"""Reuse B2 text cleanup for Gipformer without Whisper or model weights."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from fastapi.testclient import TestClient

from speech.asr import finalize
from speech.normalize import default_lexicon
from speech.serving.models import Models
from .test_listen import FakeVad, client_for, send_turn


def fake_model(text):
    model = Models.__new__(Models)
    model.recognizer = SimpleNamespace(
        create_stream=lambda: SimpleNamespace(accept_waveform=Mock(), result=SimpleNamespace(text=text)),
        decode_stream=Mock(),
    )
    model.create_vad = lambda: (FakeVad(), 320)
    return model


class STTPostprocessTests(unittest.TestCase):
    def test_lexicon_and_itn_return_written_text_for_agent(self):
        model = fake_model('dạ anh chốt kê ô đê đơn bốn triệu rưỡi nha')
        self.assertEqual(model.transcribe_segment(np.zeros(3200, dtype=np.float32)),
                         'dạ anh chốt COD đơn 4,5 triệu nha')

    def test_matches_b2_written_postprocessing_without_whisper_scores(self):
        for raw in ('anh lấy máy e pia y nhé', 'anh chốt kê ô đê giá 5.200.000 nha',
                    'dạ vâng dạ vâng dạ vâng dạ vâng dạ vâng',
                    'Hãy subscribe cho kênh Ghiền Mì Gõ', '   '):
            with self.subTest(raw=raw):
                offline = finalize([{'raw': raw, 'start': 0, 'end': 1, 'lang': 'vi',
                                     'avg_logprob': -.2, 'no_speech_prob': .1}], default_lexicon())
                expected = ' '.join(segment['text_written'] for segment in offline['asr_segments'])
                self.assertEqual(fake_model(raw).transcribe_segment(np.zeros(3200, dtype=np.float32)),
                                 expected)

    def test_no_hotword_echo_filter_without_hotword_prompt(self):
        # A real comparison of brands must not be erased as a decoder prompt echo.
        result = fake_model('AirPure, Xiaomi, Karofi, RunLite').transcribe_segment(
            np.zeros(3200, dtype=np.float32))
        self.assertIn('AirPure', result)
        self.assertIn('Karofi', result)

    def test_rest_wav_endpoint_uses_same_written_text_for_segments_and_summary(self):
        from speech.serving import app as api
        audio = np.zeros(3200, dtype=np.float32)
        model = fake_model('anh chốt kê ô đê đơn bốn triệu rưỡi nha')
        model.segments = lambda samples: [(0.0, samples)]
        with patch.object(api, 'models', model), patch.object(api, 'read_wav', return_value=audio):
            response = TestClient(api.app).post('/v1/speech/transcribe', content=b'offline-wav',
                                               headers={'Content-Type': 'audio/wav'})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['text'], 'anh chốt COD đơn 4,5 triệu nha')
        self.assertEqual(result['segments'], [{'start_s': 0.0, 'end_s': .2, 'text': result['text']}])

    def test_websocket_filters_hallucination_then_accepts_next_turn(self):
        model = fake_model('Thanks for watching!')
        with client_for(model) as client, client.websocket_connect('/listen') as ws:
            self.assertEqual(ws.receive_json()['event'], 'ready')
            send_turn(ws)
            first = [ws.receive_json() for _ in range(3)][-1]
            self.assertEqual(first['event'], 'transcript_final')
            self.assertEqual(first['text'], '')
            model.recognizer.create_stream = lambda: SimpleNamespace(
                accept_waveform=Mock(), result=SimpleNamespace(text='anh chốt kê ô đê đơn bốn triệu rưỡi nha'))
            send_turn(ws)
            second = [ws.receive_json() for _ in range(3)][-1]
            self.assertEqual(second['turn_id'], 'turn-2')
            self.assertEqual(second['text'], 'anh chốt COD đơn 4,5 triệu nha')
