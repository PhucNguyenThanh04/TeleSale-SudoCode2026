#!/usr/bin/env python3
"""
Sinh audio hội thoại đa lượt cho asr/ground_truth.json.

Mỗi lượt được tổng hợp bằng GIỌNG RIÊNG theo vai (agent / khách) + giới tính + vùng miền, rồi ghép lại
với khoảng nghỉ ngẫu nhiên 0.35–0.9 s giữa các lượt → audio/<id>.wav (16 kHz mono) và
audio/<id>.segments.json (mốc start/end từng lượt = ground truth diarization). Hội thoại noisy=true
được trộn nhiễu nền (ồn hồng + băng thông điện thoại 300–3400 Hz).

BẢO ĐẢM GIỌNG KHÁC NHAU: script luôn kiểm tra giọng của agent và giọng của khách trong CÙNG một hội thoại
phải khác nhau. Nếu backend không đủ giọng (edge chỉ có 2 giọng tiếng Việt), script tự động áp thêm
biến đổi pitch/tempo cho vai khách để hai người nghe vẫn tách được (xem --distinct).

Backend (--backend), chất lượng giảm dần:
  openai      OpenAI gpt-4o-mini-tts (API, 11 giọng, có tham số `instructions` để ép phong cách/vai).
              pip install requests ; export OPENAI_API_KEY=...
              Lưu ý: giọng OpenAI luyện chủ yếu trên tiếng Anh — đọc tiếng Việt khá trôi nhưng KHÔNG ra
              đúng chất giọng vùng miền; chỉ khác nhau rõ giữa agent và khách. Muốn giọng vùng miền thật → f5.
  gemini      Gemini 2.5 TTS (API, 30 giọng, tiếng Việt tự nhiên).  pip install google-genai ; GEMINI_API_KEY
  elevenlabs  ElevenLabs eleven_multilingual_v2 (tự nhiên nhất, có phí). pip install requests ; ELEVEN_API_KEY + voice id
  f5          F5-TTS-Vietnamese (local, GPU, clone giọng từ clip tham chiếu → GIỌNG VÙNG MIỀN thật).
              Cần repo F5-TTS + checkpoint (HF: hynt/F5-TTS-Vietnamese-ViVoice) và thư mục ref/ chứa
              clip 5–10 s cho từng giọng: ref/nu1.wav + ref/nu1.txt, ref/nu2.*, ref/nam1.*, ref/nam2.*
              (có thể cắt từ chính bản thu của 4 người đọc).
  edge        edge-tts (miễn phí, CHỈ CÓ 2 giọng tiếng Việt → bắt buộc dùng --distinct để tách vai).
  recorded    GIỌNG NGƯỜI THẬT thu sẵn. Hai cách, trong --recordings:
              (a) CẢ hội thoại 1 file trên điện thoại: D01.m4a — script tự tách thành từng lượt tại các khoảng nghỉ;
              (b) từng lượt 1 file: <ID>_T<nn>_<A|C>.wav/.m4a/.mp3.
              tự cắt lặng đầu/cuối và cân âm lượng. Lượt thiếu file sinh bằng --fallback (openai/gemini/…) với giọng TTS tương ứng mã giọng.
              Hướng dẫn thu: Hướng-dẫn-thu-âm-ASR.xlsx.
  dummy       sinh tone thay lời nói — kiểm tra ghép/segments mà không cần TTS.

DeepSeek: tính đến 09/2026 DeepSeek KHÔNG có API text-to-speech (chỉ model ngôn ngữ), nên không có backend.

Ví dụ:
  export OPENAI_API_KEY=sk-...
  python make_audio.py --backend openai                 # sinh mọi hội thoại trong ground_truth.json
  python make_audio.py --backend openai --only D01      # thử 1 hội thoại
  python make_audio.py --dry-run                        # chỉ in bảng phân giọng, không gọi API
  python make_audio.py --backend edge --distinct always # edge + biến đổi pitch cho vai khách
  python make_audio.py --backend openai --voices-json my_voices.json   # tự chỉ định giọng
  python make_audio.py --backend recorded --recordings recordings/ --check            # liệt kê file còn thiếu
  python make_audio.py --backend recorded --recordings recordings/                    # ghép bản thu (đủ file)
  python make_audio.py --backend recorded --recordings recordings/ --fallback openai  # thiếu file thì AI đọc bù
Bộ public D01–D04: BTC KHÔNG phát audio. Đội tự chạy script này (TTS hoặc --backend recorded) để tạo audio/ + segments.json.
Kết quả trên audio tự tạo không dùng để xếp hạng; WER/CER chính thức đo trên bộ private BTC thu và giữ riêng.
"""
import argparse, json, math, os, random, shlex, struct, subprocess, sys, tempfile, wave

SR = 16000
random.seed(2026)

# ============================================================================ voice profiles
VOICE_GENDER = {"nu1": "f", "nu2": "f", "nam1": "m", "nam2": "m"}

def profile(d, speaker):
    """Mã giọng cố định ('nu1','nu2','nam1','nam2') nếu ground truth có; nếu không thì 'agent_f_bac' / 'cust_m_nam'."""
    v = d.get("agent_voice" if speaker == "A" else "customer_voice")
    if v:
        return v
    if speaker == "A":
        return f"agent_{d.get('agent_gender', 'f')}_{d.get('agent_region', 'bac')}"
    return f"cust_{d.get('customer_gender', 'f')}_{d.get('customer_region', 'bac')}"

def gender_of(prof):
    return VOICE_GENDER.get(prof) or prof.split("_")[1]

REGION_VI = {"bac": "miền Bắc (Hà Nội)", "nam": "miền Nam (Sài Gòn)", "trung": "miền Trung nhẹ"}

# --- OpenAI: 11 giọng. Agent và khách LUÔN nằm ở hai nhóm giọng tách biệt ----------------------
# Giọng nữ/trung tính: alloy, coral, nova, sage, shimmer, ballad | nam: ash, echo, onyx, verse, fable
OPENAI_VOICES = {
    # 4 giọng cố định của bộ ASR (Nữ 1, Nữ 2, Nam 1, Nam 2) — mỗi người một giọng, dùng xuyên suốt
    "nu1": "coral",  "nu2": "shimmer",  "nam1": "ash",  "nam2": "onyx",
    # vai agent (tổng đài viên) — chỉ dùng 2 giọng này, không trùng với khách
    "agent_f_bac": "coral",   "agent_f_nam": "sage",   "agent_f_trung": "coral",
    "agent_m_bac": "verse",   "agent_m_nam": "verse",  "agent_m_trung": "verse",
    # vai khách — khác hẳn nhóm agent
    "cust_f_bac": "nova",     "cust_f_nam": "shimmer", "cust_f_trung": "alloy",
    "cust_m_bac": "onyx",     "cust_m_nam": "ash",     "cust_m_trung": "echo",
}
OPENAI_STYLE = {   # `instructions` — gpt-4o-mini-tts nghe theo chỉ dẫn này
    "A": ("Bạn là nhân viên tổng đài bán hàng người Việt, giọng {region}. "
          "Nói tiếng Việt chuẩn, lịch sự, tươi và chuyên nghiệp, tốc độ vừa phải, "
          "ngữ điệu phục vụ khách hàng qua điện thoại. Đọc số tiền và số điện thoại rõ ràng, tách nhịp."),
    "C": ("Bạn là khách hàng người Việt đang gọi điện cho shop, giọng {region}. "
          "Nói tự nhiên, thoải mái như đời thường, hơi nhanh và tùy hứng, KHÔNG có chất giọng nhân viên "
          "tổng đài, không quá lịch sự. Có thể hơi ngập ngừng hoặc sốt ruột."),
}

# --- Gemini ------------------------------------------------------------------------------------
GEMINI_VOICES = {
    "nu1": "Kore",  "nu2": "Leda",  "nam1": "Puck",  "nam2": "Charon",
    "agent_f_bac": "Kore",    "agent_f_nam": "Leda",    "agent_f_trung": "Kore",
    "agent_m_bac": "Orus",    "agent_m_nam": "Orus",    "agent_m_trung": "Orus",
    "cust_f_bac": "Aoede",    "cust_f_nam": "Zephyr",   "cust_f_trung": "Callirrhoe",
    "cust_m_bac": "Charon",   "cust_m_nam": "Puck",     "cust_m_trung": "Fenrir",
}
GEMINI_STYLE = {"bac": "giọng miền Bắc", "nam": "giọng miền Nam", "trung": "giọng miền Trung nhẹ"}

# --- edge-tts: CHỈ có 2 giọng tiếng Việt → cùng giới tính là trùng giọng ------------------------
EDGE_VOICES = {"f": "vi-VN-HoaiMyNeural", "m": "vi-VN-NamMinhNeural"}

# --- biến đổi pitch/tempo để tách vai khi backend hết giọng -------------------------------------
# (pitch_factor, tempo_factor) — chỉ áp cho vai khách; agent giữ nguyên.
ROLE_TUNE = {"A": (1.0, 1.0), "C": (0.93, 1.04)}

def voice_of(backend, prof, overrides):
    if prof in overrides:
        return overrides[prof]
    if backend == "openai":
        return OPENAI_VOICES.get(prof, "alloy")
    if backend == "gemini":
        return GEMINI_VOICES.get(prof, "Kore")
    if backend == "elevenlabs":
        return (os.environ.get(f"ELEVEN_VOICE_{prof.upper()}")
                or os.environ.get("ELEVEN_VOICE_" + gender_of(prof).upper()) or "")
    if backend == "edge":
        return EDGE_VOICES[gender_of(prof)]
    if backend == "f5":
        return f"ref/{prof}.wav"
    return f"tone_{gender_of(prof)}"

# ============================================================================ backends → PCM16 16k mono
def to_pcm16k(src_path):
    return subprocess.run(["ffmpeg", "-v", "error", "-i", src_path, "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                          check=True, capture_output=True).stdout

def raw_to_pcm16k(raw_bytes, in_rate):
    with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as f:
        f.write(raw_bytes); p = f.name
    out = subprocess.run(["ffmpeg", "-v", "error", "-f", "s16le", "-ar", str(in_rate), "-ac", "1", "-i", p,
                          "-f", "s16le", "-ar", str(SR), "-ac", "1", "-"], check=True, capture_output=True).stdout
    os.remove(p); return out

def tts_openai(text, prof, region, speaker, voice):
    """POST /v1/audio/speech, response_format=pcm → PCM16 24 kHz mono."""
    import requests
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("Thiếu OPENAI_API_KEY")
    body = {"model": os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
            "voice": voice, "input": text, "response_format": "pcm",
            "instructions": OPENAI_STYLE[speaker].format(region=REGION_VI.get(region, ""))}
    for attempt in range(4):
        r = requests.post(os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1") + "/audio/speech",
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json=body, timeout=180)
        if r.status_code == 200:
            return raw_to_pcm16k(r.content, 24000)
        if r.status_code in (429, 500, 502, 503) and attempt < 3:
            import time; time.sleep(2 * (attempt + 1)); continue
        sys.exit(f"OpenAI TTS lỗi {r.status_code}: {r.text[:400]}")

def tts_gemini(text, prof, region, speaker, voice):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    role = "một nhân viên tổng đài bán hàng" if speaker == "A" else "một khách hàng đang gọi điện cho shop"
    prompt = (f"Đọc câu sau bằng tiếng Việt như {role}, {GEMINI_STYLE.get(region, '')}, tự nhiên, tốc độ vừa: {text}")
    r = client.models.generate_content(
        model=os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts"), contents=prompt,
        config=types.GenerateContentConfig(response_modalities=["AUDIO"], speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)))))
    return raw_to_pcm16k(r.candidates[0].content.parts[0].inline_data.data, 24000)

def tts_elevenlabs(text, prof, region, speaker, voice):
    import requests
    if not voice:
        sys.exit(f"Thiếu voice id cho profile {prof}: đặt ELEVEN_VOICE_{prof.upper()} (hoặc ELEVEN_VOICE_F / _M)")
    r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=pcm_16000",
                      headers={"xi-api-key": os.environ["ELEVEN_API_KEY"], "Content-Type": "application/json"},
                      json={"text": text, "model_id": os.environ.get("ELEVEN_MODEL", "eleven_multilingual_v2"),
                            "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.2}}, timeout=180)
    r.raise_for_status(); return r.content

def tts_f5(text, prof, region, speaker, voice, cmd_tpl):
    ref_audio, ref_txt = f"ref/{prof}.wav", f"ref/{prof}.txt"
    if not (os.path.exists(ref_audio) and os.path.exists(ref_txt)):
        sys.exit(f"Thiếu clip tham chiếu {ref_audio} / {ref_txt} (5–10 s giọng thật vùng miền tương ứng + transcript)")
    out_dir = tempfile.mkdtemp(); out_name = "gen.wav"
    cmd = cmd_tpl.format(ref_audio=shlex.quote(ref_audio), ref_text=shlex.quote(open(ref_txt, encoding="utf-8").read().strip()),
                         text=shlex.quote(text), out_dir=shlex.quote(out_dir), out_name=out_name)
    subprocess.run(cmd, shell=True, check=True, capture_output=True)
    return to_pcm16k(os.path.join(out_dir, out_name))

def tts_edge(text, prof, region, speaker, voice):
    import asyncio, edge_tts
    rate = {"bac": "+0%", "nam": "+3%", "trung": "-5%"}[region]
    mp3 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name
    asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(mp3))
    pcm = to_pcm16k(mp3); os.remove(mp3); return pcm

REC_EXT = (".wav", ".m4a", ".mp3", ".aac", ".ogg", ".flac", ".webm")

def rec_path(rec_dir, did, idx, speaker):
    base = os.path.join(rec_dir, f"{did}_T{idx:02d}_{speaker}")
    for ext in REC_EXT:
        for cand in (base + ext, base + ext.upper()):
            if os.path.exists(cand):
                return cand
    return None

def dialogue_rec_path(rec_dir, did):
    """File thu CẢ hội thoại trên điện thoại: recordings/D01.m4a (hoặc .wav/.mp3…)."""
    base = os.path.join(rec_dir, did)
    for ext in REC_EXT:
        for cand in (base + ext, base + ext.upper()):
            if os.path.exists(cand):
                return cand
    return None

def split_dialogue(path, turns, normalize=True, noise_db=-35, min_gap=0.25):
    """Tách file cả hội thoại thành đúng len(turns) đoạn, cắt tại (n-1) khoảng lặng DÀI NHẤT giữa bài.
    Trả (pieces_pcm, warnings). Lỗi nếu không đủ khoảng lặng → người đọc phải nghỉ rõ hơn giữa các lượt."""
    import re as _re
    n = len(turns)
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         check=True, capture_output=True).stdout
    total = len(pcm) / 2 / SR
    err = subprocess.run(["ffmpeg", "-i", path, "-af", f"silencedetect=noise={noise_db}dB:d={min_gap}", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    starts = [float(x) for x in _re.findall(r"silence_start: ([\d.]+)", err)]
    ends = [float(x) for x in _re.findall(r"silence_end: ([\d.]+)", err)]
    sil = [(st, ends[i] if i < len(ends) else total) for i, st in enumerate(starts)]
    head = next((e for st, e in sil if st <= 0.05), 0.0)                 # lặng đầu file
    tail = next((st for st, e in sil if e >= total - 0.05), total)        # lặng cuối file
    inner = [(st, e) for st, e in sil if st > head and e < tail]
    if len(inner) < n - 1:
        raise ValueError(f"{os.path.basename(path)}: chỉ tìm thấy {len(inner)} khoảng nghỉ giữa các lượt, cần {n - 1}. "
                         f"Thu lại và nghỉ khoảng 1 giây giữa mỗi lượt, không nói chồng lên nhau.")
    cuts = sorted(sorted(inner, key=lambda x: x[1] - x[0], reverse=True)[:n - 1])
    bounds = [head] + [x for c in cuts for x in c] + [tail]
    pieces, warns = [], []
    for k in range(n):
        a, b = bounds[2 * k], bounds[2 * k + 1]
        seg = pcm[int(a * SR) * 2:int(b * SR) * 2]
        if normalize:
            seg = loudnorm_pcm(seg)
        exp = max(0.8, len(turns[k]["text"].split()) / 3.5)          # thời lượng kỳ vọng theo số âm tiết
        if not (exp / 2.5 <= (b - a) <= exp * 2.5):
            warns.append(f"lượt {turns[k]['idx']} dài {b - a:.1f}s (kỳ vọng ~{exp:.1f}s) — có thể tách sai, nghe lại")
        pieces.append(seg)
    return pieces, warns

def load_recorded(path, normalize=True):
    """Đọc file thu âm → PCM16 16 kHz mono, cắt lặng đầu/cuối (< -45 dB), cân âm lượng về -20 LUFS."""
    trim = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse,"
            "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse")
    af = trim + (",loudnorm=I=-20:TP=-2:LRA=11" if normalize else "")
    return subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-af", af, "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                          check=True, capture_output=True).stdout

def loudnorm_pcm(pcm):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        p = f.name
    write_wav(p, pcm)
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-af", "loudnorm=I=-20:TP=-2:LRA=11", "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         check=True, capture_output=True).stdout
    os.remove(p); return out

def tts_dummy(text, prof, region, speaker, voice):
    dur = max(0.8, len(text.split()) / 2.6); f0 = 180 if gender_of(prof) == "f" else 120
    return b"".join(struct.pack("<h", int(6000 * math.sin(2 * math.pi * f0 * i / SR) *
                                          (0.6 + 0.4 * math.sin(2 * math.pi * 3 * i / SR)))) for i in range(int(dur * SR)))

# ============================================================================ xử lý audio
def retune(pcm, pitch, tempo):
    """Dịch cao độ + tốc độ (giữ nguyên nội dung) để tách vai khi backend thiếu giọng."""
    if abs(pitch - 1.0) < 1e-3 and abs(tempo - 1.0) < 1e-3:
        return pcm
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        p = f.name
    write_wav(p, pcm)
    # asetrate đổi cả pitch lẫn tốc độ → atempo bù lại tốc độ, chỉ còn đổi pitch
    af = f"asetrate={int(SR * pitch)},aresample={SR},atempo={1 / pitch:.4f},atempo={tempo:.4f}"
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-af", af, "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         check=True, capture_output=True).stdout
    os.remove(p); return out

def silence(sec): return b"\x00\x00" * int(sec * SR)

def write_wav(path, pcm):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm)

def add_noise_and_phone_band(path):
    tmp = path + ".tmp.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-f", "lavfi",
                    "-i", f"anoisesrc=color=pink:amplitude=0.035:sample_rate={SR}",
                    "-filter_complex", "[0:a]highpass=f=300,lowpass=f=3400[a];[a][1:a]amix=inputs=2:duration=first:normalize=0",
                    "-ar", str(SR), "-ac", "1", tmp], check=True, capture_output=True)
    os.replace(tmp, path)

def synth(text, prof, region, speaker, voice, args):
    b = args.backend
    if b == "openai":     return tts_openai(text, prof, region, speaker, voice)
    if b == "gemini":     return tts_gemini(text, prof, region, speaker, voice)
    if b == "elevenlabs": return tts_elevenlabs(text, prof, region, speaker, voice)
    if b == "f5":         return tts_f5(text, prof, region, speaker, voice, args.f5_cmd)
    if b == "edge":       return tts_edge(text, prof, region, speaker, voice)
    return tts_dummy(text, prof, region, speaker, voice)

# ============================================================================ main
def plan(d, backend, overrides):
    """Trả (voice_agent, voice_cust, collide) cho 1 hội thoại."""
    pa, pc = profile(d, "A"), profile(d, "C")
    if backend == "recorded":   # giọng người thật khác nhau theo người đọc; không biến đổi pitch
        return pa, pc, "recorded", "recorded", False
    va, vc = voice_of(backend, pa, overrides), voice_of(backend, pc, overrides)
    return pa, pc, va, vc, va == vc

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="openai", choices=["openai", "gemini", "elevenlabs", "f5", "edge", "recorded", "dummy"])
    ap.add_argument("--recordings", default="recordings", help="thư mục file thu âm (backend recorded)")
    ap.add_argument("--fallback", choices=["openai", "gemini", "elevenlabs", "f5", "edge", "dummy"],
                    help="backend sinh giọng cho lượt không có file thu (backend recorded)")
    ap.add_argument("--check", action="store_true", help="(recorded) chỉ kiểm tra file thu, không ghép")
    ap.add_argument("--no-normalize", action="store_true", help="(recorded) không cân âm lượng")
    ap.add_argument("--distinct", default="auto", choices=["auto", "always", "off"],
                    help="auto: chỉ biến đổi pitch vai khách khi giọng trùng; always: luôn biến đổi; off: tắt")
    ap.add_argument("--voices-json", help='JSON {"agent_f_bac": "coral", "cust_f_bac": "nova", ...} để đè bảng giọng')
    ap.add_argument("--f5-cmd", default="f5-tts_infer-cli --model F5TTS_v1_Base --ckpt_file ckpt/model.pt --vocab_file ckpt/vocab.txt "
                                        "--ref_audio {ref_audio} --ref_text {ref_text} --gen_text {text} -o {out_dir} -w {out_name}")
    _here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--gt", default=os.path.join(_here, "ground_truth.json")); ap.add_argument("--out", default=os.path.join(_here, "audio"))
    ap.add_argument("--only", help="chỉ sinh 1 hội thoại, vd D01")
    ap.add_argument("--no-noise", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="chỉ in bảng phân giọng, không gọi TTS")
    args = ap.parse_args()

    overrides = json.load(open(args.voices_json, encoding="utf-8")) if args.voices_json else {}
    gt = json.load(open(args.gt, encoding="utf-8"))
    dialogues = [d for d in gt["dialogues"] if not args.only or d["id"] == args.only]

    split_cache = {}
    if args.backend == "recorded":
        have, missing = 0, []
        for d in dialogues:
            per_turn = [t for t in d["turns"] if rec_path(args.recordings, d["id"], t["idx"], t["speaker"])]
            whole = dialogue_rec_path(args.recordings, d["id"])
            if whole and not per_turn:                      # thu cả hội thoại 1 file → tự tách
                try:
                    pieces, warns = split_dialogue(whole, d["turns"], normalize=not args.no_normalize)
                    split_cache[d["id"]] = pieces; have += len(pieces)
                    print(f"  {d['id']}: file cả hội thoại {os.path.basename(whole)} → tách được {len(pieces)} lượt")
                    for w in warns:
                        print(f"     ! {w}")
                except ValueError as e:
                    print(f"  {d['id']}: LỖI TÁCH — {e}")
                    missing += [f"{d['id']}_T{t['idx']:02d}_{t['speaker']}" for t in d["turns"]]
                continue
            for t in d["turns"]:
                if rec_path(args.recordings, d["id"], t["idx"], t["speaker"]):
                    have += 1
                else:
                    missing.append(f"{d['id']}_T{t['idx']:02d}_{t['speaker']}")
        print(f"Bản thu: {have} lượt có | {len(missing)} lượt THIẾU")
        if missing:
            print("  Thiếu:", ", ".join(missing))
        if args.check:
            return
        if missing and not args.fallback:
            sys.exit("Còn lượt không có file thu → thêm --fallback openai (hoặc backend khác) để sinh giọng cho các lượt này.")

    # --- bảng phân giọng + cảnh báo trùng --------------------------------------------------
    print(f"{'ID':<5}{'vai agent':<16}{'giọng':<14}{'vai khách':<16}{'giọng':<14}{'tách vai'}")
    collisions = 0
    for d in dialogues:
        pa, pc, va, vc, col = plan(d, args.backend, overrides)
        tune = args.distinct == "always" or (args.distinct == "auto" and col)
        collisions += col
        print(f"{d['id']:<5}{pa:<16}{str(va)[:13]:<14}{pc:<16}{str(vc)[:13]:<14}"
              f"{'pitch/tempo' if tune else ('giọng khác' if not col else 'TRÙNG!')}")
    if collisions and args.distinct == "off":
        print(f"\n!! {collisions} hội thoại có agent và khách TRÙNG giọng và --distinct=off → "
              f"đổi sang --backend openai hoặc --distinct always.")
    if args.dry_run:
        return

    os.makedirs(args.out, exist_ok=True)
    manifest = []
    for d in dialogues:
        pa, pc, va, vc, col = plan(d, args.backend, overrides)
        tune = args.distinct == "always" or (args.distinct == "auto" and col)
        pcm, t, segs = silence(0.5), 0.5, []
        for turn in d["turns"]:
            sp = turn["speaker"]
            prof = pa if sp == "A" else pc
            voice = va if sp == "A" else vc
            region = d["agent_region"] if sp == "A" else d["customer_region"]
            source = args.backend
            if args.backend == "recorded" and d["id"] in split_cache:
                audio = split_cache[d["id"]][turn["idx"] - 1]; voice = f"{d['id']}#T{turn['idx']:02d}"; source = "recorded:whole"
            elif args.backend == "recorded":
                rp = rec_path(args.recordings, d["id"], turn["idx"], sp)
                if rp:
                    audio = load_recorded(rp, normalize=not args.no_normalize); voice = os.path.basename(rp)
                else:
                    fb = argparse.Namespace(**{**vars(args), "backend": args.fallback})
                    voice = voice_of(args.fallback, prof, overrides)
                    audio = synth(turn["text"], prof, region, sp, voice, fb)
                    if not args.no_normalize:
                        audio = loudnorm_pcm(audio)
                    source = f"tts:{args.fallback}"
            else:
                audio = synth(turn["text"], prof, region, sp, voice, args)
            if tune:
                audio = retune(audio, *ROLE_TUNE[sp])
            dur = len(audio) / 2 / SR
            segs.append({"idx": turn["idx"], "speaker": sp, "voice": voice, "source": source,
                         "start": round(t, 3), "end": round(t + dur, 3), "text": turn["text"]})
            gap = random.uniform(0.35, 0.9)
            pcm += audio + silence(gap); t += dur + gap
        path = os.path.join(args.out, f"{d['id']}.wav"); write_wav(path, pcm)
        if d.get("noisy") and not args.no_noise:
            add_noise_and_phone_band(path)
        json.dump({"id": d["id"], "duration_s": round(t, 2), "noisy": bool(d.get("noisy")), "backend": args.backend,
                   "voice_agent": va, "voice_customer": vc, "role_tuned": tune, "segments": segs},
                  open(os.path.join(args.out, f"{d['id']}.segments.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        manifest.append({"id": d["id"], "file": f"{d['id']}.wav", "duration_s": round(t, 2),
                         "n_turns": len(segs), "noisy": bool(d.get("noisy")), "voice_agent": va, "voice_customer": vc})
        print(f"→ {d['id']}  {t:6.1f}s  {len(segs)} lượt  A={va} C={vc}  {'[noisy]' if d.get('noisy') else ''}")
    json.dump({"backend": args.backend, "sample_rate": SR, "role_distinct_mode": args.distinct, "files": manifest},
              open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("tổng:", round(sum(m["duration_s"] for m in manifest) / 60, 1), "phút")

if __name__ == "__main__":
    main()
