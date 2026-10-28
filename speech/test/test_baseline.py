"""Frozen baseline contracts; all decoding is synthetic and all artifacts are temporary."""
import copy
import hashlib
import io
import itertools
import json
import shutil
import tempfile
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from speech import asr, baseline, btc, evaluate
from speech.__main__ import main
from speech.normalize import default_lexicon


def piece(text="dạ anh chốt kê ô đê đơn bốn triệu rưỡi nha", **changes):
    return {"start": .1234, "end": .9876, "raw": text, "lang": "vi",
            "avg_logprob": -.1234, "no_speech_prob": .0123, **changes}


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class AsrContractTests(unittest.TestCase):
    def test_finalize_profiles(self):
        lexicon = default_lexicon()
        catalog = ("catalog-sentinel",)
        on = date(2027, 2, 3)
        for profile, postprocess in (("B0", False), ("B1", True), ("B2", True)):
            raw = [piece("  customer COD  ")]
            before = copy.deepcopy(raw)
            with self.subTest(profile=profile), \
                    patch.object(asr, "normalize_text", return_value=SimpleNamespace(
                        spoken="spoken payment", written="written COD")) as normalize, \
                    patch.object(asr, "extract_entities", return_value=(
                        {"payment": "COD"}, [{"payment": "COD"}])) as extract:
                result = asr.finalize(raw, lexicon, catalog, on, postprocess=postprocess)
                written = "written COD" if postprocess else "customer COD"
                spoken = "spoken payment" if postprocess else "customer COD"
                extract.assert_called_once_with([written], catalog, on)
                if postprocess:
                    normalize.assert_called_once_with("customer COD", lexicon)
                else:
                    normalize.assert_not_called()
                self.assertEqual(result, {"text": spoken, "entities": {"payment": "COD"}, "asr_segments": [{
                    "start": .12, "end": .99, "text": spoken, "text_written": written,
                    "raw": "customer COD", "lang": "vi", "avg_logprob": -.123,
                    "no_speech_prob": .012, "entities": {"payment": "COD"}}]})
                self.assertEqual(raw, before)
        normalized = asr.finalize([piece()], lexicon)
        self.assertEqual(normalized["asr_segments"][0]["text_written"], "dạ anh chốt COD đơn 4,5 triệu nha")
        self.assertEqual(normalized["text"], "dạ anh chốt cê ô đê đơn bốn triệu rưỡi nha")
        bypassed = asr.finalize([piece()], lexicon, postprocess=False)
        self.assertEqual(bypassed["text"], piece()["raw"])
        self.assertEqual(bypassed["asr_segments"][0]["text_written"], piece()["raw"])

    def test_finalize_filter_boundaries(self):
        lexicon = default_lexicon()
        for probability, logprob, survives in ((.6, -1.1, True), (.60001, -1., True),
                                              (.60001, -1.00001, False), (.59999, -2, True),
                                              (.9, -.99999, True)):
            pieces = [piece("customer payment", no_speech_prob=probability, avg_logprob=logprob)]
            before = copy.deepcopy(pieces)
            with self.subTest(probability=probability, logprob=logprob):
                result = asr.finalize(pieces, lexicon, postprocess=False)
                self.assertEqual(result["text"], "customer payment" if survives else "")
                self.assertEqual(len(result["asr_segments"]), int(survives))
                self.assertEqual(pieces, before)
        for raw, expected in (("", ""), (" \n ", ""), ("thanks for watching", ""),
                              ("COD size voucher", ""), ("  khách hỏi giá  ", "khách hỏi giá"),
                              ("alo alo alo alo alo", "alo")):
            with self.subTest(cleanup=raw):
                result = asr.finalize([piece(raw)], lexicon,
                    hotword_terms=frozenset({"cod", "size", "voucher"}), postprocess=False)
                self.assertEqual(result["text"], expected)
                self.assertEqual([s["raw"] for s in result["asr_segments"]], [expected] if expected else [])
        pieces = [piece("first", start=0), piece("thanks for watching"), piece("last", start=2)]
        result = asr.finalize(pieces, lexicon, postprocess=False)
        self.assertEqual(result["text"], "first last")
        self.assertEqual([s["start"] for s in result["asr_segments"]], [0, 2])
        self.assertEqual(asr.finalize([], lexicon), {"text": "", "entities": {}, "asr_segments": []})

    def test_decode_hotwords_and_raw_retention(self):
        lexicon = default_lexicon()
        for mode in ("file", "utterance"):
            for hot in (False, True):
                model = Mock()
                model.transcribe.return_value = (iter([SimpleNamespace(
                    start=0., end=.5, text=" thanks for watching ", avg_logprob=-2., no_speech_prob=.9)]), None)
                cfg = asr.DecodeConfig(use_hotwords=hot, segmentation=mode)
                with self.subTest(mode=mode, hotwords=hot), patch.object(asr, "speech_chunks", return_value=[(0, 8000)]):
                    records = asr.decode_segments(model, np.zeros(16000), cfg=cfg,
                                                  vad=asr.VadConfig(), lexicon=lexicon)
                    kwargs = model.transcribe.call_args.kwargs
                    self.assertEqual(kwargs["hotwords"], asr.lexicon_hotwords(lexicon) if hot else None)
                    terms = asr.hotword_filter_terms(lexicon, cfg)
                    self.assertEqual(bool(terms), hot)
                    self.assertEqual(records[0]["raw"].strip(), "thanks for watching")
                    self.assertEqual((records[0]["avg_logprob"], records[0]["no_speech_prob"]), (-2., .9))
                    self.assertEqual(asr.finalize(records, lexicon, hotword_terms=terms)["asr_segments"], [])
                    self.assertEqual(len(records), 1)  # filtering never destroys raw diagnostics

    def test_decode_granularity_and_options(self):
        lexicon = default_lexicon()
        audio = np.arange(16000, dtype=np.float32) / 16000
        segments = [SimpleNamespace(start=.1, end=.2, text=" first ", avg_logprob=-.2, no_speech_prob=.1),
                    SimpleNamespace(start=.3, end=.4, text=" second ", avg_logprob=-.6, no_speech_prob=.4)]
        vad = asr.VadConfig(threshold=.7, min_speech_ms=120, min_silence_ms=320, speech_pad_ms=80)
        for mode in ("file", "utterance"):
            for count in (0, 1, 2):
                model = Mock()
                model.transcribe.side_effect = lambda *a, **k: (iter(segments[:count]), None)
                cfg = asr.DecodeConfig(language="vi", beam_size=3, use_hotwords=False, segmentation=mode)
                with self.subTest(mode=mode, count=count), \
                        patch.object(asr, "speech_chunks", return_value=[(0, 4000), (8000, 16000)]):
                    result = asr.decode_segments(model, audio, cfg=cfg, vad=vad, lexicon=lexicon)
                self.assertEqual(len(result), count if mode == "file" else (2 if count else 0))
                self.assertEqual(model.transcribe.call_count, 1 if mode == "file" else 2)
                for call in model.transcribe.call_args_list:
                    kwargs = call.kwargs
                    self.assertEqual((kwargs["language"], kwargs["beam_size"], kwargs["hotwords"],
                                      kwargs["condition_on_previous_text"], kwargs["temperature"]),
                                     ("vi", 3, None, False, (0., .2, .4)))
                    self.assertEqual(kwargs["vad_filter"], mode == "file")
                    if mode == "file":
                        options = kwargs["vad_parameters"]
                        self.assertEqual((options.threshold, options.min_speech_duration_ms,
                                          options.min_silence_duration_ms, options.speech_pad_ms),
                                         (.7, 120, 320, 80))
                    else:
                        self.assertTrue(kwargs["without_timestamps"])
                if count and mode == "utterance":
                    self.assertEqual([r["raw"] for r in result], ["first second" if count == 2 else "first"] * 2)
                    self.assertEqual([(r["start"], r["end"]) for r in result], [(0, .25), (.5, 1)])
                    self.assertAlmostEqual(result[0]["avg_logprob"], -.4 if count == 2 else -.2)
                    self.assertEqual(result[0]["no_speech_prob"], .4 if count == 2 else .1)
                    np.testing.assert_array_equal(model.transcribe.call_args_list[1].args[0], audio[8000:16000])
                elif count:
                    self.assertEqual([(r["start"], r["end"], r["raw"]) for r in result],
                                     [(s.start, s.end, s.text) for s in segments[:count]])

    def test_decode_empty_vad_and_language_boundary(self):
        lexicon = default_lexicon()
        model = Mock()
        with patch.object(asr, "speech_chunks", return_value=[]):
            self.assertEqual(asr.decode_segments(model, np.zeros(16000), cfg=asr.DecodeConfig(),
                                                vad=asr.VadConfig(), lexicon=lexicon), [])
        model.transcribe.assert_not_called()
        for detected, confidence, expected in (("en", .74999, "vi"), ("en", .75, "en"),
                                                ("en", .75001, "en"), ("fr", .99, "vi")):
            model = Mock()
            model.detect_language.return_value = (detected, confidence, None)
            model.transcribe.return_value = (iter([SimpleNamespace(text="customer", avg_logprob=-.1,
                                                                   no_speech_prob=.01)]), None)
            with self.subTest(detected=detected, confidence=confidence), \
                    patch.object(asr, "speech_chunks", return_value=[(0, 8000)]):
                records = asr.decode_segments(model, np.zeros(16000), cfg=asr.DecodeConfig(language="auto"),
                                              vad=asr.VadConfig(), lexicon=lexicon)
                self.assertEqual(records[0]["lang"], expected)
                self.assertEqual(model.transcribe.call_args.kwargs["language"], expected)


class BaselineFixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.data_dir = self.root / "btc"
        baseline.write_json(self.data_dir / "catalog" / "products.json", [])
        path = self.data_dir / "eval" / "reference_eval.py"
        path.parent.mkdir()
        path.write_text("# synthetic fingerprint only\n", encoding="utf-8")
        self.dataset = self.make_dataset("dataset", ["X1", "X2"])
        self.out = self.root / "experiment"

    def make_dataset(self, name, ids, reference_date="2027-10-15", explicit=True):
        dataset = self.root / name
        dialogues = [{"id": key, "full_text": "giao ngày mai", "turns": [
            {"idx": 1, "speaker": "C", "text": "giao ngày mai"}], "entities": {},
            "split": "dev" if i == 0 else "holdout", "noisy": i > 0,
            **({"call_date": f"2028-10-{15 + i:02}"} if explicit else {})} for i, key in enumerate(ids)]
        baseline.write_json(dataset / "ground_truth.json", {"reference_date": reference_date, "dialogues": dialogues})
        self.seal_dataset(dataset)
        (dataset / "audio").mkdir(exist_ok=True)
        for key in ids:
            (dataset / "audio" / f"{key}.wav").write_bytes(f"synthetic audio {key}".encode())
        return dataset

    def seal_dataset(self, dataset=None):
        dataset = dataset or self.dataset
        baseline.write_json(dataset / "manifest.json",
                            {"ground_truth_sha256": btc.text_sha256(dataset / "ground_truth.json")})

    def run_fixture(self, datasets=None, out=None, audio=None):
        ticks = itertools.count(step=.25)
        fake_model = Mock()
        with patch.object(baseline, "load_model", return_value=(fake_model, "cpu", "int8")), \
                patch.object(baseline, "runtime_fingerprint", return_value={"model_files": {"model.bin": "fake"}}), \
                patch.object(baseline.au, "decode", return_value=(
                    np.ones(16000, dtype=np.float32) if audio is None else audio)), \
                patch.object(baseline, "decode_segments", side_effect=lambda *a, **k: [
                    piece("giao ngày mai" if k["cfg"].use_hotwords else piece()["raw"])]) as decoder, \
                patch.object(baseline, "finalize", wraps=asr.finalize) as finalizer, \
                patch.object(baseline.time, "perf_counter", side_effect=lambda: next(ticks)), \
                patch.object(baseline, "compare_baselines", return_value={"comparison": "deferred"}) as compare:
            result = baseline.run_baselines(datasets or [self.dataset], out or self.out, self.data_dir,
                                            model_name="fake", progress=Mock())
        self.assertEqual(result, {"comparison": "deferred"})
        compare.assert_called_once_with(out or self.out, self.data_dir)
        return decoder, finalizer

    def change_artifact(self, out, profile, name, mutate):
        path = out / profile / f"{name}.json"
        value = btc.read_json(path)
        mutate(value)
        baseline.write_json(path, value)
        info = btc.read_json(out / profile / "run.json")
        info[f"{name}_sha256"] = baseline.file_sha256(path)
        baseline.write_json(out / profile / "run.json", info)


class BaselineContractTests(BaselineFixture):
    def test_profile_decode_reuse(self):
        decoder, finalizer = self.run_fixture()
        self.assertEqual([c.kwargs["cfg"].use_hotwords for c in decoder.call_args_list], [False, True] * 2)
        self.assertEqual([c.kwargs["postprocess"] for c in finalizer.call_args_list], [False, True, True] * 2)
        self.assertEqual((self.out / "B0" / "raw.json").read_bytes(), (self.out / "B1" / "raw.json").read_bytes())
        self.assertNotEqual((self.out / "B0" / "raw.json").read_bytes(), (self.out / "B2" / "raw.json").read_bytes())
        for profile in baseline.PROFILES:
            record = btc.read_json(self.out / profile / "hypotheses.json")["X1"]
            expected = {"B0": piece()["raw"], "B1": "dạ anh chốt COD đơn 4,5 triệu nha", "B2": "giao ngày mai"}[profile]
            self.assertEqual(record["asr_segments"][0]["text_written"], expected)
        self.assertEqual(set(baseline.verify_experiment(self.out, self.data_dir)[2]), {"B0", "B1", "B2"})

    def test_explicit_dates_reach_finalize(self):
        _, finalizer = self.run_fixture()
        self.assertEqual([c.args[3] for c in finalizer.call_args_list],
                         [date(2028, 10, 15)] * 3 + [date(2028, 10, 16)] * 3)
        self.assertEqual([i["call_date"] for i in btc.read_json(self.out / "experiment.json")["inputs"]],
                         ["2028-10-15", "2028-10-16"])

    def test_dataset_provenance(self):
        other = self.make_dataset("other", ["Y1"])
        merged, inputs = baseline.dataset_inputs([self.dataset, other])
        self.assertEqual([d["id"] for d in merged["dialogues"]], ["X1", "X2", "Y1"])
        self.assertEqual([i["dataset"] for i in inputs], ["dataset", "dataset", "other"])
        self.assertEqual(len(baseline.dataset_inputs([self.dataset])[1]), 2)
        for manifest in ({}, {"ground_truth_sha256": "bad"}, [], None):
            baseline.write_json(self.dataset / "manifest.json", manifest)
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                baseline.dataset_inputs([self.dataset])
        self.seal_dataset()
        for gt in ([], None, {"dialogues": {}}, {"dialogues": [None]}, {"dialogues": [{}]}):
            baseline.write_json(self.dataset / "ground_truth.json", gt)
            self.seal_dataset()
            with self.subTest(gt=gt), self.assertRaises(ValueError):
                baseline.dataset_inputs([self.dataset])

    def test_dataset_identifiers(self):
        duplicate_name = self.root / "nested" / "dataset"
        shutil.copytree(self.dataset, duplicate_name)
        with self.assertRaisesRegex(ValueError, "names"):
            baseline.dataset_inputs([self.dataset, duplicate_name])
        other = self.make_dataset("other", ["X1"])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            baseline.dataset_inputs([self.dataset, other])
        pristine = btc.read_json(self.dataset / "ground_truth.json")
        for key in ("", None, True, "../X", "a/b", "a\\b", "X1"):
            gt = copy.deepcopy(pristine)
            gt["dialogues"][1]["id"] = key
            baseline.write_json(self.dataset / "ground_truth.json", gt)
            self.seal_dataset()
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "Invalid or duplicate"):
                baseline.dataset_inputs([self.dataset])

    def test_empty_inputs(self):
        with self.assertRaisesRegex(ValueError, "At least one"):
            baseline.dataset_inputs([])
        empty = self.make_dataset("empty", [])
        with self.assertRaisesRegex(ValueError, "no dialogues"):
            baseline.dataset_inputs([empty])
        with self.assertRaisesRegex(ValueError, "Empty audio: X1"):
            self.run_fixture(audio=np.zeros(0, dtype=np.float32))
        self.assertFalse((self.out / "B0" / "hypotheses.json").exists())

    def test_output_directory_guard(self):
        for state in ("file", "nonempty", "empty", "new"):
            path = self.root / state
            if state == "file":
                path.write_bytes(b"sentinel")
            elif state != "new":
                path.mkdir()
                if state == "nonempty":
                    (path / "sentinel").write_bytes(b"original")
            with self.subTest(state=state):
                if state in ("file", "nonempty"):
                    before = path.read_bytes() if path.is_file() else snapshot(path)
                    with self.assertRaisesRegex(ValueError, "empty/new"):
                        self.run_fixture(out=path)
                    self.assertEqual(path.read_bytes() if path.is_file() else snapshot(path), before)
                else:
                    self.run_fixture(out=path)
                    self.assertEqual(len(baseline.verify_experiment(path, self.data_dir)[1]["dialogues"]), 2)

    def test_artifact_provenance_and_timing(self):
        self.run_fixture()
        experiment = btc.read_json(self.out / "experiment.json")
        self.assertEqual(experiment["fingerprint"], {"model_files": {"model.bin": "fake"}})
        self.assertEqual(experiment["vad"], asdict(asr.VadConfig()))
        self.assertEqual(experiment["model"], "fake")
        self.assertEqual(experiment["ground_truth_sha256"], btc.text_sha256(self.out / "ground_truth.json"))
        self.assertEqual(experiment["catalog_sha256"], btc.text_sha256(self.data_dir / "catalog" / "products.json"))
        self.assertEqual(experiment["evaluator_sha256"], btc.text_sha256(self.data_dir / "eval" / "reference_eval.py"))
        for i, item in enumerate(experiment["inputs"]):
            self.assertEqual(item, {"id": f"X{i + 1}", "dataset": "dataset",
                "audio": str((self.dataset / "audio" / f"X{i + 1}.wav").resolve()),
                "audio_sha256": baseline.file_sha256(self.dataset / "audio" / f"X{i + 1}.wav"),
                "call_date": f"2028-10-{15 + i}", "ground_truth_sha256": btc.text_sha256(
                    self.dataset / "ground_truth.json"), "manifest_sha256": btc.text_sha256(
                    self.dataset / "manifest.json"), "split": ("dev", "holdout")[i], "noisy": bool(i)})
        for profile, policy in baseline.PROFILES.items():
            with self.subTest(profile=profile):
                info = btc.read_json(self.out / profile / "run.json")
                self.assertEqual((info["load_s"], info["audio_s"], info["asr_s"], info["rtf"]), (.25, 2., 1., .5))
                self.assertEqual((info["frozen"], info["profile"], info["postprocess"], info["decode_reused"]),
                                 (True, profile, policy["postprocess"], profile == "B1"))
                self.assertEqual(info["decode"], asdict(asr.DecodeConfig(use_hotwords=policy["hotwords"])))
                self.assertEqual((info["device"], info["compute_type"]), ("cpu", "int8"))
                for name in ("raw", "hypotheses"):
                    self.assertEqual(info[f"{name}_sha256"], baseline.file_sha256(self.out / profile / f"{name}.json"))
                self.assertEqual(info["experiment_sha256"], baseline.file_sha256(self.out / "experiment.json"))
                hypotheses = btc.read_json(self.out / profile / "hypotheses.json")
                self.assertEqual(hypotheses["X1"]["meta"], {"audio_s": 1., "asr_s": .5, "decode_s": .25,
                                                           "postprocess_s": .25, "rtf": .5})
                self.assertEqual(btc.read_json(self.out / profile / "raw.json")["X1"]["decode_s"], .25)

    def test_hash_and_fingerprint_contracts(self):
        lf, crlf, empty = (self.root / name for name in ("lf", "crlf", "empty"))
        lf.write_bytes(b"a\nb\n")
        crlf.write_bytes(b"a\r\nb\r\n")
        empty.write_bytes(b"")
        self.assertEqual(btc.text_sha256(lf), btc.text_sha256(crlf))
        self.assertNotEqual(baseline.file_sha256(lf), baseline.file_sha256(crlf))
        self.assertEqual(baseline.file_sha256(empty), hashlib.sha256(b"").hexdigest())
        self.assertEqual(baseline.object_hash({"b": 2, "a": 1}), baseline.object_hash({"a": 1, "b": 2}))
        self.assertNotEqual(baseline.object_hash({"a": 1}), baseline.object_hash({"a": 2}))
        model = self.root / "model"
        model.mkdir()
        (model / "model.bin").write_bytes(b"model")
        (model / "tokenizer.json").write_bytes(b"{}")
        (model / "ignored-subdirectory").mkdir()
        with patch.object(baseline, "resolve_model", return_value=model) as resolve:
            fingerprint = baseline.runtime_fingerprint("fake-local")
        resolve.assert_called_once_with("fake-local")
        self.assertEqual(fingerprint["model_files"], {name: baseline.file_sha256(model / name)
                         for name in ("model.bin", "tokenizer.json")})
        self.assertEqual(set(fingerprint["dependencies"]), {"faster-whisper", "ctranslate2", "numpy", "av"})
        for name, digest in fingerprint["code"].items():
            self.assertEqual(digest, btc.text_sha256(Path(baseline.__file__).with_name(name)))

    def test_comparison_row_integrity(self):
        self.run_fixture()
        for profile in baseline.PROFILES:
            for name in ("raw", "hypotheses"):
                for change in ("missing", "extra"):
                    with self.subTest(profile=profile, artifact=name, change=change):
                        out = self.root / f"{profile}-{name}-{change}"
                        shutil.copytree(self.out, out)
                        self.change_artifact(out, profile, name, lambda rows: rows.pop("X2")
                                             if change == "missing" else rows.update({"EXTRA": rows["X1"]}))
                        with self.assertRaisesRegex(ValueError, "missing/extra IDs"):
                            baseline.compare_baselines(out, self.data_dir)

    def test_provenance_tampering(self):
        self.run_fixture()
        paths = [self.dataset / "audio" / "X1.wav", self.dataset / "ground_truth.json",
                 self.dataset / "manifest.json", self.out / "ground_truth.json",
                 self.data_dir / "catalog" / "products.json", self.data_dir / "eval" / "reference_eval.py"]
        for path in paths:
            with self.subTest(path=str(path.relative_to(self.root))):
                original = path.read_bytes()
                path.write_bytes(original + b"\n")
                try:
                    with self.assertRaisesRegex(ValueError, "changed"):
                        baseline.compare_baselines(self.out, self.data_dir)
                finally:
                    path.write_bytes(original)
        self.assertEqual(len(baseline.verify_experiment(self.out, self.data_dir)[0]["inputs"]), 2)

    def test_semantic_config_tampering(self):
        self.run_fixture()
        mutations = [(field, lambda info, field=field: info.update({field: "changed"}))
                     for field in ("fingerprint", "model", "vad", "inputs", "ground_truth_sha256",
                                   "catalog_sha256", "evaluator_sha256", "experiment_sha256", "profile",
                                   "device", "compute_type")]
        mutations += [("postprocess", lambda i: i.update(postprocess=not i["postprocess"])),
                      ("hotwords", lambda i: i["decode"].update(use_hotwords=not i["decode"]["use_hotwords"])),
                      ("beam", lambda i: i["decode"].update(beam_size=7))]
        for profile in baseline.PROFILES:
            for label, mutate in mutations:
                with self.subTest(profile=profile, field=label):
                    out = self.root / f"{profile}-{label}"
                    shutil.copytree(self.out, out)
                    path = out / profile / "run.json"
                    info = btc.read_json(path)
                    mutate(info)
                    baseline.write_json(path, info)
                    with self.assertRaises(ValueError):
                        baseline.compare_baselines(out, self.data_dir)

    def test_artifact_byte_tampering(self):
        self.run_fixture()
        for profile in baseline.PROFILES:
            for artifact in ("raw", "hypotheses"):
                with self.subTest(profile=profile, artifact=artifact):
                    out = self.root / f"byte-{profile}-{artifact}"
                    shutil.copytree(self.out, out)
                    path = out / profile / f"{artifact}.json"
                    path.write_bytes(path.read_bytes() + b" ")
                    with self.assertRaisesRegex(ValueError, f"{artifact} changed"):
                        baseline.compare_baselines(out, self.data_dir)

    def test_shared_raw_mismatch_rehashed(self):
        self.run_fixture()
        self.change_artifact(self.out, "B1", "raw", lambda rows: rows["X1"].update(decode_s=99.))
        with self.assertRaisesRegex(ValueError, "share the same raw decode"):
            baseline.compare_baselines(self.out, self.data_dir)

    def test_json_object_boundaries(self):
        path = self.root / "object.json"
        for value in ({}, {"records": [1, 2], "unicode": "ngày mai"}):
            with self.subTest(valid=value):
                baseline.write_json(path, value)
                self.assertEqual(btc.read_json_object(path), value)
                self.assertEqual(btc.read_json(path), value)
        for value in ([], ["record"], None, True, 1, "object"):
            with self.subTest(invalid=value):
                baseline.write_json(path, value)
                with self.assertRaisesRegex(ValueError, "JSON object"):
                    btc.read_json_object(path)
                self.assertEqual(btc.read_json(path), value)  # the general reader still supports arrays
        self.run_fixture()
        for name in ("experiment.json", "ground_truth.json", "B0/run.json",
                     "B0/hypotheses.json", "B0/raw.json"):
            with self.subTest(consumer=name):
                out = self.root / name.replace("/", "-").replace(".json", "-invalid")
                shutil.copytree(self.out, out)
                path = out / name
                baseline.write_json(path, [])
                if name.startswith("B0/") and not name.endswith("run.json"):
                    info = btc.read_json(out / "B0" / "run.json")
                    info[f"{path.stem}_sha256"] = baseline.file_sha256(path)
                    baseline.write_json(out / "B0" / "run.json", info)
                with self.assertRaisesRegex(ValueError, "JSON object"):
                    baseline.verify_experiment(out, self.data_dir)

    def test_common_schema_mismatch(self):
        self.run_fixture()
        for profile in baseline.PROFILES:
            with self.subTest(profile=profile):
                out = self.root / f"schema-{profile}"
                shutil.copytree(self.out, out)
                info = btc.read_json(out / profile / "run.json")
                info["schema_version"] = 2
                baseline.write_json(out / profile / "run.json", info)
                with self.assertRaisesRegex(ValueError, "incompatible schema_version"):
                    baseline.verify_experiment(out, self.data_dir)


class BaselineComparisonTests(BaselineFixture):
    def compare_with_oracle(self):
        # Synthetic scorer isolates date propagation without requiring the external BTC package.
        evaluator = SimpleNamespace(wer_cer=lambda _: {"WER": 0., "CER": 0., "entity_accuracy": 100.,
                                                        "n_dialogues": 2, "n_entities": 0, "per_dialogue": {}})
        with patch.object(baseline, "load_reference_eval", return_value=evaluator), \
                patch.object(evaluate, "extract_entities", wraps=evaluate.extract_entities) as extract:
            comparison = baseline.compare_baselines(self.out, self.data_dir)
        self.assertEqual(comparison["delta_percentage_points"]["B0->B2"],
                         {"WER": 0., "CER": 0., "entity_accuracy": 0.})
        return extract

    def test_oracle_explicit_dates(self):
        self.run_fixture()
        extract = self.compare_with_oracle()
        self.assertEqual([c.args[2] for c in extract.call_args_list],
                         [date(2028, 10, 15), date(2028, 10, 16)] * 3)
        self.assertEqual(extract.call_args_list[0].args[0], ["giao ngày mai"])

    def test_dataset_date_reaches_finalize_and_oracle(self):
        dataset = self.make_dataset("fallback", ["F1", "F2"], reference_date="2027-10-15", explicit=False)
        other = self.make_dataset("later", ["L1"], reference_date="2029-01-02", explicit=False)
        _, finalizer = self.run_fixture(datasets=[dataset, other])
        self.assertEqual([c.args[3] for c in finalizer.call_args_list],
                         [date(2027, 10, 15)] * 6 + [date(2029, 1, 2)] * 3)
        extract = self.compare_with_oracle()
        self.assertEqual([c.args[2] for c in extract.call_args_list],
                         [date(2027, 10, 15), date(2027, 10, 15), date(2029, 1, 2)] * 3,
                         "Merged GT must preserve each resolved dataset date; oracle must not use 2026 fallback")

    def test_numeric_comparison(self):
        data_dir = btc.find_data_dir(required=False)
        if data_dir is None:
            self.skipTest("cần dữ liệu BTC (BTC_DATA_DIR)")
        gt = {"dialogues": [
            {"id": "X1", "full_text": "a", "entities": {"a": 1}, "turns": [{"text": "a"}]},
            {"id": "X2", "full_text": "b c d", "entities": {"b": 1, "c": 1, "d": 1},
             "turns": [{"text": "b c d"}]}]}
        inputs = [{"id": "X1", "dataset": "short", "split": "dev", "noisy": False},
                  {"id": "X2", "dataset": "long", "split": "holdout", "noisy": True}]
        hyps = {
            "B0": {"X1": {"text": "x", "entities": {}}, "X2": {"text": "x c d", "entities": {"b": 1}}},
            "B1": {"X1": {"text": "x", "entities": {"a": 1}}, "X2": {"text": "b c d", "entities": {"b": 1, "c": 1}}},
            "B2": {"X1": {"text": "a", "entities": {"a": 1}},
                   "X2": {"text": "b c d", "entities": {"b": 1, "c": 1, "d": 1}}}}
        baseline.write_json(self.out / "ground_truth.json", gt)
        experiment = {"inputs": inputs,
                      "evaluator_sha256": btc.text_sha256(data_dir / "eval" / "reference_eval.py")}
        baseline.write_json(self.out / "experiment.json", experiment)
        for profile in baseline.PROFILES:
            baseline.write_json(self.out / profile / "hypotheses.json", hyps[profile])
        with warnings.catch_warnings(), patch.object(baseline, "verify_experiment",
                return_value=(experiment, gt, hyps)):
            warnings.simplefilter("ignore", ResourceWarning)
            result = baseline.compare_baselines(self.out, data_dir)
        self.assertEqual(result["evaluator_sha256"], experiment["evaluator_sha256"])
        self.assertEqual(result["scorer_code_sha256"], btc.text_sha256(Path(baseline.__file__)))
        expected = {
            "all": ([(50, 50, 25), (25, 25, 75), (0, 0, 100)], (2, 4)),
            "short": ([(100, 100, 0), (100, 100, 100), (0, 0, 100)], (1, 1)),
            "long": ([(33.3, 33.3, 33.3), (0, 0, 66.7), (0, 0, 100)], (1, 3))}
        groups = {"all": "all", "dataset:short": "short", "split:dev": "short", "noisy:False": "short",
                  "dataset:long": "long", "split:holdout": "long", "noisy:True": "long"}
        self.assertEqual(set(result["groups"]), set(groups))
        for group, expected_key in groups.items():
            metrics, counts = expected[expected_key]
            for profile, values in zip(baseline.PROFILES, metrics):
                with self.subTest(group=group, profile=profile):
                    score = result["groups"][group][profile]
                    self.assertEqual(tuple(score[k] for k in ("WER", "CER", "entity_accuracy")), values)
                    self.assertEqual((score["n_dialogues"], score["n_entities"]), counts)
        self.assertEqual(result["delta_percentage_points"], {
            "B0->B1": {"WER": -25., "CER": -25., "entity_accuracy": 50.},
            "B1->B2": {"WER": -25., "CER": -25., "entity_accuracy": 25.},
            "B0->B2": {"WER": -50., "CER": -50., "entity_accuracy": 75.}})
        self.assertEqual(btc.read_json(self.out / "comparison.json"), result)
        self.assertIn("| B0->B2 | -50.0 | -50.0 | 75.0 |", (self.out / "report.md").read_text(encoding="utf-8"))
        for profile, values in zip(baseline.PROFILES, expected["all"][0]):
            report = btc.read_json(self.out / profile / "score.json")
            self.assertEqual(tuple(report["official"][k] for k in ("WER", "CER", "entity_accuracy")), values)
            self.assertEqual(report["dialogues"], {"expected": 2, "processed": 2, "empty": 0, "extra": []})


class SpeechCliTests(unittest.TestCase):
    def cases(self):
        options = {"model_name": "fake", "device": "cpu", "compute_type": "int8"}
        model_args = ["--model", "fake", "--device", "cpu", "--compute-type", "int8"]
        return [
            ("speech.baseline.run_baselines", ["baseline", "--datasets", "D1", "D2", "--out", "OUT"] + model_args,
             ([Path("D1"), Path("D2")], Path("OUT"), Path("BTC")), options),
            ("speech.baseline.compare_baselines", ["compare-baselines", "--experiment", "EXP"],
             (Path("EXP"), Path("BTC")), {}),
            ("speech.replay.prepare_replay", ["prepare-replay", "--mapping", "map.json", "--out", "OUT"],
             (Path("map.json"), Path("OUT")), {}),
            ("speech.replay.export_replay", ["export-replay", "--prepared", "PREP", "--out", "OUT"] + model_args,
             (Path("PREP"), Path("OUT"), Path("BTC")), options),
            ("speech.replay.verify_bundle", ["verify-replay", "--bundle", "BUNDLE"], (Path("BUNDLE"),), {})]

    def test_scoped_dispatch(self):
        for target, argv, args, kwargs in self.cases():
            with self.subTest(command=argv[0]), patch(target, return_value={"kind": "replay", "turn_count": 2}) as fn, \
                    patch.object(btc, "find_data_dir", return_value=Path("BTC")) as find, redirect_stdout(io.StringIO()):
                main(["--data-dir", "BTC"] + argv)
                fn.assert_called_once_with(*args, **kwargs)
                if argv[0] in ("baseline", "compare-baselines", "export-replay"):
                    find.assert_called_once_with("BTC")
                else:
                    find.assert_not_called()

    def test_scoped_cli_errors(self):
        for target, argv, _, _ in self.cases():
            for error in (ValueError("contract failure"), FileNotFoundError("missing fixture")):
                with self.subTest(command=argv[0], error=type(error).__name__), patch(target, side_effect=error), \
                        patch.object(btc, "find_data_dir", return_value=Path("BTC")), \
                        self.assertRaises(SystemExit) as caught:
                    main(["--data-dir", "BTC"] + argv)
                self.assertEqual(str(caught.exception), str(error))
        for argv in (["baseline", "--out", "OUT"], ["prepare-replay", "--mapping", "map.json"],
                     ["verify-replay", "--bundle", "BUNDLE", "--memory-enabled"]):
            with self.subTest(parser=argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                main(argv)
            self.assertEqual(caught.exception.code, 2)

    def test_frozen_renormalize_preflight(self):
        for guard in ({"frozen": True}, {"profile": "B0"}, {"profile": "B1"}, {"profile": "B2"}):
            with self.subTest(guard=guard), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for name, info in (("first", {"frozen": False}), ("guarded", guard)):
                    baseline.write_json(root / name / "run.json", info)
                    baseline.write_json(root / name / "hypotheses.json",
                                        {"X1": {"asr_segments": [piece()], "meta": {"audio_s": 1}}})
                before = snapshot(root)
                with patch.object(btc, "find_data_dir", return_value=None), \
                        patch.object(asr, "finalize", wraps=asr.finalize) as finalizer, \
                        self.assertRaises(SystemExit):
                    main(["renormalize", "--runs", str(root / "first"), str(root / "guarded")])
                finalizer.assert_not_called()
                self.assertEqual(snapshot(root), before)
