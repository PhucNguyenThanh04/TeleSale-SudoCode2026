from __future__ import annotations

import copy
import json
import re
from pathlib import Path

KH = "{kh}"
HONORIFIC = {"f": "chị", "m": "anh"}
REGIONS = ("bac", "trung", "nam")
GENDERS = ("f", "m")
TEAM_VOICE_RE = re.compile(r"^tv[1-3]$")
VOICE_FIELDS = {"A": ("agent_voice", "agent_region", "agent_gender"),
                "C": ("customer_voice", "customer_region", "customer_gender")}
VALIDATOR_ONLY_FIELDS = ("checks", "tool_context")
PREVIEW_TEAM = {"tv1": {"gender": "f", "region": "bac"}, "tv2": {"gender": "m", "region": "nam"},
                "tv3": {"gender": "m", "region": "bac"}}


def read_json(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def is_template(dialogue: dict) -> bool:
    return any(dialogue.get(fields[0]) for fields in VOICE_FIELDS.values())


def load_team_voices(path: str | Path) -> dict[str, dict]:
    path = Path(path)
    raw = read_json(path)
    team, errors = {}, []
    for key, member in raw.items():
        if key.startswith("_"):
            continue
        where = f"{path.name}:{key}"
        if not TEAM_VOICE_RE.match(key):
            errors.append(f"{where}: khóa phải là tv1, tv2 hoặc tv3")
            continue
        if member.get("consent") is not True:
            errors.append(f"{where}: thiếu \"consent\": true — chỉ clone giọng thành viên đã đồng ý")
        if member.get("gender") not in GENDERS:
            errors.append(f"{where}: gender phải là f hoặc m")
        if member.get("region") not in REGIONS:
            errors.append(f"{where}: region phải là bac, trung hoặc nam")
        ref = Path(str(member.get("ref_audio", "")))
        if not ref.is_absolute():
            ref = path.resolve().parent / ref
        if not member.get("ref_audio") or not ref.is_file():
            errors.append(f"{where}: không thấy file mẫu giọng {member.get('ref_audio')!r}")
        team[key] = {**member, "ref_audio": str(ref)}
    if errors:
        raise ValueError("team_voices.json chưa hợp lệ:\n  " + "\n  ".join(errors))
    if not team:
        raise ValueError(f"{path}: chưa khai báo giọng nào (tv1…tv3)")
    return team


def fill_team(source: dict, team: dict[str, dict]) -> dict:
    out = copy.deepcopy(source)
    for dialogue in out["dialogues"]:
        if not is_template(dialogue):
            continue
        for voice_field, region_field, gender_field in VOICE_FIELDS.values():
            key = dialogue.get(voice_field)
            if key not in team:
                raise ValueError(f"{dialogue['id']}: chưa có giọng {key!r} trong team_voices.json")
            dialogue[region_field], dialogue[gender_field] = team[key]["region"], team[key]["gender"]
        honorific = HONORIFIC[dialogue["customer_gender"]]
        for turn in dialogue["turns"]:
            for field in ("text", "tts_text"):
                if field in turn:
                    turn[field] = turn[field].replace(KH, honorific)
    return out


def team_voice_entries(team: dict[str, dict]) -> dict[str, dict]:
    return {key: {**member.get("tts", {}), "ref_audio": member["ref_audio"]} for key, member in team.items()}
