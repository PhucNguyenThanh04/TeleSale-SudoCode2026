"""Giả lập kênh thoại, phân giọng TTS, ghép hội thoại có mốc thời gian và lọc ảo giác ASR (không gọi mạng/model)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from speech import audio as au
from speech import tts
from speech.asr import clean_hypothesis, finalize
from speech.btc import text_sha256
from speech.lexicon import load_lexicon

SR = au.SAMPLE_RATE


def tone(freq: float, seconds: float = 1.0, amplitude: float = 0.3) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def magnitude(signal: np.ndarray, freq: float) -> float:
    spectrum = np.abs(np.fft.rfft(signal))
    return float(spectrum[int(round(freq * signal.size / SR))])


class AudioTests(unittest.TestCase):
    def test_telephone_keeps_voice_band_only(self):
        mixed = tone(100) + tone(1000) + tone(6000)
        phone = au.telephone(mixed)
        self.assertEqual(phone.size, mixed.size)
        self.assertGreater(magnitude(phone, 1000), 30 * magnitude(phone, 100))
        self.assertGreater(magnitude(phone, 1000), 30 * magnitude(phone, 6000))

    def test_add_noise_reaches_requested_snr(self):
        speech = tone(300, amplitude=0.5)
        noisy = au.add_noise(speech, 10.0, np.random.default_rng(0))
        voiced = np.abs(speech) > 0.02
        snr = 20 * np.log10(np.sqrt(np.mean(speech[voiced] ** 2)) / np.sqrt(np.mean((noisy - speech) ** 2)))
        self.assertAlmostEqual(snr, 10.0, delta=0.3)

    def test_wav_round_trip(self):
        signal = tone(440, seconds=0.5)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.wav"
            au.write_wav(path, signal)
            decoded = au.decode(path)
        self.assertEqual(decoded.size, signal.size)
        self.assertLess(float(np.max(np.abs(decoded - signal))), 1e-3)


class VoiceTests(unittest.TestCase):
    CONFIG = {"edge": {"voices": {"bac_f": {"voice": "F"}, "bac_m": {"voice": "M"}, "C:bac_f": {"voice": "CF"},
                                  "nam_m": {"voice": "NM"}},
                       "roles": {"A": {"rate": "+6%"}},
                       "pronounce": {"size": "sai", "ship": "síp", "shipper": "síp pơ"}},
              "elevenlabs": {"model_id": "eleven_multilingual_v2", "voice_settings": {"stability": 0.4},
                             "voices": {"bac_m": {"voice_id": "abc"}}}}

    def test_voice_lookup_falls_back_from_region_to_northern(self):
        agent = tts.resolve_voice(self.CONFIG, "edge", "A", "nam", "m")
        self.assertEqual((agent["key"], agent["voice"], agent["rate"]), ("nam_m", "NM", "+6%"))
        self.assertEqual(tts.resolve_voice(self.CONFIG, "edge", "C", "trung", "f")["voice"], "CF")
        self.assertEqual(tts.resolve_voice(self.CONFIG, "edge", "A", "trung", "f")["voice"], "F")
        with self.assertRaises(KeyError):
            tts.resolve_voice(self.CONFIG, "edge", "A", "nam", "x")

    def test_elevenlabs_voice_gets_section_defaults(self):
        voice = tts.resolve_voice(self.CONFIG, "elevenlabs", "C", "nam", "m")
        self.assertEqual((voice["voice_id"], voice["model_id"]), ("abc", "eleven_multilingual_v2"))
        self.assertEqual(voice["voice_settings"], {"stability": 0.4})

    def test_respell_replaces_whole_words_longest_first(self):
        mapping = self.CONFIG["edge"]["pronounce"]
        self.assertEqual(tts.respell("Shipper ship sizes Size", mapping), "síp pơ síp sizes sai")

    def test_vieneu_engine_passes_voice_and_resamples_to_16k(self):
        class FakeVieneu:
            sample_rate = 48_000

            def __init__(self, mode: str):
                self.mode = mode

            def infer(self, text: str, voice: str, **kwargs):
                FakeVieneu.call = (self.mode, text, voice, kwargs)
                return tone(440, seconds=0.5).repeat(3)  # 24 000 mẫu = 0,5 s ở 48 kHz

        with mock.patch.dict("sys.modules", {"vieneu": mock.Mock(Vieneu=FakeVieneu)}), \
                mock.patch.dict(tts._VIENEU_MODELS, clear=True):
            clip = tts._vieneu("dạ size m ạ", {"key": "bac_f", "voice": "Trúc Ly", "temperature": 0.2})
        self.assertEqual(FakeVieneu.call, ("v3turbo", "dạ size m ạ", "Trúc Ly", {"temperature": 0.2}))
        self.assertAlmostEqual(clip.size / SR, 0.5, delta=0.01)


class SynthDatasetTests(unittest.TestCase):
    SOURCE = {"reference_date": "2026-10-15", "dialogues": [{
        "id": "T9", "agent_region": "bac", "agent_gender": "f", "customer_region": "nam", "customer_gender": "m",
        "turns": [{"idx": 1, "speaker": "A", "text": "dạ shop chào anh", "tts_text": "dạ sóp chào anh"},
                  {"idx": 2, "speaker": "C", "text": "phí ship bao nhiêu em"}]}]}

    def test_dialogue_audio_segments_and_ground_truth(self):
        calls = []

        def fake_engine(text: str, params: dict) -> np.ndarray:
            calls.append((text, params["voice"]))
            return np.full(800 * len(text), 0.5, dtype=np.float32)  # 0,05 s mỗi ký tự

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(tts.ENGINES, {"edge": fake_engine}):
            out, cache = Path(tmp) / "ds", Path(tmp) / "cache"
            manifest = tts.synth_dataset(self.SOURCE, out, engine="edge", config=VoiceTests.CONFIG,
                                         cache_dir=cache, channel="none")
            again = tts.synth_dataset(self.SOURCE, Path(tmp) / "ds2", engine="edge", config=VoiceTests.CONFIG,
                                      cache_dir=cache, channel="none")
            segments = json.loads((out / "audio" / "T9.segments.json").read_text(encoding="utf-8"))["segments"]
            ground_truth = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))
            duration = au.decode(out / "audio" / "T9.wav").size / SR

        self.assertEqual(calls, [("dạ sóp chào anh", "F"), ("phí síp bao nhiêu em", "NM")])
        self.assertEqual(manifest["new_chars_synthesized"], len("dạ sóp chào anh") + len("phí síp bao nhiêu em"))
        self.assertEqual(again["new_chars_synthesized"], 0)
        self.assertEqual([s["speaker"] for s in segments], ["A", "C"])
        self.assertEqual(segments[0]["start"], 0.3)
        self.assertAlmostEqual(segments[0]["end"] - segments[0]["start"], 0.05 * len("dạ sóp chào anh"), places=2)
        self.assertGreater(segments[1]["start"], segments[0]["end"])
        self.assertGreater(duration, segments[1]["end"])
        dialogue = ground_truth["dialogues"][0]
        self.assertEqual(ground_truth["reference_date"], "2026-10-15")
        self.assertEqual(dialogue["full_text"], "dạ shop chào anh phí ship bao nhiêu em")
        self.assertNotIn("tts_text", dialogue["turns"][0])

    def test_manifest_records_provenance_and_ground_truth_hash(self):
        provenance = {"source": {"file": "/scripts/team.json", "sha256": "abc"}, "noise": None,
                      "team_preview": False}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(tts.ENGINES, {"edge": lambda text, params: tone(440, seconds=0.2)}):
            out = Path(tmp) / "ds"
            manifest = tts.synth_dataset(self.SOURCE, out, engine="edge", config=VoiceTests.CONFIG,
                                         cache_dir=Path(tmp) / "cache", channel="none", provenance=provenance)
            written = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            gt_hash = text_sha256(out / "ground_truth.json")
        self.assertEqual(written["source"], provenance["source"])
        self.assertEqual(manifest["ground_truth_sha256"], gt_hash)
        self.assertEqual(written["ground_truth_sha256"], gt_hash)
        self.assertEqual([d["id"] for d in written["dialogues"]], ["T9"])
        self.assertNotIn("clips", written)  # chỉ engine files mới ghi danh sách clip
        self.assertNotIn(tmp, json.dumps(written, ensure_ascii=False))


class AsrPostprocessTests(unittest.TestCase):
    def test_drops_known_whisper_hallucinations(self):
        self.assertEqual(clean_hypothesis("Hãy subscribe cho kênh Ghiền Mì Gõ"), "")

    def test_collapses_repeated_ngrams(self):
        self.assertEqual(clean_hypothesis("dạ vâng dạ vâng dạ vâng dạ vâng dạ vâng"), "dạ vâng")

    def test_drops_hotword_list_echo_but_keeps_real_sentences(self):
        terms = frozenset({"airpure", "xiaomi", "karofi", "runlite"})
        self.assertEqual(clean_hypothesis("AirPure, Xiaomi, Karofi, RunLite", terms), "")
        self.assertEqual(clean_hypothesis("anh lấy máy Xiaomi nhé", terms), "anh lấy máy Xiaomi nhé")

    def test_finalize_skips_noise_and_builds_both_forms(self):
        def piece(raw: str, start: float, logprob: float = -0.2, no_speech: float = 0.1) -> dict:
            return {"start": start, "end": start + 1, "raw": raw, "lang": "vi", "avg_logprob": logprob,
                    "no_speech_prob": no_speech}

        record = finalize([piece("Thanks for watching!", 0), piece("ừm", 1, logprob=-1.5, no_speech=0.9),
                           piece("anh chốt kê ô đê giá 5.200.000 nha", 2)], load_lexicon())
        self.assertEqual(record["text"], "anh chốt cê ô đê giá năm triệu hai trăm nghìn nha")
        self.assertEqual(record["entities"], {"payment": "COD", "price_vnd": 5200000})
        self.assertEqual([s["text_written"] for s in record["asr_segments"]], ["anh chốt COD giá 5.200.000 nha"])


if __name__ == "__main__":
    unittest.main()
