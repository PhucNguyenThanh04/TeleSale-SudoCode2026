"""ElevenLabs thủ công: xuất checklist để tạo clip trên web (gói Free, không gọi API) rồi nhập clip lại.

``python -m speech manual-export --dialogues <file> --out speech/data/inbox/elevenlabs``
    → ``checklist.md`` + ``checklist.csv``: mỗi lượt một dòng gồm tên file cần lưu, giọng gợi ý, câu cần dán,
    số ký tự và credit ước tính; tạo sẵn thư mục ``<ID>/`` để thả file tải về.

``python -m speech synth --engine files --inbox speech/data/inbox/elevenlabs --dialogues <file> --out ...``
    → ghép clip ``<ID>/<ID>_<idx>_<A|C>.mp3`` với lượt thoại (``scan_inbox``). Nếu cả thư mục ``<ID>/`` chưa đổi
    tên file thì gán theo thứ tự tên file (tên mặc định của ElevenLabs có mốc thời gian nên đúng thứ tự tạo).
    Báo file thiếu/thừa và clip có tốc độ đọc bất thường so với độ dài câu (``check_rates``).
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .team import is_template
from .tts import DEFAULT_ELEVEN_MODEL, credits_per_char, plan
from .validate import syllables

AUDIO_SUFFIXES = (".mp3", ".wav", ".m4a", ".flac", ".ogg")
CLIP_RE = re.compile(r"^(?P<id>[A-Za-z0-9][A-Za-z0-9-]*)_(?P<idx>\d+)_(?P<role>[AC])$", re.IGNORECASE)
# Tốc độ đọc hợp lý của một câu TTS (âm tiết/giây); ngoài khoảng này thường là dán nhầm câu hoặc clip bị cắt.
RATE_RANGE = (2.0, 8.0)
MIN_SYLLABLES_FOR_RATE = 3  # câu quá ngắn ("dạ", "vâng ạ") có tốc độ dao động mạnh nên bỏ qua
# Trang giá ElevenLabs: Flash/Turbo v2.5 giảm còn 0,5–1 credit/ký tự "for API usage"; Help Center: credit phụ thuộc
# tạo qua website hay API → khi tạo thủ công trên web, tính cả mức xấu nhất 1 credit/ký tự.
WEB_MAX_CREDIT = 1.0


def clip_name(dialogue_id: str, idx: int, speaker: str, suffix: str = ".mp3") -> str:
    return f"{dialogue_id}_{int(idx):02d}_{speaker}{suffix}"


def _natural_key(path: Path) -> list:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]


def _md_cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def export_checklist(source: dict, out_dir: Path, config: dict, only: set[str] | None = None) -> dict:
    dialogues = [d for d in source["dialogues"] if not only or d["id"] in only]
    templates = [d["id"] for d in dialogues if is_template(d)]
    if templates:
        raise ValueError(f"{', '.join(templates)} là bản mẫu giọng clone (tv1–tv3, {{kh}}); dùng engine vieneu "
                         "với --team-voices thay vì ElevenLabs thủ công")
    model_id = config.get("elevenlabs", {}).get("model_id", DEFAULT_ELEVEN_MODEL)
    rate = credits_per_char(model_id)
    rows = []
    for row in plan(dialogues, "elevenlabs", config):
        params = row["params"]
        rows.append({"dialogue": row["dialogue"], "idx": row["idx"], "speaker": row["speaker"],
                     "file": f"{row['dialogue']}/{clip_name(row['dialogue'], row['idx'], row['speaker'])}",
                     "voice_key": row["voice_key"], "voice": params.get("name") or params.get("voice_id", ""),
                     "voice_id": params.get("voice_id", ""), "chars": len(row["text"]),
                     "credits": round(len(row["text"]) * rate, 1), "text": row["text"]})
    out_dir = Path(out_dir)
    for dialogue in dialogues:
        (out_dir / dialogue["id"]).mkdir(parents=True, exist_ok=True)
    with open(out_dir / "checklist.csv", "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["dialogue"])
        writer.writeheader()
        writer.writerows(rows)
    total_chars = sum(r["chars"] for r in rows)
    total_credits = total_chars * rate
    voices = {}
    for r in rows:
        voices.setdefault((r["voice_key"], r["voice"], r["voice_id"]), set()).add(r["dialogue"])
    lines = [
        "# Checklist ElevenLabs (tạo thủ công trên web)", "",
        f"- Model: `{model_id}`, ngôn ngữ: Vietnamese. {len(dialogues)} hội thoại, {len(rows)} câu, "
        f"{total_chars} ký tự ≈ {total_credits:.0f} credit theo giá API; **tối đa {total_chars * WEB_MAX_CREDIT:.0f} "
        "credit** nếu website không giảm giá cho Flash (trang giá ghi mức 0,5 credit/ký tự áp dụng cho API). "
        "Tạo một hội thoại ngắn trước, xem trang Usage để biết hệ số thật rồi mới chia lô theo cột *lũy kế*.",
        "- Dán **đúng** cột *câu cần dán* (đã viết số bằng chữ, tên hãng viết gốc), tải mp3, đổi tên theo cột *file* "
        "rồi thả vào thư mục cùng tên. Chưa kịp đổi tên thì để nguyên tên ElevenLabs trong `<ID>/`, chỉ cần tạo "
        "đủ và đúng thứ tự lượt.",
        "- Giữ cùng một giọng cho cùng *khóa giọng* ở mọi hội thoại; nhân viên và khách trong một hội thoại phải "
        "khác giọng.",
        "- Nhập lại: `python -m speech synth --engine files --inbox <thư mục này> --dialogues <file kịch bản> "
        "--out speech/data/datasets/<tên>` (thêm `--dry-run` để chỉ kiểm file thiếu/tốc độ đọc).", "",
        "## Giọng", "", "| khóa giọng | giọng gợi ý | voice_id | dùng ở |", "|---|---|---|---|"]
    for (key, name, voice_id), used in sorted(voices.items()):
        lines.append(f"| {key} | {_md_cell(name)} | {voice_id} | {', '.join(sorted(used))} |")
    lines += ["", "## Ký tự theo hội thoại", "",
              f"| id | câu | ký tự | lũy kế | credit ×{rate:g} | credit ×{WEB_MAX_CREDIT:g} |", "|---|---|---|---|---|---|"]
    cumulative = 0
    for dialogue in dialogues:
        items = [r for r in rows if r["dialogue"] == dialogue["id"]]
        chars = sum(r["chars"] for r in items)
        cumulative += chars
        lines.append(f"| {dialogue['id']} | {len(items)} | {chars} | {cumulative} | {chars * rate:.0f} | "
                     f"{chars * WEB_MAX_CREDIT:.0f} |")
    for dialogue in dialogues:
        did = dialogue["id"]
        items = [r for r in rows if r["dialogue"] == did]
        lines += ["", f"## {did} — {sum(r['chars'] for r in items)} ký tự", "",
                  "| ☐ | file | vai | khóa giọng | ký tự | câu cần dán |", "|---|---|---|---|---|---|"]
        for r in items:
            lines.append(f"| ☐ | `{r['file']}` | {r['speaker']} | {r['voice_key']} | {r['chars']} | "
                         f"{_md_cell(r['text'])} |")
    (out_dir / "checklist.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"dialogues": len(dialogues), "rows": len(rows), "chars": total_chars, "credits": total_credits,
            "credits_web_max": total_chars * WEB_MAX_CREDIT, "model_id": model_id}


@dataclass
class InboxScan:
    clips: dict[tuple[str, int], Path] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing and not self.errors

    def lines(self) -> list[str]:
        return ([f"lỗi: {m}" for m in self.errors] + [f"thiếu: {m}" for m in self.missing]
                + [f"thừa (bỏ qua): {m}" for m in self.extra] + [f"ghi chú: {m}" for m in self.notes])


def _audio_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES),
                  key=_natural_key)


def scan_inbox(dialogues: list[dict], inbox: Path) -> InboxScan:
    """Ghép clip trong ``inbox/<ID>/`` (và file đã đặt tên chuẩn ở ``inbox/``) với từng lượt thoại."""
    inbox = Path(inbox)
    scan = InboxScan()
    root_files = _audio_files(inbox)
    for dialogue in dialogues:
        did = dialogue["id"]
        turns = {int(t["idx"]): t["speaker"] for t in dialogue["turns"]}
        folder = inbox / did
        named: dict[int, Path] = {}
        unnamed: list[Path] = []
        for path in _audio_files(folder) + root_files:
            match = CLIP_RE.match(path.stem)
            if not match or match["id"].upper() != did.upper():
                if path.parent == folder:
                    unnamed.append(path)
                continue
            idx, role = int(match["idx"]), match["role"].upper()
            if idx not in turns:
                scan.extra.append(f"{path.name}: {did} không có lượt {idx}")
            elif turns[idx] != role:
                scan.errors.append(f"{path.name}: lượt {idx} của {did} là vai {turns[idx]}, tên file ghi {role}")
            elif idx in named:
                scan.errors.append(f"{did} lượt {idx}: có hai file {named[idx].name} và {path.name}")
            else:
                named[idx] = path
        if not named and unnamed and len(unnamed) == len(turns):
            named = dict(zip(sorted(turns), unnamed))
            scan.notes.append(f"{did}: {len(unnamed)} file chưa đổi tên → gán theo thứ tự tên file "
                              f"({unnamed[0].name} … {unnamed[-1].name}); nghe lại để chắc đúng thứ tự")
        else:
            scan.extra += [f"{p.name}: tên không theo mẫu {did}_<idx>_<A|C>" for p in unnamed]
            if not named and unnamed:
                scan.notes.append(f"{did}: có {len(unnamed)} file chưa đổi tên nhưng cần {len(turns)} → không tự gán")
        scan.missing += [f"{did}/{clip_name(did, idx, turns[idx])}" for idx in sorted(turns) if idx not in named]
        scan.clips.update({(did, idx): path for idx, path in named.items()})
    return scan


def check_rates(dialogues: list[dict], clips: dict[tuple[str, int], Path],
                duration: Callable[[Path], float]) -> list[str]:
    """Cảnh báo clip có tốc độ (âm tiết/giây của câu trong kịch bản) ngoài ``RATE_RANGE``."""
    warnings = []
    for dialogue in dialogues:
        for turn in dialogue["turns"]:
            path = clips.get((dialogue["id"], int(turn["idx"])))
            n = syllables(turn.get("tts_text") or turn["text"])
            if path is None or n < MIN_SYLLABLES_FOR_RATE:
                continue
            seconds = duration(path)
            rate = n / seconds if seconds > 0 else float("inf")
            if not RATE_RANGE[0] <= rate <= RATE_RANGE[1]:
                warnings.append(f"{path.name}: {rate:.1f} âm tiết/s ({n} âm tiết, {seconds:.1f} s; hợp lý "
                                f"{RATE_RANGE[0]:g}–{RATE_RANGE[1]:g}) — kiểm tra clip có đúng câu lượt "
                                f"{turn['idx']} không")
    return warnings


def clip_seconds(path: Path) -> float:
    """Thời lượng phần có tiếng (đã cắt lặng đầu/cuối như khi ghép hội thoại)."""
    from . import audio as au

    return au.trim(au.decode(path)).size / au.SAMPLE_RATE


def files_config(scan: InboxScan) -> dict:
    """Cấu hình cho engine ``files`` của ``tts``: khóa ``<ID>#<idx>`` → đường dẫn clip."""
    return {"files": {"clips": {f"{did}#{idx}": str(path) for (did, idx), path in scan.clips.items()}}}
