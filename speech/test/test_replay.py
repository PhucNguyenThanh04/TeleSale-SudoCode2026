"""Offline replay contracts: synthetic PCM, fake ASR, and the real request schema."""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from speech import replay
from speech.baseline import write_json
from speech.btc import read_json, text_sha256
from speech.tts import file_sha256


def session(**changes):
    return dict(dataset="dataset", dialogue_id="X1", conversation_key="conv",
                session_key="session1", session_index=1, identity_ref="synthetic",
                call_date="2026-10-15", **changes) if not changes else {
                    **session(), **changes}


def turn(**changes):
    return {**{k: v for k, v in session().items() if k not in ("dataset", "dialogue_id")},
            "turn_index": 1, "source_turn_index": 2, "text": "decoded customer",
            "customer_input_mode": "asr_transcript", "audio_sha256": "a" * 64, **changes}


def segment(**changes):
    return {"idx": 2, "speaker": "C", "start": .25, "end": .75,
            "text": "GT_SENTINEL", **changes}


def raw_piece(text="dạ anh chốt kê ô đê đơn bốn triệu rưỡi nha", **changes):
    return {"start": 0., "end": .5, "raw": text, "lang": "vi",
            "avg_logprob": -.1, "no_speech_prob": .01, **changes}


class ReplayValidationTests(unittest.TestCase):
    def test_mapping_schema(self):
        valid = {"schema_version": 1, "sessions": [session()]}
        self.assertEqual(replay.validate_sessions(valid), [session()])
        invalid = [None, [], True, {}, {**valid, "schema_version": True},
                   {**valid, "schema_version": "1"}, {**valid, "schema_version": 2},
                   {**valid, "sessions": []}, {**valid, "sessions": {}},
                   {**valid, "sessions": [None]}, {**valid, "answer": "LABEL"}]
        for field in replay.SESSION_FIELDS:
            invalid.append({**valid, "sessions": [{k: v for k, v in session().items() if k != field}]})
        for field in ("expected_answer", "labels", "ground_truth", "memory_enabled"):
            invalid.append({**valid, "sessions": [{**session(), field: "LABEL_SENTINEL"}]})
        for value in ("", " ", None, 4):
            invalid.append({**valid, "sessions": [session(dataset=value)]})
        for index, payload in enumerate(invalid):
            with self.subTest(case=index), self.assertRaises(ValueError):
                replay.validate_sessions(payload)

    def test_session_sequence(self):
        first = session()
        second = session(session_key="session2", session_index=2)
        for on in ("2026-10-15", "2026-10-16", "2027-01-01"):
            sessions = [first, {**second, "call_date": on},
                        session(conversation_key="other", session_key="other1")]
            with self.subTest(valid_date=on):
                self.assertEqual(replay.validate_sessions({"schema_version": 1, "sessions": sessions}), sessions)
        for changes in ({"identity_ref": "different"}, {"call_date": "2026-10-14"},
                        {"call_date": "20261015"}, {"call_date": "2026-02-30"},
                        {"call_date": None}, {"session_index": 1}, {"session_index": 3}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replay.validate_sessions({"schema_version": 1, "sessions": [first, {**second, **changes}]})
        with self.assertRaises(ValueError):
            replay.validate_sessions({"schema_version": 1, "sessions": [second, first]})

    def test_session_index_and_key_boundaries(self):
        for key in ("a", "A_2-9", "x" * 100):
            with self.subTest(valid_key=key):
                self.assertEqual(replay._key(key), key)
                self.assertEqual(replay.validate_sessions({"schema_version": 1,
                    "sessions": [session(session_key=key)]})[0]["session_key"], key)
        for key in ("", "x" * 101, "../x", "a/b", "a\\b", "_a", "-a", "é", True, None):
            for field in ("dialogue_id", "conversation_key", "session_key", "identity_ref"):
                with self.subTest(key=key, field=field), self.assertRaises(ValueError):
                    replay.validate_sessions({"schema_version": 1, "sessions": [session(**{field: key})]})
        for index in (True, False, 0, -1, 1.0, "1", 2):
            with self.subTest(index=index), self.assertRaises(ValueError):
                replay.validate_sessions({"schema_version": 1, "sessions": [session(session_index=index)]})
        with self.assertRaisesRegex(ValueError, "unique"):
            replay.validate_sessions({"schema_version": 1, "sessions": [
                session(), session(conversation_key="other")]})

    def test_timestamp_types(self):
        for field in ("start", "end"):
            for value in (float("nan"), float("inf"), -float("inf"), True, False, ".5", None):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    replay.customer_segments({"segments": [segment(**{field: value})]}, 1.)
        for duration in (0., -1., float("nan"), float("inf"), -float("inf")):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                replay.customer_segments({"segments": [segment()]}, duration)

    def test_segment_time_boundaries(self):
        for start, end in ((0, 1), (.25, 1), (.25, .75)):
            with self.subTest(valid=(start, end)):
                self.assertEqual(replay.customer_segments({"segments": [segment(start=start, end=end)]}, 1),
                                 [{"idx": 2, "start": start, "end": end}])
        for start, end in ((-.00001, .5), (.5, .5), (.5, .49999), (.5, 1.00001)):
            with self.subTest(invalid=(start, end)), self.assertRaises(ValueError):
                replay.customer_segments({"segments": [segment(start=start, end=end)]}, 1)
        for start in (.5, .50001):
            payload = {"segments": [segment(idx=1, speaker="A", start=0, end=.5),
                                    segment(start=start, end=1)]}
            with self.subTest(touch_or_gap=start):
                self.assertEqual(replay.customer_segments(payload, 1), [{"idx": 2, "start": start, "end": 1}])
        with self.assertRaises(ValueError):
            replay.customer_segments({"segments": [segment(idx=1, start=0, end=.5),
                                                   segment(start=.49999, end=1)]}, 1)

    def test_segment_identity(self):
        for bad in (None, [], "segment"):
            with self.subTest(nonobject=bad), self.assertRaises(ValueError):
                replay.customer_segments({"segments": [bad]}, 1)
        for speaker in ("A", "C"):
            for field, value in (("idx", True), ("idx", 0), ("idx", -1), ("idx", "2"),
                                 ("speaker", "customer"), ("speaker", None), ("start", -.1)):
                with self.subTest(speaker=speaker, field=field, value=value), self.assertRaises(ValueError):
                    replay.customer_segments({"segments": [{**segment(speaker=speaker), field: value},
                        segment(idx=3, start=.8, end=1)]}, 1)
        for index in (1, 2):
            with self.subTest(nonincreasing=index), self.assertRaises(ValueError):
                replay.customer_segments({"segments": [segment(idx=2, start=0, end=.2),
                                                       segment(idx=index)]}, 1)

    def test_missing_customer_segments(self):
        for payload in (None, [], {}, {"segments": []}, {"segments": None},
                        {"segments": [segment(speaker="A")]}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                replay.customer_segments(payload, 1)

    def test_turn_text_boundaries(self):
        for length in (1, 37, 7999, 8000):
            row = turn(text=" " + "x" * length + " ")
            with self.subTest(valid=length):
                self.assertIsNone(replay.validate_turns([row]))
                self.assertEqual(row["text"], " " + "x" * length + " ")  # validation is not truncation
        for text in ("", " \n\t ", "x" * 8001, None, 42):
            with self.subTest(invalid_length=None if not isinstance(text, str) else len(text)):
                with self.assertRaisesRegex(ValueError, "1-8000"):
                    replay.validate_turns([turn(text=text)])

    def test_turn_exact_contract(self):
        self.assertEqual(set(turn()), replay.TURN_FIELDS)
        self.assertIsNone(replay.validate_turns([turn()]))
        invalid = [[], [None]]
        for field in replay.TURN_FIELDS:
            invalid.append([{k: v for k, v in turn().items() if k != field}])
        for field in ("memory_enabled", "expected_answer", "labels", "speaker"):
            invalid.append([{**turn(), field: "LABEL_SENTINEL"}])
        for digest in ("a" * 63, "a" * 65, "A" * 64, "g" * 64, None):
            invalid.append([turn(audio_sha256=digest)])
        for mode in ("clean", "", None, "chat_teencode"):
            invalid.append([turn(customer_input_mode=mode)])
        for field in ("turn_index", "source_turn_index", "session_index"):
            for value in (True, 0, -1, 1.0, "1"):
                invalid.append([turn(**{field: value})])
        for value in (None, "20261015", "2026-02-30"):
            invalid.append([turn(call_date=value)])
        for i, rows in enumerate(invalid):
            with self.subTest(case=i), self.assertRaises(ValueError):
                replay.validate_turns(rows)

    def test_turn_sequence(self):
        second = turn(turn_index=2, source_turn_index=5)
        next_session = turn(session_key="session2", session_index=2, call_date="2026-10-16")
        other = turn(conversation_key="other", session_key="other1")
        rows = [turn(), second, next_session, other]
        before = copy.deepcopy(rows)
        self.assertIsNone(replay.validate_turns(rows))
        self.assertEqual(rows, before)
        for change in ({"turn_index": 1}, {"turn_index": 3}, {"source_turn_index": 2},
                       {"source_turn_index": 1}, {"identity_ref": "other"},
                       {"conversation_key": "other"}, {"session_index": 2}, {"call_date": "2026-10-16"}):
            with self.subTest(changed_second=change), self.assertRaises(ValueError):
                replay.validate_turns([turn(), {**second, **change}])
        for change in ({"session_index": 3}, {"identity_ref": "other"}, {"call_date": "2026-10-14"}):
            with self.subTest(next_session=change), self.assertRaises(ValueError):
                replay.validate_turns([turn(), {**next_session, **change}])
        for invalid in ([second], [next_session], [turn(), next_session, second]):
            with self.subTest(reentry_or_first=invalid), self.assertRaises(ValueError):
                replay.validate_turns(invalid)


class ReplayArtifactTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.dataset = self.root / "dataset"
        self.mapping = self.root / "mapping.json"
        self.prepared = self.root / "prepared"
        self.data_dir = self.root / "btc"
        write_json(self.data_dir / "catalog" / "products.json", [])
        (self.dataset / "audio").mkdir(parents=True)
        (self.dataset / "audio" / "X1.wav").write_bytes(b"synthetic source waveform")
        self.audio = np.full(16000, -.85, dtype=np.float32)  # agent waveform is deliberately disjoint
        self.audio[4000:8000] = np.linspace(.15, .45, 4000, dtype=np.float32)
        self.audio[12000:16000] = np.linspace(.5, 1.2, 4000, dtype=np.float32)
        self.annotations = {"id": "X1", "segments": [
            segment(idx=1, speaker="A", start=0, end=.25, text="AGENT_SENTINEL"),
            segment(idx=2, start=.25, end=.5),
            segment(idx=3, speaker="A", start=.5, end=.75, text="LABEL_SENTINEL"),
            segment(idx=4, start=.75, end=1, text="GT_SENTINEL_2")]}
        write_json(self.dataset / "audio" / "X1.segments.json", self.annotations)
        write_json(self.mapping, {"schema_version": 1, "sessions": [session()]})

    def prepare(self, destination=None):
        with patch.object(replay.au, "decode", return_value=self.audio):
            return replay.prepare_replay(self.mapping, destination or self.prepared)

    def export(self, out=None, raw=None, finalized=None, per_clip_raw=None):
        out = out or self.root / "export"
        pieces = [raw_piece(), raw_piece("giao ngày mai", start=.5, end=.9)] if raw is None else raw
        with patch.object(replay, "load_model", return_value=(Mock(), "cpu", "int8")), \
                patch.object(replay, "runtime_fingerprint", return_value={"model_files": {"model.bin": "fake"}}), \
                patch.object(replay, "decode_segments", return_value=pieces, side_effect=per_clip_raw) as decoder, \
                patch.object(replay.au, "decode", return_value=np.zeros(17600, dtype=np.float32)):
            if finalized is None:
                manifest = replay.export_replay(self.prepared, out, self.data_dir, progress=Mock())
            else:
                with patch.object(replay, "finalize", return_value=finalized):
                    manifest = replay.export_replay(self.prepared, out, self.data_dir, progress=Mock())
        return out, manifest, decoder

    def reseal(self, bundle, name):
        manifest = read_json(bundle / "manifest.json")
        manifest["files"][name] = file_sha256(bundle / name)
        write_json(bundle / "manifest.json", manifest)

    def test_prepare_customer_pcm(self):
        original = self.audio.copy()
        for absolute in (False, True):
            with self.subTest(absolute_dataset=absolute):
                write_json(self.mapping, {"schema_version": 1, "sessions": [
                    session(dataset=str(self.dataset) if absolute else "dataset")]})
                out = self.root / f"prepared-{absolute}"
                manifest = self.prepare(out)
                clips = read_json(out / "clips.json")
                self.assertEqual(manifest["boundary_padding_s"], .3)
                self.assertEqual(manifest["turn_count"], 2)
                self.assertEqual(manifest["mapping_sha256"], text_sha256(self.mapping))
                self.assertEqual(manifest["sources"], [{
                    "session_key": "session1",
                    "audio_sha256": file_sha256(self.dataset / "audio" / "X1.wav"),
                    "segments_sha256": text_sha256(self.dataset / "audio" / "X1.segments.json")}])
                for i, (start, end, source_index) in enumerate(((.25, .5, 2), (.75, 1, 4)), 1):
                    clip = clips[i - 1]
                    path = out / "audio" / f"session1-{source_index}.wav"
                    with wave.open(str(path), "rb") as wav:
                        self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()),
                                         (1, 2, 16000))
                        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
                    center = (np.clip(original[round(start * 16000):round(end * 16000)], -1, 1)
                              * 32767).astype("<i2")
                    expected = np.concatenate((np.zeros(4800, dtype="<i2"), center,
                                               np.zeros(4800, dtype="<i2")))
                    np.testing.assert_array_equal(pcm, expected)
                    self.assertEqual((clip["start"], clip["end"], clip["turn_index"],
                                      clip["source_turn_index"]), (start, end, i, source_index))
                    self.assertEqual(clip["audio_sha256"], file_sha256(path))
                self.assertEqual(replay.verify_bundle(out, "prepared"), manifest)
        np.testing.assert_array_equal(self.audio, original)
        self.assertFalse((self.dataset / "ground_truth.json").exists())

    def test_prepare_sidecar_identity(self):
        for payload in ({**self.annotations, "id": "X2"}, [], None):
            with self.subTest(payload=payload):
                write_json(self.dataset / "audio" / "X1.segments.json", payload)
                with self.assertRaises(ValueError):
                    self.prepare()
                self.assertFalse(self.prepared.exists())

    def test_subsample_clip_rejected(self):
        write_json(self.dataset / "audio" / "X1.segments.json",
                   {"id": "X1", "segments": [segment(start=.25, end=.250001)]})
        with self.assertRaisesRegex(ValueError, "one audio sample"):
            self.prepare()
        self.assertFalse((self.prepared / "manifest.json").exists())
        self.assertEqual(list(self.prepared.glob("audio/*.wav")), [])

    def test_export_written_turns_and_no_reference_leakage(self):
        self.prepare()
        out, manifest, decoder = self.export()
        turns = [json.loads(line) for line in (out / "turns.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(turns), 2)
        self.assertEqual(decoder.call_count, 2)
        for row in turns:
            self.assertEqual(row["text"], "dạ anh chốt COD đơn 4,5 triệu nha giao ngày mai")
            self.assertEqual(set(row), replay.TURN_FIELDS)
            self.assertEqual(row["customer_input_mode"], "asr_transcript")
        payloads = "\n".join(p.read_text(encoding="utf-8") for p in out.rglob("*.json"))
        payloads += (out / "turns.jsonl").read_text(encoding="utf-8")
        for forbidden in ("GT_SENTINEL", "AGENT_SENTINEL", "LABEL_SENTINEL", "memory_enabled"):
            self.assertNotIn(forbidden, payloads)
        self.assertEqual((manifest["status"], manifest["kind"], manifest["turn_count"]), ("ready", "replay", 2))
        info = read_json(out / "run" / "run.json")
        self.assertEqual((info["frozen"], info["profile"], info["device"], info["compute_type"]),
                         (True, "B2", "cpu", "int8"))
        self.assertTrue(info["decode"]["use_hotwords"])
        self.assertEqual(info["catalog_sha256"], text_sha256(self.data_dir / "catalog" / "products.json"))
        self.assertEqual(replay.verify_bundle(out), manifest)

    def test_export_metadata(self):
        write_json(self.mapping, {"schema_version": 1, "sessions": [
            session(), session(session_key="session2", session_index=2, call_date="2026-11-01")]})
        self.prepare()
        with patch.object(replay, "finalize", wraps=replay.finalize) as finalizer:
            out, manifest, decoder = self.export()
        self.assertEqual([c.args[3].isoformat() for c in finalizer.call_args_list],
                         ["2026-10-15"] * 2 + ["2026-11-01"] * 2)
        turns = [json.loads(line) for line in (out / "turns.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual((manifest["turn_count"], decoder.call_count), (4, 4))
        clips = read_json(self.prepared / "clips.json")
        for index, row in enumerate(turns):
            with self.subTest(turn=index):
                self.assertEqual({k: row[k] for k in ("conversation_key", "identity_ref", "session_key",
                    "session_index", "call_date", "turn_index", "source_turn_index", "audio_sha256")},
                    {"conversation_key": "conv", "identity_ref": "synthetic",
                     "session_key": f"session{index // 2 + 1}", "session_index": index // 2 + 1,
                     "call_date": "2026-10-15" if index < 2 else "2026-11-01",
                     "turn_index": index % 2 + 1, "source_turn_index": (2, 4)[index % 2],
                     "audio_sha256": clips[index]["audio_sha256"]})
                name = Path("audio") / f"{row['session_key']}-{row['source_turn_index']}.wav"
                self.assertEqual((out / name).read_bytes(), (self.prepared / name).read_bytes())

    def test_invalid_export_diagnostics(self):
        self.prepare()
        for label, pieces in (("zero", []), ("whitespace", [raw_piece(" \t ")]),
                              ("filtered", [raw_piece("kept raw evidence", no_speech_prob=.9, avg_logprob=-2)])):
            out = self.root / label
            with self.subTest(case=label):
                with self.assertRaisesRegex(ValueError, "invalid/empty"):
                    self.export(out, raw=pieces)
                self.assertFalse((out / "manifest.json").exists())
                self.assertFalse((out / "turns.jsonl").exists())
                diagnostic = read_json(out / "diagnostics.json")
                self.assertEqual(diagnostic["invalid_text_clips"], ["session1-2", "session1-4"])
                self.assertEqual([(x["clip_key"], x["text_length"]) for x in diagnostic["turns"]],
                                 [("session1-2", 0), ("session1-4", 0)])
                self.assertEqual(read_json(out / "run" / "raw.json"),
                                 {"schema_version": 1, "records": {"session1-2": pieces, "session1-4": pieces}})

    def test_partial_empty_export_never_becomes_ready(self):
        self.prepare()
        valid = [raw_piece("customer payment")]
        for empty_index in (0, 1):
            out = self.root / f"partial-{empty_index}"
            records = [valid, valid]
            records[empty_index] = []
            with self.subTest(empty_index=empty_index):
                with self.assertRaisesRegex(ValueError, "invalid/empty"):
                    self.export(out, per_clip_raw=records)
                self.assertFalse((out / "manifest.json").exists())
                self.assertFalse((out / "turns.jsonl").exists())
                diagnostics = read_json(out / "diagnostics.json")
                keys = ["session1-2", "session1-4"]
                self.assertEqual(diagnostics["invalid_text_clips"], [keys[empty_index]])
                self.assertEqual([(d["clip_key"], d["text_length"]) for d in diagnostics["turns"]],
                                 [(key, 0 if i == empty_index else 16) for i, key in enumerate(keys)])
                self.assertEqual(read_json(out / "run" / "raw.json"),
                                 {"schema_version": 1, "records": dict(zip(keys, records))})

    def test_export_text_capacity(self):
        self.prepare()
        for length in (8000, 8001):
            out = self.root / str(length)
            finalized = {"asr_segments": [{"text_written": "x" * length}]}
            with self.subTest(length=length):
                if length == 8000:
                    self.export(out, finalized=finalized)
                    rows = [json.loads(x) for x in (out / "turns.jsonl").read_text().splitlines()]
                    self.assertEqual([row["text"] for row in rows], ["x" * length] * 2)
                    self.assertEqual(replay.verify_bundle(out)["turn_count"], 2)
                else:
                    with self.assertRaisesRegex(ValueError, "invalid/empty"):
                        self.export(out, finalized=finalized)
                    self.assertFalse((out / "manifest.json").exists())
                    self.assertFalse((out / "turns.jsonl").exists())
                    diagnostics = read_json(out / "diagnostics.json")
                    self.assertEqual(diagnostics["invalid_text_clips"], ["session1-2", "session1-4"])
                    self.assertEqual([d["text_length"] for d in diagnostics["turns"]], [8001, 8001])

    def test_output_directory_guard(self):
        self.prepare()
        for kind in ("prepare", "export"):
            for occupied in ("file", "directory", "empty"):
                path = self.root / f"{kind}-{occupied}"
                if occupied == "file":
                    path.write_bytes(b"do not overwrite")
                else:
                    path.mkdir()
                    if occupied == "directory":
                        (path / "sentinel").write_bytes(b"do not overwrite")
                before = path.read_bytes() if path.is_file() else {
                    p.name: p.read_bytes() for p in path.iterdir()}
                with self.subTest(kind=kind, occupied=occupied):
                    action = lambda: self.prepare(path) if kind == "prepare" else self.export(path)
                    if occupied == "empty":
                        action()
                        self.assertTrue((path / "manifest.json").is_file())
                    else:
                        with self.assertRaisesRegex(ValueError, "empty/new"):
                            action()
                        after = path.read_bytes() if path.is_file() else {
                            p.name: p.read_bytes() for p in path.iterdir()}
                        self.assertEqual(after, before)

    def test_bundle_content_integrity(self):
        self.prepare()
        exported, _, _ = self.export()
        cases = ("audio-bytes", "turn-bytes", "clip-duplicate", "clip-hash", "clip-key",
                 "turn-linkage", "turn-audio-unlisted")
        for case in cases:
            with self.subTest(case=case):
                source = self.prepared if case.startswith("clip") else exported
                bundle = self.root / case
                shutil.copytree(source, bundle)
                if case == "audio-bytes":
                    (bundle / "audio" / "session1-2.wav").write_bytes(b"corrupt")
                elif case == "turn-bytes":
                    with (bundle / "turns.jsonl").open("a", encoding="utf-8") as f:
                        f.write("\n")
                elif case.startswith("clip"):
                    clips = read_json(bundle / "clips.json")
                    if case == "clip-duplicate":
                        clips[1]["clip_key"] = clips[0]["clip_key"]
                    elif case == "clip-hash":
                        clips[0]["audio_sha256"] = "f" * 64
                    else:
                        clips[0]["clip_key"] = "unlisted"
                    write_json(bundle / "clips.json", clips)
                    self.reseal(bundle, "clips.json")
                else:
                    rows = [json.loads(x) for x in (bundle / "turns.jsonl").read_text(encoding="utf-8").splitlines()]
                    if case == "turn-linkage":
                        rows[0]["audio_sha256"] = rows[1]["audio_sha256"]
                        (bundle / "turns.jsonl").write_text(
                            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
                        self.reseal(bundle, "turns.jsonl")
                    else:
                        manifest = read_json(bundle / "manifest.json")
                        del manifest["files"][str(Path("audio") / "session1-2.wav")]
                        write_json(bundle / "manifest.json", manifest)
                with self.assertRaises(ValueError):
                    replay.verify_bundle(bundle)

    def test_bundle_manifest_guards(self):
        self.prepare()
        exported, _, _ = self.export()
        for kind, source in (("prepared", self.prepared), ("replay", exported)):
            for case in ("kind", "version", "files-empty", "files-type", "missing", "traversal",
                         "count", "metadata-unlisted", "expected-kind", "empty-rows"):
                with self.subTest(kind=kind, case=case):
                    bundle = self.root / f"{kind}-{case}"
                    shutil.copytree(source, bundle)
                    manifest = read_json(bundle / "manifest.json")
                    metadata = "clips.json" if kind == "prepared" else "turns.jsonl"
                    if case in ("kind", "version", "files-empty", "files-type", "count"):
                        field, value = {"kind": ("kind", "unknown"), "version": ("schema_version", 2),
                                        "files-empty": ("files", {}), "files-type": ("files", []),
                                        "count": ("turn_count", 3)}[case]
                        manifest[field] = value
                    elif case == "traversal":
                        outside = self.root / "outside"
                        outside.write_bytes(b"outside")
                        manifest["files"]["../outside"] = file_sha256(outside)
                    elif case == "metadata-unlisted":
                        del manifest["files"][metadata]
                    elif case == "missing":
                        (bundle / metadata).unlink()
                    elif case == "empty-rows":
                        (bundle / metadata).write_text("[]" if kind == "prepared" else "", encoding="utf-8")
                        manifest["files"][metadata] = file_sha256(bundle / metadata)
                    write_json(bundle / "manifest.json", manifest)
                    expected = "replay" if kind == "prepared" else "prepared"
                    with self.assertRaises((ValueError, FileNotFoundError)):
                        replay.verify_bundle(bundle, expected if case == "expected-kind" else None)
        manifest = read_json(exported / "manifest.json")
        manifest["status"] = "failed"
        write_json(exported / "manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "not ready"):
            replay.verify_bundle(exported)

    def test_portable_bundle_copy(self):
        self.prepare()
        exported, prepared_manifest, _ = self.export()
        with tempfile.TemporaryDirectory() as destination:
            copy_prepared, copy_replay = Path(destination) / "prepared", Path(destination) / "replay"
            shutil.copytree(self.prepared, copy_prepared)
            shutil.copytree(exported, copy_replay)
            expected_prepared = read_json(self.prepared / "manifest.json")
            shutil.rmtree(self.dataset)
            self.mapping.unlink()
            shutil.rmtree(self.prepared)
            shutil.rmtree(exported)
            self.assertEqual(replay.verify_bundle(copy_prepared, "prepared"), expected_prepared)
            self.assertEqual(replay.verify_bundle(copy_replay, "replay"), prepared_manifest)

    def test_single_clip_rounding_padding_and_decode_contract(self):
        start, end = .25004, .49996
        write_json(self.dataset / "audio" / "X1.segments.json",
                   {"id": "X1", "segments": [segment(start=start, end=end)]})
        self.prepare()
        clips = read_json(self.prepared / "clips.json")
        self.assertEqual(len(clips), 1)
        self.assertEqual((clips[0]["start"], clips[0]["end"]), (start, end))
        with wave.open(str(self.prepared / "audio" / "session1-2.wav"), "rb") as wav:
            pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
        expected_center = (self.audio[4001:7999] * 32767).astype("<i2")
        np.testing.assert_array_equal(pcm, np.concatenate((
            np.zeros(4800, dtype="<i2"), expected_center, np.zeros(4800, dtype="<i2"))))
        with patch.object(replay, "finalize", wraps=replay.finalize) as finalizer:
            out, manifest, decoder = self.export()
        self.assertEqual((manifest["turn_count"], decoder.call_count, finalizer.call_count), (1, 1, 1))
        cfg = decoder.call_args.kwargs["cfg"]
        self.assertEqual((cfg.language, cfg.beam_size, cfg.use_hotwords, cfg.segmentation),
                         ("vi", 5, True, "utterance"))
        self.assertEqual(finalizer.call_args.args[3].isoformat(), "2026-10-15")
        row = json.loads((out / "turns.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(row["text"], "dạ anh chốt COD đơn 4,5 triệu nha giao ngày mai")
        self.assertEqual((row["turn_index"], row["source_turn_index"]), (1, 2))

    def test_object_consumers_reject_nonobjects(self):
        for payload in ([], None, True):
            with self.subTest(mapping=payload):
                baseline = {"schema_version": 1, "sessions": [session()]}
                write_json(self.mapping, payload)
                with self.assertRaisesRegex(ValueError, "JSON object"):
                    self.prepare()
                self.assertFalse(self.prepared.exists())
                write_json(self.mapping, baseline)
        self.prepare()
        original = read_json(self.prepared / "manifest.json")
        for payload in ([], None, True):
            with self.subTest(manifest=payload):
                write_json(self.prepared / "manifest.json", payload)
                with self.assertRaisesRegex(ValueError, "JSON object"):
                    replay.verify_bundle(self.prepared)
        write_json(self.prepared / "manifest.json", original)
        self.assertEqual(replay.verify_bundle(self.prepared)["turn_count"], 2)


class ChatRequestBoundaryTests(unittest.TestCase):
    def validate_batch(self, payloads):
        script = """
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))
from app.schemas.chat import ChatRequest
from pydantic import ValidationError
results = []
for payload in json.load(sys.stdin):
    try:
        request = ChatRequest.model_validate(payload)
        results.append({"ok": request.model_dump(mode="json")})
    except ValidationError as exc:
        results.append({"errors": [list(e["loc"]) for e in exc.errors()]})
print(json.dumps({"results": results, "services": sorted(
    x for x in sys.modules if x.split(".")[0] in ("fastapi", "httpx", "sqlalchemy", "langchain"))}))
"""
        result = subprocess.run([sys.executable, "-B", "-c", script],
                                input=json.dumps(payloads), text=True, capture_output=True,
                                cwd=Path(__file__).resolve().parents[2], timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        decoded = json.loads(result.stdout)
        self.assertEqual(decoded["services"], [])
        self.assertEqual(len(decoded["results"]), len(payloads))
        return decoded["results"]

    def request(self, **changes):
        row = turn()
        return {"text": row["text"], "channel": "hotline", "channel_identity": row["identity_ref"],
                "call_date": row["call_date"], "customer_input_mode": row["customer_input_mode"], **changes}

    def test_valid_replay_requests(self):
        first = self.request(text="  decoded COD 4,5 triệu  ")
        phone = {k: v for k, v in self.request(caller_phone="0123456789").items() if k != "channel_identity"}
        continuation = {"session_id": "12345678-1234-5678-9234-567812345678",
                        "text": "next customer turn", "customer_input_mode": "asr_transcript"}
        results = self.validate_batch([first, phone, continuation])
        for i, result in enumerate(results):
            with self.subTest(request=i):
                self.assertIn("ok", result)
                self.assertEqual(result["ok"]["customer_input_mode"], "asr_transcript")
        self.assertEqual(results[0]["ok"]["text"], "decoded COD 4,5 triệu")
        self.assertEqual(results[0]["ok"]["call_date"], "2026-10-15")
        self.assertEqual(results[1]["ok"]["caller_phone"], "0123456789")
        self.assertEqual(results[2]["ok"]["session_id"], continuation["session_id"])
        self.assertEqual(results[2]["ok"]["text"], "next customer turn")
        self.assertIsNone(results[2]["ok"]["call_date"])

    def test_request_boundaries(self):
        cases = []
        for length in (0, 1, 7999, 8000, 8001):
            cases.append((f"text-{length}", self.request(text=" " + "x" * length + " "),
                          1 <= length <= 8000, ["text"]))
        for field in ("channel", "call_date", "channel_identity"):
            cases.append((f"missing-{field}", {k: v for k, v in self.request().items() if k != field},
                          False, []))
        continuation = {"session_id": "12345678-1234-5678-9234-567812345678", "text": "next"}
        for field, value in (("caller_phone", "0123456789"), ("channel_identity", "synthetic"),
                             ("channel", "hotline"), ("call_date", "2026-10-15")):
            cases.append((f"forbidden-{field}", {**continuation, field: value}, False, []))
        results = self.validate_batch([c[1] for c in cases])
        for (name, payload, valid, location), result in zip(cases, results):
            with self.subTest(case=name):
                if valid:
                    self.assertEqual(result["ok"]["text"], payload["text"].strip())
                    self.assertEqual(result["ok"]["call_date"], "2026-10-15")
                else:
                    self.assertIn(location, result["errors"])

    def test_phone_channel_and_mode(self):
        cases = []
        for phone in ("0123456789", "0999999999", "1234567890", "012345678", "01234567890",
                      "+84123456789", "0abcdefghi", " 0123456789"):
            payload = {k: v for k, v in self.request(caller_phone=phone).items() if k != "channel_identity"}
            cases.append((f"phone-{phone}", payload, phone in ("0123456789", "0999999999")))
        for channel in ("hotline", "chat_fanpage", "zalo_oa", "web_chat", "other", "invalid"):
            cases.append((f"channel-{channel}", self.request(channel=channel), channel != "invalid"))
            if channel not in ("hotline", "invalid"):
                cases.append((f"identity-{channel}", {k: v for k, v in self.request(
                    channel=channel, caller_phone="0123456789").items() if k != "channel_identity"}, False))
        for mode in ("clean", "asr_transcript", "chat_teencode", "invalid"):
            cases.append((f"mode-{mode}", self.request(customer_input_mode=mode), mode != "invalid"))
        default = {k: v for k, v in self.request().items() if k != "customer_input_mode"}
        cases.append(("default", default, True))
        for (name, payload, valid), result in zip(cases, self.validate_batch([c[1] for c in cases])):
            with self.subTest(case=name):
                if valid:
                    self.assertEqual(result["ok"]["customer_input_mode"], payload.get("customer_input_mode", "clean"))
                    self.assertEqual(result["ok"]["channel"], payload["channel"])
                    self.assertEqual(result["ok"]["caller_phone"], payload.get("caller_phone"))
                else:
                    self.assertIn("errors", result)
                    self.assertNotEqual(result["errors"], [])
