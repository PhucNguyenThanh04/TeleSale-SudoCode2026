"""ElevenLabs thủ công: checklist, ghép clip trong inbox, kiểm tốc độ đọc, engine ``files``."""
import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from speech import audio as au
from speech import manual, tts
from speech.__main__ import main as cli
from speech.btc import text_sha256

SR = au.SAMPLE_RATE
CONFIG = {"elevenlabs": {"model_id": "eleven_flash_v2_5",
                         "voices": {"bac_f": {"voice_id": "F" * 20, "name": "Nữ Bắc"},
                                    "C:bac_f": {"voice_id": "G" * 20, "name": "Nữ Bắc thứ hai"},
                                    "nam_m": {"voice_id": "M" * 20, "name": "Nam Nam"}}}}
DIALOGUE = {"id": "T90", "agent_region": "bac", "agent_gender": "f", "customer_region": "nam",
            "customer_gender": "m", "turns": [
                {"idx": 1, "speaker": "A", "text": "dạ em chào anh, em gọi từ cửa hàng e pia y ạ",
                 "tts_text": "dạ em chào anh, em gọi từ cửa hàng AirPure Y ạ"},
                {"idx": 2, "speaker": "C", "text": "ừ"},
                {"idx": 3, "speaker": "A", "text": "máy lọc này giá bốn triệu tám trăm nghìn anh nhé"}]}
SOURCE = {"reference_date": "2026-10-15", "dialogues": [DIALOGUE]}


def clip(seconds: float) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


class ChecklistTests(unittest.TestCase):
    def test_checklist_lists_file_voice_text_and_credits(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "inbox"
            summary = manual.export_checklist(SOURCE, out, CONFIG)
            with open(out / "checklist.csv", encoding="utf-8-sig") as fh:
                rows = list(csv.DictReader(fh))
            markdown = (out / "checklist.md").read_text(encoding="utf-8")
            self.assertTrue((out / "T90").is_dir())
        self.assertEqual([r["file"] for r in rows], ["T90/T90_01_A.mp3", "T90/T90_02_C.mp3", "T90/T90_03_A.mp3"])
        self.assertEqual(rows[0]["text"], DIALOGUE["turns"][0]["tts_text"])  # dán tts_text khi có
        self.assertEqual([r["voice"] for r in rows], ["Nữ Bắc", "Nam Nam", "Nữ Bắc"])
        chars = sum(len(t.get("tts_text") or t["text"]) for t in DIALOGUE["turns"])
        self.assertEqual(summary["chars"], chars)
        self.assertAlmostEqual(summary["credits"], chars * 0.5)
        self.assertAlmostEqual(summary["credits_web_max"], chars * 1.0)
        self.assertIn(f"| T90 | 3 | {chars} | {chars} |", markdown)
        self.assertIn("`T90/T90_03_A.mp3`", markdown)
        self.assertIn("| bac_f | Nữ Bắc |", markdown)

    def test_template_dialogues_are_rejected(self):
        template = {"dialogues": [{**DIALOGUE, "agent_voice": "tv1", "customer_voice": "tv2"}]}
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            manual.export_checklist(template, Path(tmp), CONFIG)


class InboxTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.inbox = Path(self._tmp.name)
        (self.inbox / "T90").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def touch(self, name: str, seconds: float = 1.0) -> Path:
        path = self.inbox / name
        au.write_wav(path, clip(seconds))
        return path

    def test_named_files_in_folder_or_root_and_missing_report(self):
        self.touch("T90/T90_01_A.wav")
        self.touch("T90_3_A.mp3")  # đặt thẳng ở inbox, idx không đệm số 0
        scan = manual.scan_inbox([DIALOGUE], self.inbox)
        self.assertEqual(set(scan.clips), {("T90", 1), ("T90", 3)})
        self.assertEqual(scan.missing, ["T90/T90_02_C.mp3"])
        self.assertFalse(scan.complete)

    def test_wrong_role_duplicate_and_unknown_turn(self):
        self.touch("T90/T90_01_A.mp3")
        self.touch("T90/T90_01_A.wav")
        self.touch("T90/T90_02_A.mp3")
        self.touch("T90/T90_09_C.mp3")
        scan = manual.scan_inbox([DIALOGUE], self.inbox)
        self.assertEqual(len(scan.errors), 2)  # hai file cho lượt 1; lượt 2 là vai C
        self.assertTrue(any("không có lượt 9" in e for e in scan.extra))

    def test_unrenamed_downloads_are_assigned_in_name_order(self):
        for stamp in ("10_05_09", "10_04_59", "10_05_30"):
            self.touch(f"T90/ElevenLabs_2026-10-16T{stamp}_Voice.mp3")
        scan = manual.scan_inbox([DIALOGUE], self.inbox)
        self.assertTrue(scan.complete)
        self.assertEqual([scan.clips[("T90", i)].name[22:30] for i in (1, 2, 3)],
                         ["10_04_59", "10_05_09", "10_05_30"])
        self.assertTrue(scan.notes)

    def test_wrong_number_of_unrenamed_files_is_not_guessed(self):
        self.touch("T90/a.mp3")
        self.touch("T90/b.mp3")
        scan = manual.scan_inbox([DIALOGUE], self.inbox)
        self.assertEqual(scan.clips, {})
        self.assertEqual(len(scan.missing), 3)
        self.assertEqual(len(scan.extra), 2)

    def test_reading_rate_flags_wrong_or_truncated_clip(self):
        paths = {("T90", 1): self.touch("T90/T90_01_A.mp3", 3.0),   # ~4 âm tiết/s: bình thường
                 ("T90", 2): self.touch("T90/T90_02_C.mp3", 0.1),   # câu 1 âm tiết: bỏ qua
                 ("T90", 3): self.touch("T90/T90_03_A.mp3", 0.8)}   # >13 âm tiết/s: quá nhanh
        warnings = manual.check_rates([DIALOGUE], paths, manual.clip_seconds)
        self.assertEqual(len(warnings), 1)
        self.assertIn("T90_03_A.mp3", warnings[0])
        slow = manual.check_rates([DIALOGUE], {("T90", 1): paths[("T90", 1)]}, lambda _: 20.0)
        self.assertEqual(len(slow), 1)

    def test_files_engine_builds_dataset_without_new_characters(self):
        for idx, speaker, seconds in ((1, "A", 1.0), (2, "C", 0.5), (3, "A", 1.5)):
            self.touch(f"T90/T90_{idx:02d}_{speaker}.mp3", seconds)
        scan = manual.scan_inbox([DIALOGUE], self.inbox)
        out = self.inbox / "ds"
        manifest = tts.synth_dataset(SOURCE, out, engine="files", config=manual.files_config(scan),
                                     cache_dir=self.inbox / "cache", channel="none")
        segments = json.loads((out / "audio" / "T90.segments.json").read_text(encoding="utf-8"))["segments"]
        ground_truth = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["new_chars_synthesized"], 0)
        self.assertFalse((self.inbox / "cache").exists())
        self.assertEqual([s["speaker"] for s in segments], ["A", "C", "A"])
        self.assertAlmostEqual(segments[2]["end"] - segments[2]["start"], 1.5, delta=0.1)
        self.assertNotIn("tts_text", ground_truth["dialogues"][0]["turns"][0])

    def test_files_engine_manifest_records_each_clip_by_name_and_hash(self):
        for idx, speaker, seconds in ((1, "A", 1.0), (2, "C", 0.5), (3, "A", 1.5)):
            self.touch(f"T90/T90_{idx:02d}_{speaker}.mp3", seconds)
        config = manual.files_config(manual.scan_inbox([DIALOGUE], self.inbox))
        first = tts.synth_dataset(SOURCE, self.inbox / "ds1", engine="files", config=config,
                                  cache_dir=self.inbox / "cache", channel="none")
        replaced = self.touch("T90/T90_02_C.mp3", 0.7)  # thay một clip sau khi đã tạo dataset
        second = tts.synth_dataset(SOURCE, self.inbox / "ds2", engine="files", config=config,
                                   cache_dir=self.inbox / "cache", channel="none")
        self.assertEqual([c["file"] for c in first["clips"]],
                         ["T90/T90_01_A.mp3", "T90/T90_02_C.mp3", "T90/T90_03_A.mp3"])
        self.assertEqual(second["clips"][1]["sha256"], tts.file_sha256(replaced))
        changed = [a["idx"] for a, b in zip(first["clips"], second["clips"]) if a["sha256"] != b["sha256"]]
        self.assertEqual(changed, [2])
        self.assertNotIn(str(self.inbox), json.dumps(first["clips"], ensure_ascii=False))

    def test_cli_synth_records_full_script_path_and_hashes(self):
        for idx, speaker in ((1, "A"), (2, "C"), (3, "A")):
            self.touch(f"T90/T90_{idx:02d}_{speaker}.mp3")
        script = self.inbox / "script.json"
        script.write_text(json.dumps(SOURCE, ensure_ascii=False), encoding="utf-8")
        out = self.inbox / "ds"
        with contextlib.redirect_stdout(io.StringIO()):
            cli(["synth", "--engine", "files", "--inbox", str(self.inbox), "--dialogues", str(script),
                 "--out", str(out), "--channel", "none"])
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["source"], {"file": str(script.resolve()), "sha256": text_sha256(script)})
        self.assertEqual((manifest["noise"], manifest["team_preview"]), (None, False))
        self.assertEqual(manifest["ground_truth_sha256"], text_sha256(out / "ground_truth.json"))
        self.assertEqual(len(manifest["clips"]), 3)

    def test_files_engine_requires_every_clip(self):
        with self.assertRaises(KeyError):
            tts.plan([DIALOGUE], "files", {"files": {"clips": {"T90#1": "x.mp3"}}})


if __name__ == "__main__":
    unittest.main()
