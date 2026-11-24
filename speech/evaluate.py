from __future__ import annotations

import json
from hashlib import sha256
import shutil
import tempfile
from datetime import date
from pathlib import Path
from types import ModuleType

from .btc import read_json, reference_date, text_sha256
from .entities import Product, extract_entities
from .normalize import normalize_text, rules_fingerprint
from .textutil import btc_norm


def _wer_cer(ref_eval: ModuleType, ground_truth: dict, hypotheses: dict, segments_dir: Path | None = None) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        with open(Path(tmp) / "ground_truth.json", "w", encoding="utf-8") as fh:
            json.dump(ground_truth, fh, ensure_ascii=False)
        with open(Path(tmp) / "hypotheses.json", "w", encoding="utf-8") as fh:
            json.dump(hypotheses, fh, ensure_ascii=False)
        if segments_dir is not None:
            shutil.copytree(segments_dir, Path(tmp) / "audio", ignore=shutil.ignore_patterns("*.wav", "*.mp3"))
        return ref_eval.wer_cer(tmp)


def _has_speakers(hypotheses: dict) -> bool:
    return any(turn.get("speaker") for h in hypotheses.values() for turn in h.get("turns", []))


def oracle_entities(ground_truth: dict, catalog: tuple[Product, ...]) -> dict:
    ok = total = 0
    ref = reference_date(ground_truth)
    for dialogue in ground_truth["dialogues"]:
        written = [normalize_text(turn["text"]).written for turn in dialogue["turns"]]
        on = date.fromisoformat(dialogue["call_date"]) if dialogue.get("call_date") else ref
        merged, _ = extract_entities(written, catalog, on)
        for key, value in dialogue.get("entities", {}).items():
            total += 1
            values = value if isinstance(value, list) else [value]
            ok += any(str(merged.get(key)) == str(v) for v in values)
    return {"oracle_entity_accuracy": round(100 * ok / total, 1) if total else None, "n_entities": total}


def coverage(ground_truth: dict, hypotheses: dict) -> dict:
    expected = [d["id"] for d in ground_truth["dialogues"]]
    missing = [i for i in expected if i not in hypotheses]
    if missing:
        raise ValueError(f"hypotheses.json thiếu {len(missing)}/{len(expected)} hội thoại: {', '.join(missing)}")
    return {"expected": len(expected), "processed": len(expected),
            "empty": sum(not hypotheses[i].get("text", "").strip() for i in expected),
            "extra": sorted(set(hypotheses) - set(expected))}


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def asr_time(hypotheses: dict, run_info: dict) -> dict | None:
    metas = [h.get("meta", {}) for h in hypotheses.values()]
    metas = [m for m in metas if m.get("audio_s") and m.get("asr_s") is not None]
    if not metas:
        return None
    per_file = [60 * m["asr_s"] / m["audio_s"] for m in metas]
    total_audio = sum(m["audio_s"] for m in metas)
    return {"s_per_audio_min": round(60 * sum(m["asr_s"] for m in metas) / total_audio, 1),
            "p50": round(_percentile(per_file, 0.5), 1), "p95": round(_percentile(per_file, 0.95), 1),
            "audio_min": round(total_audio / 60, 2), "load_s": run_info.get("load_s")}


def ground_truth_check(dataset_dir: Path, run_info: dict) -> bool | None:
    recorded = run_info.get("ground_truth_sha256")
    if not recorded:
        return None
    return recorded == text_sha256(dataset_dir / "ground_truth.json")


def score_run(dataset_dir: Path, run_dir: Path, ref_eval: ModuleType, catalog: tuple[Product, ...]) -> dict:
    ground_truth = read_json(dataset_dir / "ground_truth.json")
    hypotheses = read_json(run_dir / "hypotheses.json")
    counts = coverage(ground_truth, hypotheses)
    segments_dir = dataset_dir / "audio" if _has_speakers(hypotheses) and (dataset_dir / "audio").is_dir() else None
    official = _wer_cer(ref_eval, ground_truth, hypotheses, segments_dir)
    raw = {key: {"text": btc_norm(" ".join(s.get("raw", "") for s in h.get("asr_segments", [])))}
           for key, h in hypotheses.items()}
    raw_scores = _wer_cer(ref_eval, ground_truth, raw)
    per_dialogue = official.pop("per_dialogue", {})
    entity_types = {key: {'correct': 0, 'total': 0} for key in ('money', 'phone')}
    for dialogue in ground_truth["dialogues"]:
        hyp = hypotheses.get(dialogue["id"])
        if hyp is None or dialogue["id"] not in per_dialogue:
            continue
        gold = dialogue.get("entities", {})
        for key, value in gold.items():
            kind = 'money' if key.endswith('_vnd') else 'phone' if key == 'phone' else None
            if kind:
                values = value if isinstance(value, list) else [value]
                entity_types[kind]['total'] += 1
                entity_types[kind]['correct'] += int(any(
                    str(hyp.get('entities', {}).get(key)) == str(v) for v in values))
        hits = sum(any(str(hyp.get('entities', {}).get(k)) == str(v)
                       for v in (value if isinstance(value, list) else [value])) for k, value in gold.items())
        per_dialogue[dialogue["id"]]["entity"] = f"{hits}/{len(gold)}"
        per_dialogue[dialogue["id"]]["wer_raw"] = raw_scores["per_dialogue"].get(dialogue["id"], {}).get("wer")
        per_dialogue[dialogue["id"]]["rtf"] = hyp.get("meta", {}).get("rtf")
    run_info = read_json(run_dir / "run.json") if (run_dir / "run.json").exists() else {}
    current = rules_fingerprint()
    for counts_by_type in entity_types.values():
        counts_by_type['value'] = (round(100 * counts_by_type['correct'] / counts_by_type['total'], 1)
                                   if counts_by_type['total'] else None)
    inputs = {'ground_truth': dataset_dir / 'ground_truth.json',
              'hypotheses': run_dir / 'hypotheses.json', 'run_metadata': run_dir / 'run.json'}
    scorer_path = getattr(ref_eval, '__file__', None)
    report = {"run": run_dir.name, "dataset": dataset_dir.name, "model": run_info.get("model"),
              'input_sha256': {key: sha256(path.read_bytes()).hexdigest()
                               for key, path in inputs.items() if path.is_file()},
              'audio_sha256': {d['id']: sha256(path.read_bytes()).hexdigest()
                               for d in ground_truth['dialogues']
                               if (path := dataset_dir / 'audio' / (d['id'] + '.wav')).is_file()},
              'scorer_sha256': sha256(Path(scorer_path).read_bytes()).hexdigest() if scorer_path else None,
              'entity_accuracy_by_type': entity_types,
              "device": run_info.get("device"), "compute_type": run_info.get("compute_type"),
              "decode": run_info.get("decode"), "rtf": run_info.get("rtf"),
              "lexicon_sha256": run_info.get("lexicon_sha256"), "rules_sha256": run_info.get("rules_sha256"),
              "rules_stale": run_info.get("rules_sha256") != current["rules_sha256"],
              "ground_truth_match": ground_truth_check(dataset_dir, run_info), "dialogues": counts,
              "asr_time": asr_time(hypotheses, run_info), "official": official, "wer_raw": raw_scores["WER"], "cer_raw": raw_scores["CER"],
              **oracle_entities(ground_truth, catalog), "per_dialogue": per_dialogue}
    with open(run_dir / "score.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    return report


def markdown_table(reports: list[dict]) -> str:
    lines = ["| Run | Model | Thiết bị | WER | CER | WER thô | Entity | Oracle entity | RTF | "
             "Giây ASR/phút audio (p50/p95) |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in reports:
        o, t = r["official"], r.get("asr_time")
        timing = f"{t['s_per_audio_min']} ({t['p50']}/{t['p95']})" if t else "–"
        lines.append(f"| {r['run']} | {r['model']} | {r['device']}/{r['compute_type']} | {o['WER']} | {o['CER']} | "
                     f"{r['wer_raw']} | {o['entity_accuracy']} | {r['oracle_entity_accuracy']} | {r['rtf']} | "
                     f"{timing} |")
    dialogue_ids = sorted({d for r in reports for d in r["per_dialogue"]})
    if dialogue_ids:
        lines += ["", "| Run | " + " | ".join(f"{d} WER (entity)" for d in dialogue_ids) + " |",
                  "|---|" + "---:|" * len(dialogue_ids)]
        for r in reports:
            cells = []
            for d in dialogue_ids:
                p = r["per_dialogue"].get(d)
                cells.append(f"{p['wer']} ({p['entity']})" if p else "–")
            lines.append(f"| {r['run']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)
