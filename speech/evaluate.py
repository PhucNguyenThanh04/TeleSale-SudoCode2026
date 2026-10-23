"""Chấm ``hypotheses.json`` bằng chính ``reference_eval.wer_cer`` của BTC, kèm vài số đo phụ để phân tích.

* ``WER``/``CER``/``entity_accuracy``: số chính thức theo script BTC.
* ``wer_raw``: WER nếu nộp nguyên chữ Whisper (chỉ qua chuẩn hóa của BTC) → cho thấy tác dụng của lexicon + TN.
* ``oracle_entity_accuracy``: trích entity từ chính transcript đúng → tách lỗi ASR khỏi lỗi bộ trích entity.
* ``asr_time``: giây ASR / phút audio (đơn vị BTC yêu cầu báo riêng ở M1), tổng + p50/p95 theo file.

Script BTC bỏ qua hội thoại không có trong ``hypotheses.json`` (điểm sẽ đẹp giả), nên ở đây thiếu ID là lỗi.
"""
from __future__ import annotations

import json
import shutil
import tempfile
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
        merged, _ = extract_entities(written, catalog, ref)
        for key, value in dialogue.get("entities", {}).items():
            total += 1
            ok += str(merged.get(key)) == str(value)
    return {"oracle_entity_accuracy": round(100 * ok / total, 1) if total else None, "n_entities": total}


def coverage(ground_truth: dict, hypotheses: dict) -> dict:
    """Đếm hội thoại; ``ValueError`` nếu thiếu ID vì ``reference_eval`` sẽ lặng lẽ bỏ qua chúng."""
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
    """Giây ASR cho mỗi phút audio. Không tính thời gian nạp model (ghi riêng ở ``load_s``)."""
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
    """Run có được tạo từ đúng ``ground_truth.json`` này không (hash ghi trong ``run.json`` lúc transcribe).

    ``None`` = không kiểm được (run cũ chưa ghi hash, hoặc transcribe không thấy ground truth cạnh audio).
    Chỉ khớp theo ID là chưa đủ: hai dataset khác kịch bản có thể dùng chung ID (ví dụ ``T02``).
    """
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
    for dialogue in ground_truth["dialogues"]:
        hyp = hypotheses.get(dialogue["id"])
        if hyp is None or dialogue["id"] not in per_dialogue:
            continue
        gold = dialogue.get("entities", {})
        hits = sum(str(hyp.get("entities", {}).get(k)) == str(v) for k, v in gold.items())
        per_dialogue[dialogue["id"]]["entity"] = f"{hits}/{len(gold)}"
        per_dialogue[dialogue["id"]]["wer_raw"] = raw_scores["per_dialogue"].get(dialogue["id"], {}).get("wer")
        per_dialogue[dialogue["id"]]["rtf"] = hyp.get("meta", {}).get("rtf")
    run_info = read_json(run_dir / "run.json") if (run_dir / "run.json").exists() else {}
    current = rules_fingerprint()
    report = {"run": run_dir.name, "dataset": dataset_dir.name, "model": run_info.get("model"),
              "device": run_info.get("device"), "compute_type": run_info.get("compute_type"),
              "decode": run_info.get("decode"), "rtf": run_info.get("rtf"),
              "lexicon_sha256": run_info.get("lexicon_sha256"), "rules_sha256": run_info.get("rules_sha256"),
              # True = hypotheses tạo bằng bộ luật khác bộ hiện tại → chạy `renormalize` trước khi so sánh.
              "rules_stale": run_info.get("rules_sha256") != current["rules_sha256"],
              # False = run tạo từ ground truth khác dataset đang chấm; None = run cũ, không kiểm được.
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
