"""Reproducible B0/B1/B2 experiments; labels are used only by offline scoring."""
from __future__ import annotations

import hashlib
import json
import platform
import time
from dataclasses import asdict, replace
from collections.abc import Callable
from datetime import date
from importlib.metadata import version
from pathlib import Path

from . import audio as au
from .asr import DecodeConfig, VadConfig, decode_segments, finalize, hotword_filter_terms, load_model, resolve_model
from .btc import load_catalog, load_reference_eval, read_json_object, reference_date, text_sha256
from .evaluate import _wer_cer, markdown_table, score_run
from .normalize import default_lexicon, rules_fingerprint
from .tts import file_sha256

PROFILES = {"B0": {"hotwords": False, "postprocess": False},
            "B1": {"hotwords": False, "postprocess": True},
            "B2": {"hotwords": True, "postprocess": True}}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def object_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def new_directory(path: Path) -> None:
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError(f"Output must be an empty/new directory: {path}")
    path.mkdir(parents=True, exist_ok=True)


def runtime_fingerprint(model_name: str) -> dict:
    model_path = resolve_model(model_name)
    model_files = {p.name: file_sha256(p) for p in sorted(model_path.iterdir()) if p.is_file()}
    sources = ("asr.py", "baseline.py", "evaluate.py", "audio.py", "btc.py")
    return {**rules_fingerprint(), "model_files": model_files,
            "code": {name: text_sha256(Path(__file__).with_name(name)) for name in sources},
            "python": platform.python_version(), "platform": platform.platform(),
            "dependencies": {name: version(name) for name in ("faster-whisper", "ctranslate2", "numpy", "av")}}


def dataset_inputs(datasets: list[Path]) -> tuple[dict, list[dict]]:
    if not datasets:
        raise ValueError("At least one dataset is required")
    dialogues, inputs, seen, names = [], [], set(), set()
    for dataset in datasets:
        if dataset.name in names:
            raise ValueError("Dataset names must be unique")
        names.add(dataset.name)
        gt = read_json_object(dataset / "ground_truth.json")
        manifest = read_json_object(dataset / "manifest.json")
        if not isinstance(gt.get("dialogues"), list):
            raise ValueError("Expected ground truth dialogues list")
        gt_hash = text_sha256(dataset / "ground_truth.json")
        if manifest.get("ground_truth_sha256") != gt_hash:
            raise ValueError(f"Missing/mismatched ground truth provenance: {dataset.name}")
        for dialogue in gt["dialogues"]:
            if not isinstance(dialogue, dict) or "id" not in dialogue:
                raise ValueError("Invalid ground truth dialogue")
            key = dialogue["id"]
            if not isinstance(key, str) or not key or Path(key).name != key or key in seen:
                raise ValueError("Invalid or duplicate dialogue ID")
            seen.add(key)
            audio_path = dataset / "audio" / f"{key}.wav"
            raw_date = dialogue["call_date"] if "call_date" in dialogue else reference_date(gt).isoformat()
            if not isinstance(raw_date, str):
                raise ValueError("call_date must be YYYY-MM-DD")
            on = date.fromisoformat(raw_date)
            if on.isoformat() != raw_date:
                raise ValueError("call_date must be YYYY-MM-DD")
            dialogues.append({**dialogue, "call_date": on.isoformat()})
            inputs.append({"id": key, "dataset": dataset.name, "audio": str(audio_path.resolve()),
                           "audio_sha256": file_sha256(audio_path), "call_date": on.isoformat(),
                           "ground_truth_sha256": gt_hash, "manifest_sha256": text_sha256(dataset / "manifest.json"),
                           "split": dialogue.get("split", "unspecified"), "noisy": bool(dialogue.get("noisy"))})
    if not inputs:
        raise ValueError("Dataset has no dialogues")
    return {"dialogues": dialogues}, inputs


def run_baselines(datasets: list[Path], out: Path, data_dir: Path, *, model_name: str = "whisper-turbo",
                  device: str = "cpu", compute_type: str = "int8", cfg: DecodeConfig = DecodeConfig(),
                  vad: VadConfig = VadConfig(), progress: Callable[..., None] = print) -> dict:
    ground_truth, inputs = dataset_inputs(datasets)
    new_directory(out)
    write_json(out / "ground_truth.json", ground_truth)
    catalog = load_catalog(data_dir)
    lexicon = default_lexicon()
    fingerprint = runtime_fingerprint(model_name)
    common = {"schema_version": 1, "model": model_name, "fingerprint": fingerprint, "inputs": inputs,
              "catalog_sha256": text_sha256(data_dir / "catalog" / "products.json"),
              "evaluator_sha256": text_sha256(data_dir / "eval" / "reference_eval.py"),
              "vad": asdict(vad), "ground_truth_sha256": text_sha256(out / "ground_truth.json")}
    write_json(out / "experiment.json", common)
    started = time.perf_counter()
    model, used_device, used_type = load_model(model_name, device, compute_type)
    load_s = time.perf_counter() - started
    hyps = {key: {} for key in PROFILES}
    raw_records = {key: {} for key in PROFILES}
    for item in inputs:
        audio = au.decode(Path(item["audio"]))
        if not audio.size:
            raise ValueError(f"Empty audio: {item['id']}")
        audio_s = audio.size / au.SAMPLE_RATE
        for hot in (False, True):
            decode_cfg = replace(cfg, use_hotwords=hot)
            started = time.perf_counter()
            pieces = decode_segments(model, audio, cfg=decode_cfg, vad=vad, lexicon=lexicon)
            decode_s = time.perf_counter() - started
            raw = {"schema_version": 1, "segments": pieces, "decode_s": decode_s, "audio_s": audio_s}
            for profile in (("B2",) if hot else ("B0", "B1")):
                started = time.perf_counter()
                record = finalize(pieces, lexicon, catalog, date.fromisoformat(item["call_date"]),
                                  hotword_filter_terms(lexicon, decode_cfg),
                                  postprocess=PROFILES[profile]["postprocess"])
                post_s = time.perf_counter() - started
                asr_s = decode_s + post_s
                record["meta"] = {"audio_s": audio_s, "asr_s": asr_s, "decode_s": decode_s,
                                  "postprocess_s": post_s, "rtf": asr_s / audio_s}
                hyps[profile][item["id"]] = record
                raw_records[profile][item["id"]] = raw
                run = out / profile
                write_json(run / "hypotheses.json", hyps[profile])
                write_json(run / "raw.json", raw_records[profile])
                total_audio = sum(h["meta"]["audio_s"] for h in hyps[profile].values())
                total_asr = sum(h["meta"]["asr_s"] for h in hyps[profile].values())
                info = {**common, **rules_fingerprint(), "profile": profile, "frozen": True,
                        "postprocess": PROFILES[profile]["postprocess"], "decode": asdict(decode_cfg),
                        "device": used_device, "compute_type": used_type, "load_s": load_s,
                        "audio_s": total_audio, "asr_s": total_asr, "rtf": total_asr / total_audio,
                        "decode_reused": profile == "B1", "raw_sha256": file_sha256(run / "raw.json"),
                        "hypotheses_sha256": file_sha256(run / "hypotheses.json"),
                        "experiment_sha256": file_sha256(out / "experiment.json")}
                write_json(run / "run.json", info)
            progress(f"{item['id']} hotwords={hot}: {decode_s:.1f}s / {audio_s:.1f}s audio", flush=True)
    return compare_baselines(out, data_dir)


def verify_experiment(out: Path, data_dir: Path) -> tuple[dict, dict, dict]:
    experiment = read_json_object(out / "experiment.json")
    gt = read_json_object(out / "ground_truth.json")
    if text_sha256(out / "ground_truth.json") != experiment["ground_truth_sha256"]:
        raise ValueError("Experiment ground truth changed")
    if text_sha256(data_dir / "eval" / "reference_eval.py") != experiment["evaluator_sha256"]:
        raise ValueError("Evaluator changed")
    if text_sha256(data_dir / "catalog" / "products.json") != experiment["catalog_sha256"]:
        raise ValueError("Catalog changed")
    expected = [item["id"] for item in experiment["inputs"]]
    if len(set(expected)) != len(expected) or sorted(expected) != sorted(d["id"] for d in gt["dialogues"]):
        raise ValueError("Experiment ID mismatch")
    for item in experiment["inputs"]:
        if file_sha256(Path(item["audio"])) != item["audio_sha256"]:
            raise ValueError(f"Source audio changed: {item['id']}")
        dataset = Path(item["audio"]).parent.parent
        if (text_sha256(dataset / "ground_truth.json") != item["ground_truth_sha256"]
                or text_sha256(dataset / "manifest.json") != item["manifest_sha256"]):
            raise ValueError(f"Source labels/manifest changed: {item['id']}")
    infos, hypotheses = {}, {}
    for profile, config in PROFILES.items():
        run = out / profile
        info = read_json_object(run / "run.json")
        for name in ("raw", "hypotheses"):
            if info.get(f"{name}_sha256") != file_sha256(run / f"{name}.json"):
                raise ValueError(f"{profile}: {name} changed")
        if (info.get("experiment_sha256") != file_sha256(out / "experiment.json")
                or info.get("profile") != profile or info.get("postprocess") != config["postprocess"]
                or info.get("decode", {}).get("use_hotwords") != config["hotwords"]):
            raise ValueError(f"{profile}: profile/provenance mismatch")
        for field, value in experiment.items():
            if info.get(field) != value:
                raise ValueError(f"{profile}: incompatible {field}")
        hypotheses[profile] = read_json_object(run / "hypotheses.json")
        raw = read_json_object(run / "raw.json")
        if set(hypotheses[profile]) != set(expected) or set(raw) != set(expected):
            raise ValueError(f"{profile}: missing/extra IDs")
        infos[profile] = info
    base = infos["B0"]
    for profile in ("B1", "B2"):
        for field in ("device", "compute_type"):
            if infos[profile][field] != base[field]:
                raise ValueError(f"Incompatible {field}")
        if {k: v for k, v in infos[profile]["decode"].items() if k != "use_hotwords"} != {
                k: v for k, v in base["decode"].items() if k != "use_hotwords"}:
            raise ValueError("Incompatible decode settings")
    if infos["B0"]["raw_sha256"] != infos["B1"]["raw_sha256"]:
        raise ValueError("B0/B1 must share the same raw decode")
    return experiment, gt, hypotheses


def compare_baselines(out: Path, data_dir: Path) -> dict:
    experiment, gt, hypotheses = verify_experiment(out, data_dir)
    ref_eval = load_reference_eval(data_dir)
    catalog = load_catalog(data_dir)
    reports = [score_run(out, out / profile, ref_eval, catalog) for profile in PROFILES]
    groups = {"all": experiment["inputs"]}
    for field in ("dataset", "split", "noisy"):
        for value in sorted({str(i[field]) for i in experiment["inputs"]}):
            groups[f"{field}:{value}"] = [i for i in experiment["inputs"] if str(i[field]) == value]
    scores = {}
    for group, items in groups.items():
        ids = {i["id"] for i in items}
        subset = {"dialogues": [d for d in gt["dialogues"] if d["id"] in ids]}
        scores[group] = {p: _wer_cer(ref_eval, subset, {k: v for k, v in h.items() if k in ids})
                         for p, h in hypotheses.items()}
    deltas = {}
    for left, right in (("B0", "B1"), ("B1", "B2"), ("B0", "B2")):
        deltas[f"{left}->{right}"] = {
            metric: round(scores["all"][right][metric] - scores["all"][left][metric], 2)
            for metric in ("WER", "CER", "entity_accuracy")}
    notes = ["B0 includes VAD/cleanup; its WER includes representation mismatch.",
             "B0/B1 share no-hotword decode; B2 includes hotword echo filtering.",
             "Subsets are re-scored by BTC; no averaging of per-dataset percentages.",
             "Split labels do not prove unseen holdout. No memory metrics measured."]
    comparison = {"schema_version": 1, "experiment_sha256": file_sha256(out / "experiment.json"),
                  "scorer_code_sha256": text_sha256(Path(__file__)),
                  "evaluator_sha256": experiment["evaluator_sha256"],
                  "profiles": PROFILES, "groups": scores, "delta_percentage_points": deltas,
                  "notes": notes}
    write_json(out / "comparison.json", comparison)
    text = "# ASR B0/B1/B2\n\n" + markdown_table(reports)
    text += "\n\n| Comparison (right - left, pp) | WER | CER | Entity |\n|---|---:|---:|---:|\n"
    for name, delta in deltas.items():
        text += f"| {name} | {delta['WER']} | {delta['CER']} | {delta['entity_accuracy']} |\n"
    text += "\nNegative WER/CER and positive Entity deltas are improvements.\n\n"
    text += "\n".join(f"- {note}" for note in notes) + "\n"
    text += "\n| Group | Profile | Files | Entities | WER | CER | Entity |\n|---|---|---:|---:|---:|---:|---:|\n"
    for group, profiles in scores.items():
        for profile, s in profiles.items():
            text += (f"| {group} | {profile} | {s['n_dialogues']} | {s['n_entities']} | "
                     f"{s['WER']} | {s['CER']} | {s['entity_accuracy']} |\n")
    (out / "report.md").write_text(text, encoding="utf-8")
    return comparison
