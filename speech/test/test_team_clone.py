"""Giọng clone của thành viên (VieNeu ``ref_audio``) và bản mẫu kịch bản tv1–tv3 / ``{kh}``."""
import argparse
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from speech import audio as au
from speech import tts
from speech.__main__ import _team_source
from speech.team import PREVIEW_TEAM, fill_team, load_team_voices, team_voice_entries

SR = au.SAMPLE_RATE
TEMPLATE = {"reference_date": "2026-10-15", "tts_engine": "vieneu", "dialogues": [{
    "id": "T95", "agent_voice": "tv1", "customer_voice": "tv2", "noisy": False,
    "checks": [{"tool": "x"}], "tool_context": {"crm_overlay": []},
    "turns": [{"idx": 1, "speaker": "A", "text": "dạ em chào {kh} ạ", "entities": {}},
              {"idx": 2, "speaker": "C", "text": "chào em", "entities": {}}], "entities": {}}]}


def tone(seconds: float) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (0.3 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)


class TeamVoicesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        au.write_wav(self.dir / "refs" / "tv1.wav", tone(1.0))
        au.write_wav(self.dir / "refs" / "tv2.wav", tone(1.2))

    def tearDown(self):
        self._tmp.cleanup()

    def write_team(self, team: dict) -> Path:
        path = self.dir / "team_voices.json"
        path.write_text(json.dumps(team), encoding="utf-8")
        return path

    def team(self) -> dict:
        return {"_doc": "ghi chú", "tv1": {"gender": "f", "region": "bac", "ref_audio": "refs/tv1.wav", "consent": True},
                "tv2": {"gender": "m", "region": "nam", "ref_audio": "refs/tv2.wav", "consent": True}}

    def test_relative_ref_audio_resolved_next_to_json(self):
        team = load_team_voices(self.write_team(self.team()))
        self.assertEqual(sorted(team), ["tv1", "tv2"])
        self.assertTrue(Path(team["tv1"]["ref_audio"]).is_file())

    def test_missing_consent_or_sample_is_rejected(self):
        raw = self.team()
        raw["tv1"]["consent"] = False
        raw["tv2"]["ref_audio"] = "refs/khong-co.wav"
        raw["tv4"] = {"gender": "f", "region": "bac"}
        with self.assertRaises(ValueError) as ctx:
            load_team_voices(self.write_team(raw))
        message = str(ctx.exception)
        self.assertIn("consent", message)
        self.assertIn("khong-co.wav", message)
        self.assertIn("tv4", message)

    def test_fill_team_sets_region_gender_and_honorific(self):
        filled = fill_team(TEMPLATE, load_team_voices(self.write_team(self.team())))
        d = filled["dialogues"][0]
        self.assertEqual((d["agent_region"], d["agent_gender"], d["customer_region"], d["customer_gender"]),
                         ("bac", "f", "nam", "m"))
        self.assertEqual(d["turns"][0]["text"], "dạ em chào anh ạ")
        self.assertIn("{kh}", TEMPLATE["dialogues"][0]["turns"][0]["text"])  # bản mẫu gốc không bị sửa
        with self.assertRaises(ValueError):
            fill_team(TEMPLATE, {"tv1": PREVIEW_TEAM["tv1"]})

    def test_clone_dataset_uses_team_voice_and_writes_filled_ground_truth(self):
        team = load_team_voices(self.write_team(self.team()))
        config = {"vieneu": {"voices": {"bac_f": {"voice": "Preset"}, **team_voice_entries(team)}}}
        calls = []

        def fake_vieneu(text: str, params: dict) -> np.ndarray:
            calls.append((text, params["key"], params["ref_audio"]))
            return tone(0.4)

        with mock.patch.dict(tts.ENGINES, {"vieneu": fake_vieneu}):
            manifest = tts.synth_dataset(fill_team(TEMPLATE, team), self.dir / "ds", engine="vieneu",
                                         config=config, cache_dir=self.dir / "cache", channel="none")
        gt = json.loads((self.dir / "ds" / "ground_truth.json").read_text(encoding="utf-8"))["dialogues"][0]
        self.assertEqual([c[1] for c in calls], ["tv1", "tv2"])
        self.assertEqual(calls[0][0], "dạ em chào anh ạ")
        self.assertEqual((gt["agent_region"], gt["customer_gender"]), ("bac", "m"))
        self.assertNotIn("checks", gt)
        self.assertNotIn("tool_context", gt)
        labels = {v[2] for v in manifest["voices"]}
        self.assertTrue(all(label.startswith("clone-") for label in labels))
        self.assertNotIn(str(self.dir), json.dumps(manifest, ensure_ascii=False))  # không lộ đường dẫn mẫu giọng

    def test_cache_follows_sample_content_not_path(self):
        ref = self.dir / "refs" / "tv1.wav"
        moved = self.dir / "elsewhere.wav"
        shutil.copy(ref, moved)
        n = []

        def fake_vieneu(text: str, params: dict) -> np.ndarray:
            n.append(params["ref_audio_sha256"])
            return tone(0.3)

        cache = self.dir / "cache"
        with mock.patch.dict(tts.ENGINES, {"vieneu": fake_vieneu}):
            _, first = tts.synth_text("dạ", "vieneu", {"key": "tv1", "ref_audio": str(ref)}, cache)
            _, same = tts.synth_text("dạ", "vieneu", {"key": "tv1", "ref_audio": str(moved)}, cache)
            au.write_wav(moved, tone(2.0))
            _, changed = tts.synth_text("dạ", "vieneu", {"key": "tv1", "ref_audio": str(moved)}, cache)
        self.assertEqual((first, same, changed), (False, True, False))
        self.assertEqual(len(n), 2)

    def test_vieneu_adds_clone_once_per_sample(self):
        class FakeVieneu:
            sample_rate = 48_000
            added: list = []
            used: list = []

            def __init__(self, mode: str):
                self.mode = mode

            def add_voice(self, name, ref_audio, *, denoise=True, save=False):
                FakeVieneu.added.append((name, ref_audio, denoise, save))
                return name

            def infer(self, text: str, voice: str, **kwargs):
                FakeVieneu.used.append(voice)
                return np.repeat(tone(0.5), 3)

        ref = str(self.dir / "refs" / "tv1.wav")
        sha = tts.file_sha256(ref)
        with mock.patch.dict("sys.modules", {"vieneu": mock.Mock(Vieneu=FakeVieneu)}), \
                mock.patch.dict(tts._VIENEU_MODELS, clear=True), mock.patch.dict(tts._VIENEU_CLONES, clear=True):
            clip = tts._vieneu("dạ em chào chị", {"key": "tv1", "ref_audio": ref})
            tts._vieneu("vâng ạ", {"key": "tv1", "ref_audio": ref, "ref_audio_sha256": sha})
        self.assertEqual(FakeVieneu.added, [(f"clone-{sha[:12]}", ref, True, False)])
        self.assertEqual(FakeVieneu.used, [f"clone-{sha[:12]}"] * 2)
        self.assertAlmostEqual(clip.size / SR, 0.5, delta=0.01)


class TemplateCliTests(unittest.TestCase):
    def args(self, **kw) -> argparse.Namespace:
        return argparse.Namespace(**{"team_voices": None, "preview_team": False, "engine": "edge", **kw})

    def test_template_needs_team_voices_or_preview(self):
        with self.assertRaises(SystemExit):
            _team_source(TEMPLATE, self.args(), {})
        preview = _team_source(TEMPLATE, self.args(preview_team=True), {})
        self.assertTrue(preview["team_preview"])
        self.assertEqual(preview["dialogues"][0]["customer_region"], PREVIEW_TEAM["tv2"]["region"])
        full = {"dialogues": [{"id": "X", "turns": []}]}
        self.assertIs(_team_source(full, self.args(), {}), full)


if __name__ == "__main__":
    unittest.main()
