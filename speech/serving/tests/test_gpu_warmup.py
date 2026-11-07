"""VAD/TTS CUDA startup and three warmups without downloading model weights."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from speech.serving import vieneu_sidecar as sidecar
from . import test_asr_startup as startup_helpers


class GPUWarmupTests(unittest.TestCase):
    def test_main_service_warms_vad_and_korva_three_times(self):
        model, _, _ = startup_helpers.ASRStartupTests().initialize()
        self.assertEqual(model.vad_config.provider, 'cuda')
        self.assertEqual(model.vad_warmup_runs, 3)
        self.assertEqual(model.tts_provider, 'cuda')
        self.assertEqual(model.tts_warmup_runs, 3)
        self.assertEqual(model.tts.synthesize.call_count, 3)

    def test_korva_cpu_fallback_and_warmup_failure_abort_startup(self):
        with self.assertRaisesRegex(RuntimeError, 'did not initialize on CUDA'):
            startup_helpers.ASRStartupTests().initialize(tts_execution_provider='CPUExecutionProvider')
        with self.assertRaisesRegex(RuntimeError, 'Korva warmup failed'):
            startup_helpers.ASRStartupTests().initialize(tts_error=RuntimeError('Korva warmup failed'))

    def test_sidecar_publishes_only_after_three_complete_gpu_streams(self):
        candidate = Mock()
        candidate.engine.device.type = 'cuda'
        candidate.engine.dtype = 'torch.bfloat16'
        candidate.backend = 'pytorch'
        candidate.list_preset_voices.return_value = [('Trúc Ly', 'Trúc Ly')]
        def frames(*args, **kwargs):
            self.assertIsNone(sidecar.model)
            yield np.zeros(480, dtype=np.float32)
        candidate.infer_stream.side_effect = frames
        factory = Mock(return_value=candidate)
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True))
        with patch.dict('sys.modules', {'vieneu': SimpleNamespace(Vieneu=factory), 'torch': torch}), \
             patch.dict('os.environ', {'SPEECH_TTS_PROVIDER': 'cuda'}), \
             patch.object(sidecar, 'model', None), patch.object(sidecar, 'voices', []), \
             patch.object(sidecar, 'tts_provider', None), patch.object(sidecar, 'tts_warmup_runs', 0):
            sidecar.load_model()
            self.assertIs(sidecar.model, candidate)
            self.assertEqual(candidate.infer_stream.call_count, 3)
            self.assertEqual(factory.call_args.kwargs['device'], 'cuda')
            self.assertEqual(factory.call_args.kwargs['backend'], 'pytorch')
            self.assertEqual(factory.call_args.kwargs['max_streams'], 1)
            self.assertEqual(sidecar.health()['tts_warmup_runs'], 3)
            self.assertEqual(sidecar.health()['tts_provider'], 'cuda')

    def test_sidecar_warmup_failure_does_not_publish_model(self):
        candidate = Mock()
        candidate.engine.device.type = 'cuda'
        candidate.backend = 'pytorch'
        candidate.list_preset_voices.return_value = [('Trúc Ly', 'Trúc Ly')]
        candidate.infer_stream.side_effect = RuntimeError('warmup failed')
        with patch.dict('sys.modules', {'vieneu': SimpleNamespace(Vieneu=Mock(return_value=candidate)),
                                        'torch': SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True))}), \
             patch.dict('os.environ', {'SPEECH_TTS_PROVIDER': 'cuda'}), \
             patch.object(sidecar, 'model', None):
            with self.assertRaisesRegex(RuntimeError, 'warmup failed'):
                sidecar.load_model()
            self.assertIsNone(sidecar.model)
