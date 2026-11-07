"""GPU selection and exactly three startup warmups, without model inference."""
import asyncio
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import numpy as np
from unittest.mock import Mock, patch

from speech.serving.models import Models


class ASRStartupTests(unittest.TestCase):
    def initialize(self, provider=None, decode_error=None, wheel='1.13.8+cuda13.cudnn9.onnxruntime1.28.2',
                   tts_execution_provider='CUDAExecutionProvider', tts_error=None):
        recognizer = Mock()
        recognizer.create_stream.side_effect = lambda: SimpleNamespace(
            accept_waveform=Mock(), result=SimpleNamespace(text=''))
        if decode_error:
            recognizer.decode_stream.side_effect = decode_error
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / 'gipformer'
            directory.mkdir()
            for name in ('encoder', 'decoder', 'joiner'):
                for suffix in ('.onnx', '.int8.onnx'):
                    (directory / (name + suffix)).touch()
            (directory / 'tokens.txt').touch()
            (root / 'silero_vad.onnx').touch()
            env = dict(os.environ)
            for name in ('SPEECH_ASR_PROVIDER', 'SPEECH_VAD_PROVIDER', 'SPEECH_TTS_PROVIDER'):
                env.pop(name, None)
            if provider is not None:
                env['SPEECH_ASR_PROVIDER'] = provider
            tts = Mock()
            tts.synthesize.return_value = (np.zeros(441, dtype=np.float32), .01)
            if tts_error:
                tts.synthesize.side_effect = tts_error
            for name in ('duration_predictor', 'text_encoder', 'vector_estimator', 'vocoder'):
                getattr(tts.sessions, name).get_providers.return_value = [tts_execution_provider, 'CPUExecutionProvider']
            with patch.dict(os.environ, env, clear=True), \
                 patch('speech.serving.models.version', return_value=wheel), \
                 patch('speech.serving.models.sherpa_onnx.OfflineRecognizer.from_transducer', return_value=recognizer) as factory, \
                 patch.object(Models, 'segments', return_value=[]), \
                 patch.dict('sys.modules', {'korvatts': SimpleNamespace(TTS=Mock(return_value=tts))}):
                model = Models(root)
                return model, recognizer, factory.call_args.kwargs

    def test_default_cuda_uses_fp32_and_warms_up_three_times(self):
        model, recognizer, config = self.initialize()
        self.assertEqual(config['provider'], 'cuda')
        self.assertTrue(config['encoder'].endswith('/encoder.onnx'))
        self.assertTrue(config['decoder'].endswith('/decoder.onnx'))
        self.assertTrue(config['joiner'].endswith('/joiner.onnx'))
        self.assertEqual(recognizer.decode_stream.call_count, 3)
        self.assertEqual(recognizer.create_stream.call_count, 3)
        self.assertEqual(model.asr_warmup_runs, 3)
        self.assertEqual(model.asr_provider, 'cuda')
        for call in recognizer.decode_stream.call_args_list:
            rate, samples = call.args[0].accept_waveform.call_args.args
            self.assertEqual(rate, 16000)
            self.assertEqual(samples.shape, (16000,))

    def test_explicit_cpu_retains_int8_and_still_warms_up_three_times(self):
        model, recognizer, config = self.initialize('cpu', wheel='1.13.8')
        self.assertEqual(config['provider'], 'cpu')
        self.assertTrue(config['encoder'].endswith('/encoder.int8.onnx'))
        self.assertEqual(recognizer.decode_stream.call_count, 3)
        self.assertEqual(model.asr_warmup_runs, 3)

    def test_cuda_rejects_cpu_only_wheel_instead_of_silent_fallback(self):
        with self.assertRaisesRegex(RuntimeError, 'CUDA-enabled'):
            self.initialize(wheel='1.13.8')

    def test_invalid_provider_and_warmup_failure_abort_initialization(self):
        with self.assertRaisesRegex(ValueError, 'SPEECH_ASR_PROVIDER'):
            self.initialize('auto')
        with self.assertRaisesRegex(RuntimeError, 'warmup failed'):
            self.initialize(decode_error=[None, RuntimeError('warmup failed')])

    def test_startup_does_not_publish_models_after_failed_warmup(self):
        from speech.serving import app as api
        with patch.object(api, 'models', None), \
             patch.object(api, 'Models', side_effect=RuntimeError('warmup failed')):
            with self.assertRaisesRegex(RuntimeError, 'warmup failed'):
                asyncio.run(api.startup())
            self.assertEqual(api.health()['status'], 'loading')
