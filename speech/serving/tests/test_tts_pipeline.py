"""TTS model boundaries must use Vietnamese spoken text, without loading weights."""
import json
import unittest
from unittest.mock import Mock, patch

import numpy as np
from fastapi.testclient import TestClient

from speech.serving import vieneu_sidecar as sidecar
from speech.serving.models import Models
from speech.text.tts import prepare_tts_text


class TTSTextTests(unittest.TestCase):
    def test_numbers_units_brands_and_acronyms_keep_sentence_punctuation(self):
        self.assertEqual(
            prepare_tts_text("AirPure giá 5.200.000đ. Phòng 25m2, trả COD nhé!"),
            "e pia giá năm triệu hai trăm nghìn đồng. Phòng hai mươi lăm mét vuông, trả cê ô đê nhé!",
        )

    def test_phone_date_and_engine_pronunciation_overrides(self):
        self.assertEqual(
            prepare_tts_text("Gọi 0917223456 ngày 15/10/2026. Shipper ship sizes Size?",
                             pronounce={"size": "sai", "ship": "síp", "shipper": "síp pơ"}),
            "Gọi không chín một bảy hai hai ba bốn năm sáu ngày mười lăm tháng mười năm hai nghìn không trăm hai mươi sáu. síp pơ síp sizes sai?",
        )

    def test_does_not_apply_asr_correction_rules_to_agent_text(self):
        self.assertEqual(prepare_tts_text("Rủi ro, cá rô phi và sai rồi."),
                         "Rủi ro, cá rô phi và sai rồi.")

    def test_preparation_is_idempotent_and_empty_input_stays_empty(self):
        text = prepare_tts_text("RO 1-2-3, HEPA và COD, 25m2.")
        self.assertEqual(prepare_tts_text(text), text)
        self.assertEqual(prepare_tts_text(" \n\t "), "")

    def test_unseparated_money_is_a_price_not_an_identifier(self):
        self.assertEqual(prepare_tts_text("Giá 5200000 đồng, giảm 1000000đ."),
                         "Giá năm triệu hai trăm nghìn đồng, giảm một triệu đồng.")


class TTSModelBoundaryTests(unittest.TestCase):
    def test_korva_http_wav_sequence_stream_and_static_assets(self):
        from speech.serving import app as api
        model = Models.__new__(Models)
        model.tts = Mock()
        model.tts.synthesize.return_value = (np.zeros(4410, dtype=np.float32), .1)
        with patch.object(api, 'models', model):
            client = TestClient(api.app)
            self.assertEqual(client.get('/').status_code, 200)
            self.assertIn('javascript', client.get('/tts.js').headers['content-type'])
            body = {'text': 'AirPure giá 5.200.000đ. COD nhé!', 'voice': 'khanh_vy'}
            self.assertEqual(client.post('/v1/speech/synthesize', json=body).status_code, 200)
            sequence = client.post('/v1/speech/synthesize/sequence', json=body)
            self.assertEqual(sequence.status_code, 200)
            self.assertEqual([segment['text'] for segment in sequence.json()['segments']],
                             ['e pia giá năm triệu hai trăm nghìn đồng.', 'cê ô đê nhé!'])
            stream = client.post('/v1/speech/synthesize/stream', json=body)
            self.assertEqual(stream.status_code, 200)
            self.assertIn('event: done', stream.text)
        self.assertEqual(model.tts.synthesize.call_count, 5)
        for call in model.tts.synthesize.call_args_list:
            self.assertNotIn('AirPure', call.args[0])
            self.assertNotIn('5.200.000', call.args[0])
            self.assertNotIn('COD', call.args[0])

    def test_korva_receives_prepared_text_without_changing_sample_rate(self):
        model = Models.__new__(Models)
        model.tts = Mock()
        model.tts.synthesize.return_value = (np.zeros(4410, dtype=np.float32), .1)
        audio, debug = model.synthesize("AirPure giá 5.200.000đ, COD.", "khanh_vy")
        model.tts.synthesize.assert_called_once_with(
            "e pia giá năm triệu hai trăm nghìn đồng, cê ô đê.",
            voice="khanh_vy", lang="vi", total_steps=16)
        self.assertTrue(audio.startswith(b"RIFF"))
        self.assertEqual(debug["audio_s"], .1)

    def test_vieneu_wav_and_pcm_stream_use_the_same_prepared_text(self):
        fake = Mock()
        fake.infer.return_value = np.zeros(4800, dtype=np.float32)
        fake.infer_stream.side_effect = lambda text, **kwargs: iter([np.zeros(480, dtype=np.float32)])
        with patch.object(sidecar, 'model', fake), \
             patch.object(sidecar, 'voices', [{'id': 'Trúc Ly'}]):
            # Do not enter TestClient lifespan: that would load the real SDK/model.
            client = TestClient(sidecar.app)
            body = {"text": "AirPure giá 5.200.000đ. COD nhé!", "voice": "Trúc Ly"}
            wav = client.post('/synthesize', json=body)
            self.assertEqual(wav.status_code, 200)
            self.assertTrue(wav.content.startswith(b'RIFF'))
            response = client.post('/stream', json=body)
            self.assertEqual(response.status_code, 200)
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
            spoken = [call.args[0] for call in fake.infer_stream.call_args_list]
            self.assertEqual(' '.join(spoken), fake.infer.call_args.args[0])
            self.assertEqual(spoken, ['e pia giá năm triệu hai trăm nghìn đồng.', 'cê ô đê nhé!'])
            self.assertTrue(any('pcm16_base64' in event for event in events))
            self.assertEqual(events[-1], {'segments_total': 2})

    def test_stream_word_limit_applies_after_number_expansion(self):
        text = ' '.join(['giá 5.200.000đ'] * 10)
        with patch.object(sidecar, 'model', Mock()), \
             patch.object(sidecar, 'voices', [{'id': 'Trúc Ly'}]):
            chunks = sidecar.validate(sidecar.StreamingSpeech(text=text))
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk.split()) <= 20 for chunk in chunks))
        self.assertNotIn('5.200.000', ' '.join(chunks))
