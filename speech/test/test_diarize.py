import unittest

import numpy as np

from speech import asr
from speech.diarize import features, split_by_speaker


class DiarizeTests(unittest.TestCase):
    def test_split_cuts_mid_silence_between_speakers(self):
        turns = [{"start": 0, "end": 1000, "speaker": "A"}, {"start": 1400, "end": 3000, "speaker": "C"}]
        self.assertEqual(split_by_speaker(0, 3000, turns), [(0, 1200, "A"), (1200, 3000, "C")])
        self.assertEqual(split_by_speaker(1500, 2500, turns), [(1500, 2500, "C")])
        self.assertEqual(split_by_speaker(0, 500, []), [(0, 500, None)])

    def test_words_assigned_to_speaker_part_by_midpoint(self):
        from types import SimpleNamespace as W
        seg = W(words=[W(word=" dạ", start=0.0, end=0.2), W(word=" vâng", start=0.3, end=0.6),
                       W(word=" alo", start=1.3, end=1.6)])
        parts = [(16000, 16000 + 12000, "A"), (16000 + 12000, 16000 + 32000, "C")]
        self.assertEqual(asr._split_words([seg], 16000, parts),
                         [(16000, 28000, "A", "dạ vâng"), (28000, 48000, "C", "alo")])

    def test_features_separate_spectral_shapes(self):
        sr = 16000
        t = np.arange(sr) / sr
        low = np.sin(2 * np.pi * 180 * t).astype(np.float32)
        high = np.sin(2 * np.pi * 1800 * t).astype(np.float32)
        self.assertGreater(np.linalg.norm(features(low) - features(high)),
                           np.linalg.norm(features(low) - features(0.3 * low)))

    def test_finalize_merges_same_speaker_into_indexed_turns(self):
        pieces = [{"start": 0.0, "end": 1.0, "raw": "dạ shop xin nghe", "lang": "vi", "avg_logprob": -0.1,
                   "no_speech_prob": 0.0, "speaker": "A"},
                  {"start": 1.2, "end": 2.0, "raw": "em chào chị", "lang": "vi", "avg_logprob": -0.1,
                   "no_speech_prob": 0.0, "speaker": "A"},
                  {"start": 2.5, "end": 4.0, "raw": "chị trả tiền mặt khi nhận hàng", "lang": "vi",
                   "avg_logprob": -0.1, "no_speech_prob": 0.0, "speaker": "C"}]
        out = asr.finalize(pieces, asr.default_lexicon())
        self.assertEqual([(t["idx"], t["speaker"]) for t in out["turns"]], [(1, "A"), (2, "C")])
        self.assertEqual(out["turns"][0]["text"], "dạ shop xin nghe em chào chị")
        self.assertEqual((out["turns"][1]["start"], out["turns"][1]["end"]), (2.5, 4.0))
        self.assertIn("entities", out["turns"][1])

    def test_finalize_without_speakers_keeps_old_format(self):
        pieces = [{"start": 0.0, "end": 1.0, "raw": "alo", "lang": "vi", "avg_logprob": -0.1, "no_speech_prob": 0.0}]
        self.assertNotIn("turns", asr.finalize(pieces, asr.default_lexicon()))


if __name__ == "__main__":
    unittest.main()
