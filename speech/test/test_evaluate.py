"""Chấm một lần chạy ASR bằng ``reference_eval.wer_cer`` của BTC và các số đo phụ."""
import json
import tempfile
import unittest
import warnings
from pathlib import Path

from speech.__main__ import _dataset_ground_truth
from speech.btc import find_data_dir, load_reference_eval, text_sha256
from speech.evaluate import asr_time, coverage, ground_truth_check, markdown_table, score_run
from speech.normalize import rules_fingerprint

BTC_DIR = find_data_dir(required=False)


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class CoverageAndTimingTests(unittest.TestCase):
    GT = {"dialogues": [{"id": "X1"}, {"id": "X2"}]}

    def test_missing_dialogue_is_an_error_not_a_skipped_row(self):
        with self.assertRaisesRegex(ValueError, "X2"):
            coverage(self.GT, {"X1": {"text": "dạ"}})

    def test_counts_empty_and_extra_transcripts(self):
        counts = coverage(self.GT, {"X1": {"text": "dạ"}, "X2": {"text": " "}, "Y9": {"text": "alo"}})
        self.assertEqual(counts, {"expected": 2, "processed": 2, "empty": 1, "extra": ["Y9"]})

    def test_asr_seconds_per_audio_minute(self):
        hyps = {"X1": {"meta": {"audio_s": 60.0, "asr_s": 30.0}}, "X2": {"meta": {"audio_s": 120.0, "asr_s": 180.0}}}
        timing = asr_time(hyps, {"load_s": 4.2})
        self.assertEqual((timing["s_per_audio_min"], timing["p50"], timing["audio_min"], timing["load_s"]),
                         (70.0, 60.0, 3.0, 4.2))
        self.assertIsNone(asr_time({"X1": {}}, {}))


class GroundTruthCheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dataset = Path(self._tmp.name) / "dataset"
        write(self.dataset / "ground_truth.json", {"dialogues": [{"id": "T02", "full_text": "dạ chào chị"}]})

    def tearDown(self):
        self._tmp.cleanup()

    def test_same_id_but_different_ground_truth_is_detected(self):
        recorded = text_sha256(self.dataset / "ground_truth.json")
        self.assertIs(ground_truth_check(self.dataset, {"ground_truth_sha256": recorded}), True)
        write(self.dataset / "ground_truth.json", {"dialogues": [{"id": "T02", "full_text": "dạ chào anh"}]})
        self.assertIs(ground_truth_check(self.dataset, {"ground_truth_sha256": recorded}), False)

    def test_old_run_without_hash_cannot_be_checked(self):
        self.assertIsNone(ground_truth_check(self.dataset, {}))
        self.assertIsNone(ground_truth_check(self.dataset, {"ground_truth_sha256": None}))

    def test_hash_ignores_crlf(self):
        lf, crlf = Path(self._tmp.name) / "lf.json", Path(self._tmp.name) / "crlf.json"
        lf.write_bytes(b'{\n "a": 1\n}\n')
        crlf.write_bytes(b'{\r\n "a": 1\r\n}\r\n')
        self.assertEqual(text_sha256(lf), text_sha256(crlf))

    def test_transcribe_finds_ground_truth_next_to_audio_dir_or_file(self):
        audio = self.dataset / "audio"
        audio.mkdir()
        (audio / "T02.wav").write_bytes(b"")
        self.assertEqual(_dataset_ground_truth(audio), self.dataset / "ground_truth.json")
        self.assertEqual(_dataset_ground_truth(audio / "T02.wav"), self.dataset / "ground_truth.json")
        self.assertIsNone(_dataset_ground_truth(Path(self._tmp.name)))


@unittest.skipUnless(BTC_DIR, "cần dữ liệu BTC (BTC_DATA_DIR)")
class ScoreRunTests(unittest.TestCase):
    def test_official_scores_raw_wer_and_per_dialogue_details(self):
        spoken = "dạ máy này giá năm triệu hai trăm nghìn anh chốt cê ô đê nha"
        ground_truth = {"reference_date": "2026-10-15", "dialogues": [{
            "id": "X1", "noisy": False, "full_text": spoken, "entities": {"price_vnd": 5200000, "payment": "COD"},
            "turns": [{"idx": 1, "speaker": "A", "text": spoken}]}]}
        hypotheses = {"X1": {"text": spoken, "entities": {"price_vnd": 5200000, "payment": "COD"},
                             "asr_segments": [{"raw": "Dạ máy này giá 5.200.000 anh chốt kê ô đê nha"}],
                             "meta": {"rtf": 0.5}}}
        with tempfile.TemporaryDirectory() as tmp:
            dataset, run = Path(tmp) / "dataset", Path(tmp) / "run"
            write(dataset / "ground_truth.json", ground_truth)
            write(run / "hypotheses.json", hypotheses)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ResourceWarning)  # script BTC mở file không đóng
                report = score_run(dataset, run, load_reference_eval(BTC_DIR), catalog=())
                self.assertTrue(report["rules_stale"])  # không có run.json → không biết bộ luật nào
                self.assertIsNone(report["ground_truth_match"])
                write(run / "run.json", {**rules_fingerprint(),
                                         "ground_truth_sha256": text_sha256(dataset / "ground_truth.json")})
                again = score_run(dataset, run, load_reference_eval(BTC_DIR), catalog=())
                self.assertFalse(again["rules_stale"])
                self.assertIs(again["ground_truth_match"], True)
            self.assertTrue((run / "score.json").is_file())

        self.assertEqual((report["official"]["WER"], report["official"]["entity_accuracy"]), (0.0, 100.0))
        self.assertGreater(report["wer_raw"], 0.0)
        self.assertEqual(report["oracle_entity_accuracy"], 100.0)
        self.assertEqual(report["per_dialogue"]["X1"]["entity"], "2/2")
        self.assertEqual(report["per_dialogue"]["X1"]["rtf"], 0.5)
        self.assertIn("| run |", markdown_table([report]))


if __name__ == "__main__":
    unittest.main()
