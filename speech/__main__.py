"""CLI: ``python -m speech <lệnh>``.

  voices       liệt kê giọng tiếng Việt (edge-tts / ElevenLabs Voice Library), thêm giọng vào My Voices
  synth        kịch bản hội thoại → audio + ground_truth.json + segments.json
  manual-export checklist tạo clip ElevenLabs thủ công trên web; nhập lại bằng synth --engine files
  validate     kiểm kịch bản tự viết (định dạng, dạng nói, giá/KM/tồn kho theo mock_tools BTC)
  transcribe   audio → hypotheses.json đúng format BTC
  renormalize  chạy lại chuẩn hóa + entity trên chữ thô đã lưu (sửa lexicon xong không cần chạy lại ASR)
  eval         chấm bằng reference_eval.py của BTC, so sánh nhiều run
  normalize    xem một câu đi qua các bước chuẩn hóa (debug)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}


def _voice_config(path: str | None) -> dict:
    candidates = [Path(path)] if path else [PACKAGE_DIR / "voices.json", PACKAGE_DIR / "voices.example.json"]
    for candidate in candidates:
        if candidate.is_file():
            with open(candidate, encoding="utf-8") as fh:
                return json.load(fh)
    raise FileNotFoundError(f"Không thấy cấu hình giọng: {candidates}")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)


def _dataset_ground_truth(audio: Path) -> Path | None:
    """``ground_truth.json`` của dataset chứa ``audio`` (thư mục ``<dataset>/audio`` hoặc một file trong đó)."""
    path = (audio if audio.is_dir() else audio.parent).parent / "ground_truth.json"
    return path if path.is_file() else None


def _provenance(source_path: Path, noise_path: str | None, team_preview: bool) -> dict:
    """Nguồn của dataset ghi vào manifest: đường dẫn đầy đủ + sha256 của kịch bản (và file nhiễu nếu có)."""
    from .btc import text_sha256
    from .tts import file_sha256

    source = {"file": str(source_path.resolve()), "sha256": text_sha256(source_path)}
    noise = {"file": str(Path(noise_path).resolve()), "sha256": file_sha256(noise_path)} if noise_path else None
    return {"source": source, "noise": noise, "team_preview": team_preview}


def cmd_voices(args: argparse.Namespace) -> None:
    from . import tts

    if args.engine == "edge":
        for voice in tts.list_edge_voices():
            print(f"{voice['voice']:<28} {voice['gender']:<7} {voice['locale']}")
        return
    if args.engine == "vieneu":
        from vieneu import Vieneu

        for label, voice_id in Vieneu().list_preset_voices():
            print(f"{voice_id:<16} {label}")
        return
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        sys.exit("Cần biến môi trường ELEVENLABS_API_KEY để tìm giọng trong Voice Library.")
    if args.add:
        owner, _, voice_id = args.add.partition(":")
        result = tts.add_eleven_shared(api_key, owner, voice_id, args.name or voice_id)
        print(f"Đã thêm vào My Voices: voice_id={result.get('voice_id', voice_id)}")
        return
    for v in tts.list_eleven_shared(api_key, accent=args.accent, gender=args.gender):
        print(f"{v['voice_id']}  owner={v['public_owner_id']}  {v['name']!s:<24} {v['gender']!s:<7} "
              f"{v['accent']!s:<10} {v['age']!s:<12} {v['use_case']!s:<16} free={v['free_users_allowed']}")


def _team_source(source: dict, args: argparse.Namespace, config: dict) -> dict:
    """Bản mẫu giọng clone (tv1–tv3, {kh}) → điền vùng/giới theo team_voices.json hoặc đội giả lập để nghe thử."""
    from .team import PREVIEW_TEAM, fill_team, is_template, load_team_voices, team_voice_entries

    if not any(is_template(d) for d in source["dialogues"]):
        return source
    if args.team_voices:
        try:
            team = load_team_voices(args.team_voices)
        except ValueError as exc:
            sys.exit(str(exc))
        if args.engine == "vieneu":
            config.setdefault("vieneu", {}).setdefault("voices", {}).update(team_voice_entries(team))
        return fill_team(source, team)
    if args.preview_team:
        return {**fill_team(source, PREVIEW_TEAM), "team_preview": True}
    sys.exit("Kịch bản có bản mẫu giọng clone (agent_voice/customer_voice = tv1–tv3): cần --team-voices "
             "speech/data/team_voices.json, hoặc --preview-team để nghe thử bằng giọng có sẵn.")


def _files_config(dialogues: list[dict], inbox: str | None) -> dict:
    from .manual import check_rates, clip_seconds, files_config, scan_inbox

    if not inbox:
        sys.exit("--engine files cần --inbox (ví dụ speech/data/inbox/elevenlabs).")
    scan = scan_inbox(dialogues, Path(inbox))
    for line in scan.lines():
        print(line)
    for warning in check_rates(dialogues, scan.clips, clip_seconds):
        print(f"cảnh báo: {warning}")
    if not scan.complete:
        sys.exit(f"Chưa đủ clip: thiếu {len(scan.missing)}, lỗi {len(scan.errors)} → chưa tạo dataset.")
    print(f"Đủ {len(scan.clips)} clip cho {len(dialogues)} hội thoại.")
    return files_config(scan)


def cmd_synth(args: argparse.Namespace) -> None:
    from . import audio as au
    from . import tts
    from .btc import find_data_dir, read_json

    source_path = (find_data_dir(args.data_dir) / "asr" / "ground_truth.json" if args.dialogues == "btc"
                   else Path(args.dialogues))
    source = read_json(source_path)
    only = set(args.only.split(",")) if args.only else None
    if args.engine == "files":
        source = _team_source(source, args, {})
        dialogues = [d for d in source["dialogues"] if not only or d["id"] in only]
        config = _files_config(dialogues, args.inbox)
        if args.dry_run:
            return
    else:
        config = _voice_config(args.voices)
        source = _team_source(source, args, config)
    if args.no_pronounce:
        config.get(args.engine, {}).pop("pronounce", None)
    if args.dry_run:
        dialogues = [d for d in source["dialogues"] if not only or d["id"] in only]
        rows = tts.plan(dialogues, args.engine, config)
        for row in rows:
            voice = row["params"].get("voice") or row["params"].get("voice_id")
            print(f"{row['dialogue']}.{row['idx']} {row['speaker']} {row['voice_key']:<10} {voice}")
        chars = sum(len(row["text"]) for row in rows)
        print(f"Tổng {len(rows)} câu, {chars} ký tự.")
        if args.engine == "elevenlabs":
            model_id = config.get("elevenlabs", {}).get("model_id", tts.DEFAULT_ELEVEN_MODEL)
            print(f"Ước tính ~{chars * tts.credits_per_char(model_id):.0f} credit với {model_id} "
                  "(câu đã có trong cache không tính lại).")
        return
    noise = au.decode(args.noise) if args.noise else None
    manifest = tts.synth_dataset(source, Path(args.out), engine=args.engine, config=config,
                                 cache_dir=Path(args.cache_dir), channel=args.channel, snr_db=args.snr,
                                 seed=args.seed, noise=noise, only=only, add_noise=not args.no_noise,
                                 provenance=_provenance(source_path, args.noise, bool(source.get("team_preview"))))
    total = sum(d["duration_s"] for d in manifest["dialogues"])
    print(f"Đã tạo {len(manifest['dialogues'])} hội thoại ({total:.0f}s audio) tại {args.out}; "
          f"ký tự mới gửi lên dịch vụ TTS: {manifest['new_chars_synthesized']}.")
    if source.get("team_preview"):
        print("Lưu ý: vùng/giới của tv1–tv3 là đội giả lập (--preview-team) → dataset chỉ để nghe thử, không để chấm.")


def cmd_manual_export(args: argparse.Namespace) -> None:
    from .btc import read_json
    from .manual import export_checklist

    only = set(args.only.split(",")) if args.only else None
    try:
        summary = export_checklist(read_json(args.dialogues), Path(args.out), _voice_config(args.voices), only)
    except (KeyError, ValueError) as exc:
        sys.exit(str(exc))
    print(f"Checklist: {summary['dialogues']} hội thoại, {summary['rows']} câu, {summary['chars']} ký tự "
          f"≈ {summary['credits']:.0f} credit theo giá API ({summary['model_id']}), tối đa "
          f"{summary['credits_web_max']:.0f} nếu web tính 1 credit/ký tự → {Path(args.out) / 'checklist.md'} "
          f"và checklist.csv; thả mp3 vào {Path(args.out) / '<ID>'}")


def cmd_validate(args: argparse.Namespace) -> None:
    import warnings

    from .btc import find_data_dir, read_json
    from .validate import Reference, format_report, validate

    warnings.simplefilter("ignore", ResourceWarning)  # mock_tools BTC mở file JSON không đóng
    ref = Reference.load(find_data_dir(args.data_dir))
    report = validate([(path, read_json(path)) for path in args.dialogues], ref)
    text = format_report(report)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    if report.errors:
        sys.exit(1)


def _audio_paths(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    return sorted(p for p in target.iterdir() if p.suffix.lower() in AUDIO_SUFFIXES)


def cmd_transcribe(args: argparse.Namespace) -> None:
    from .asr import DecodeConfig, VadConfig, transcribe_files
    from .btc import find_data_dir, load_catalog, read_json, reference_date, text_sha256
    from .entities import REFERENCE_DATE

    target = Path(args.audio)
    paths = _audio_paths(target)
    if not paths:
        sys.exit(f"Không có file âm thanh trong {target}")
    gt_path = _dataset_ground_truth(target)
    if args.reference_date:
        ref = date.fromisoformat(args.reference_date)
    else:
        ref = reference_date(read_json(gt_path)) if gt_path else REFERENCE_DATE
    catalog = load_catalog(find_data_dir(args.data_dir, required=False))
    if not catalog:
        print("Cảnh báo: không thấy catalog BTC nên sẽ không trích được SKU (đặt BTC_DATA_DIR hoặc --data-dir).")
    cfg = DecodeConfig(language=args.language, beam_size=args.beam_size, use_hotwords=not args.no_hotwords,
                       segmentation=args.segmentation)
    vad = VadConfig(threshold=args.vad_threshold, min_silence_ms=args.min_silence_ms)
    print(f"Model {args.model}: {len(paths)} file …")
    hypotheses, info = transcribe_files(paths, args.model, cfg=cfg, vad=vad, device=args.device,
                                        compute_type=args.compute_type, catalog=catalog, reference_date=ref)
    out = Path(args.out)
    _write_json(out / "hypotheses.json", hypotheses)
    _write_json(out / "run.json", {**info, "audio": str(target), "reference_date": ref.isoformat(),
                                   # eval so hash này với ground_truth.json của dataset để bắt chấm nhầm cặp
                                   "ground_truth_sha256": text_sha256(gt_path) if gt_path else None})
    print(f"Xong trên {info['device']}/{info['compute_type']}: RTF {info['rtf']} → {out / 'hypotheses.json'}")


def cmd_renormalize(args: argparse.Namespace) -> None:
    from .asr import finalize
    from .btc import find_data_dir, load_catalog, read_json
    from .entities import REFERENCE_DATE
    from .normalize import default_lexicon, rules_fingerprint

    catalog = load_catalog(find_data_dir(args.data_dir, required=False))
    lexicon = default_lexicon()
    fingerprint = rules_fingerprint()
    for run in map(Path, args.runs):
        info = read_json(run / "run.json") if (run / "run.json").is_file() else {}
        ref = date.fromisoformat(info["reference_date"]) if info.get("reference_date") else REFERENCE_DATE
        hypotheses = read_json(run / "hypotheses.json")
        for key, record in hypotheses.items():
            hypotheses[key] = {**finalize(record.get("asr_segments", []), lexicon, catalog, ref),
                               "meta": record.get("meta", {})}
        _write_json(run / "hypotheses.json", hypotheses)
        if info:
            _write_json(run / "run.json", {**info, **fingerprint})
        print(f"Đã chuẩn hóa lại {len(hypotheses)} file trong {run} (chữ thô ASR giữ nguyên).")


def cmd_eval(args: argparse.Namespace) -> None:
    from .btc import find_data_dir, load_catalog, load_reference_eval
    from .evaluate import markdown_table, score_run

    data_dir = find_data_dir(args.data_dir)
    ref_eval = load_reference_eval(data_dir)
    catalog = load_catalog(data_dir)
    try:
        reports = [score_run(Path(args.dataset), Path(run), ref_eval, catalog) for run in args.runs]
    except ValueError as exc:
        sys.exit(f"Không chấm: {exc}")
    stale = [r["run"] for r in reports if r["rules_stale"]]
    if stale:
        print(f"Cảnh báo: {', '.join(stale)} tạo bằng bộ luật chuẩn hóa cũ; chạy `python -m speech renormalize` "
              "trước khi so sánh.")
    mismatched = [r["run"] for r in reports if r["ground_truth_match"] is False]
    if mismatched:
        print(f"Cảnh báo: {', '.join(mismatched)} được nhận dạng từ dataset có ground_truth.json khác "
              f"{Path(args.dataset) / 'ground_truth.json'} → có thể đang chấm nhầm cặp run–dataset.")
    unchecked = [r["run"] for r in reports if r["ground_truth_match"] is None]
    if unchecked:
        print(f"Ghi chú: {', '.join(unchecked)} không ghi ground_truth_sha256 (run cũ) → không kiểm được "
              "run có khớp dataset không.")
    table = markdown_table(reports)
    print(table)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(table + "\n", encoding="utf-8")


def cmd_normalize(args: argparse.Namespace) -> None:
    from .btc import find_data_dir, load_catalog
    from .entities import extract_entities
    from .normalize import normalize_text

    norm = normalize_text(args.text)
    merged, _ = extract_entities([norm.written], load_catalog(find_data_dir(args.data_dir, required=False)))
    for field in ("raw", "canonical", "written", "spoken"):
        print(f"{field:<9}: {getattr(norm, field)}")
    print(f"entities : {json.dumps(merged, ensure_ascii=False)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m speech", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", help="thư mục BTC-Data-Vong1-TEAMS (mặc định: BTC_DATA_DIR hoặc cạnh repo)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("voices", help="liệt kê/thêm giọng tiếng Việt")
    p.add_argument("--engine", choices=("edge", "elevenlabs", "vieneu"), default="edge")
    p.add_argument("--accent", help="ElevenLabs: northern | southern | central …")
    p.add_argument("--gender", help="ElevenLabs: male | female")
    p.add_argument("--add", metavar="OWNER_ID:VOICE_ID", help="ElevenLabs: thêm giọng Voice Library vào My Voices")
    p.add_argument("--name", help="tên mới khi --add")
    p.set_defaults(func=cmd_voices)

    p = sub.add_parser("synth", help="kịch bản → audio hội thoại")
    p.add_argument("--dialogues", default="btc", help="'btc' (asr/ground_truth.json của BTC) hoặc file JSON cùng format")
    p.add_argument("--engine", choices=("edge", "elevenlabs", "vieneu", "mms", "files"), default="edge",
                   help="files = clip có sẵn trong --inbox (ElevenLabs tạo thủ công, xem manual-export)")
    p.add_argument("--voices", help="file cấu hình giọng (mặc định speech/voices.json, rồi voices.example.json)")
    p.add_argument("--inbox", help="engine files: thư mục chứa <ID>/<ID>_<idx>_<A|C>.mp3")
    p.add_argument("--team-voices", help="bản mẫu giọng clone: speech/data/team_voices.json "
                                         "({\"tv1\": {gender, region, ref_audio, consent: true}})")
    p.add_argument("--preview-team", action="store_true",
                   help="bản mẫu giọng clone: điền tv1–tv3 bằng đội giả lập để nghe thử (không dùng để chấm)")
    p.add_argument("--out", required=True, help="thư mục dataset, ví dụ speech/data/datasets/btc-edge")
    p.add_argument("--cache-dir", default=str(PACKAGE_DIR / "data" / "tts_cache"))
    p.add_argument("--channel", choices=("phone", "none"), default="phone", help="giả lập kênh điện thoại 300–3400 Hz")
    p.add_argument("--snr", type=float, default=10.0, help="SNR (dB) cho hội thoại có noisy=true")
    p.add_argument("--no-noise", action="store_true", help="không trộn nhiễu kể cả hội thoại noisy=true")
    p.add_argument("--noise", help="file tiếng ồn thật để trộn (mặc định nhiễu hồng)")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--only", help="chỉ tạo các id, ví dụ D01,D03")
    p.add_argument("--no-pronounce", action="store_true",
                   help="bỏ bảng phiên âm 'pronounce' (để giọng TTS đọc nguyên chữ tiếng Anh)")
    p.add_argument("--dry-run", action="store_true",
                   help="chỉ in bảng phân giọng + ước tính ký tự/credit (engine files: chỉ kiểm inbox)")
    p.set_defaults(func=cmd_synth)

    p = sub.add_parser("manual-export", help="checklist tạo clip ElevenLabs thủ công trên web (không gọi API)")
    p.add_argument("--dialogues", required=True, help="file kịch bản đầy đủ, ví dụ speech/dialogues/team_synthetic.json")
    p.add_argument("--out", default=str(PACKAGE_DIR / "data" / "inbox" / "elevenlabs"))
    p.add_argument("--voices", help="file cấu hình giọng (mục elevenlabs) để gợi ý giọng")
    p.add_argument("--only", help="chỉ xuất các id, ví dụ T03,T04")
    p.set_defaults(func=cmd_manual_export)

    p = sub.add_parser("validate", help="kiểm kịch bản tự viết: định dạng, dạng nói, sự thật theo mock_tools BTC")
    p.add_argument("--dialogues", nargs="+", required=True, help="các file kịch bản JSON")
    p.add_argument("--out", help="ghi báo cáo ra file")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("transcribe", help="audio → hypotheses.json")
    p.add_argument("--audio", required=True, help="file hoặc thư mục audio (ví dụ <dataset>/audio)")
    p.add_argument("--model", default="whisper-turbo",
                   help="preset hoặc thư mục CTranslate2 (mặc định whisper-turbo: chính xác nhất khi thử; "
                        "phowhisper-small nhanh gấp ~2 lần trên CPU)")
    p.add_argument("--out", required=True, help="thư mục run, ví dụ speech/data/runs/btc-edge__whisper-turbo")
    p.add_argument("--language", choices=("vi", "en", "auto"), default="vi")
    p.add_argument("--segmentation", choices=("utterance", "file"), default="utterance")
    p.add_argument("--no-hotwords", action="store_true")
    p.add_argument("--beam-size", type=int, default=5)
    p.add_argument("--device", default="auto", help="auto | cpu | cuda")
    p.add_argument("--compute-type", default="auto", help="auto | int8 | int8_float16 | float16 | float32")
    p.add_argument("--vad-threshold", type=float, default=0.5)
    p.add_argument("--min-silence-ms", type=int, default=500)
    p.add_argument("--reference-date", help="YYYY-MM-DD; mặc định lấy từ ground_truth.json cạnh thư mục audio")
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser("renormalize", help="chuẩn hóa + trích entity lại từ chữ thô ASR đã lưu")
    p.add_argument("--runs", nargs="+", required=True, help="các thư mục run có hypotheses.json")
    p.set_defaults(func=cmd_renormalize)

    p = sub.add_parser("eval", help="chấm và so sánh các run")
    p.add_argument("--dataset", required=True, help="thư mục có ground_truth.json")
    p.add_argument("--runs", nargs="+", required=True)
    p.add_argument("--out", help="ghi bảng markdown ra file")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("normalize", help="xem các bước chuẩn hóa của một câu")
    p.add_argument("text")
    p.set_defaults(func=cmd_normalize)
    return parser


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
