"""
Build Haruka protagonist voice replacement + remaining-Sebastian-voice mute overlay
using direct stock loose `.wav` paths (works across ALL archives, chapters, and DLCs
with zero `.decl` conflicts).

Layout written to `<OUT_OVERLAY>/base/sound/...`:
  - 138 replaced Haruka in-game action / hit / QTE struggle / death / cough / breath WAVs
        (44100 Hz 16-bit mono PCM) in `base/sound/voice_talk/english/ingame_voice/sebastian/`
  - 2 replaced Haruka gamecutscene WAVs in `base/sound/voice_talk/english/ingame_voice/ingame_cutscene/`
  - 4 muted `notice_01..04.wav` (exact digital silence)
  - 324 muted Sebastian spoken dialogue WAVs (`*_seba.wav`) matching each clip's EXACT
        original `.bsnd` duration (8000 Hz 8-bit mono PCM 0x80 = exact digital zero,
        so cutscenes & subtitles keep 100% original timing while Sebastian's voice is silent).
"""

import glob
import json
import os
import re
import shutil
import struct
import sys
import wave
from pathlib import Path
import numpy as np

sys.path.insert(0, r"F:\dspr_mod\tew_external_mount")
import tango

SR = 44100
SILENCE_SR = 8000
DECODED_DIR = Path(
    r"C:\Users\lenovo\.gemini\antigravity\brain\4335b024-138e-4184-afac-e1892cb5e101\scratch\decoded_wavs"
)
GAME_BASE = Path(r"F:\HG\evil\TheEvilWithin\TheEvilWithin\base")
OUT_OVERLAY = Path(r"F:\HG\evil\TEW1ModManager\runtime_src\haruka_voice_overlay")


def load_npy(sub: str, stem: str) -> np.ndarray:
    p = DECODED_DIR / f"{sub}__{stem}.npy"
    if not p.exists():
        raise FileNotFoundError(p)
    return np.load(p).astype(np.float32)


def apply_fades(y: np.ndarray, fade_in=0.010, fade_out=0.020) -> np.ndarray:
    out = y.copy()
    n = len(out)
    fi = min(int(fade_in * SR), n // 4)
    fo = min(int(fade_out * SR), n // 4)
    if fi > 1:
        t = np.linspace(0.0, np.pi * 0.5, fi, dtype=np.float32)
        out[:fi] *= np.sin(t)
    if fo > 1:
        t = np.linspace(np.pi * 0.5, 0.0, fo, dtype=np.float32)
        out[-fo:] *= np.sin(t)
    return out


def trim_silence(y: np.ndarray, pad_pre=0.015, pad_post=0.035, rel_thr=0.018, abs_thr=0.004) -> np.ndarray:
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    if peak < 1e-6:
        return y
    thr = max(peak * rel_thr, abs_thr)
    nz = np.where(np.abs(y) > thr)[0]
    if len(nz) == 0:
        return y
    i0 = max(0, int(nz[0]) - int(pad_pre * SR))
    i1 = min(len(y), int(nz[-1]) + int(pad_post * SR))
    return apply_fades(y[i0:i1], fade_in=0.010, fade_out=0.020)


def normalize_clip(y: np.ndarray, target_rms_db=-10.0, max_peak_db=-0.2) -> np.ndarray:
    if len(y) == 0:
        return y
    peak = float(np.max(np.abs(y)))
    if peak < 1e-6:
        return y
    mask = np.abs(y) > max(peak * 0.03, 0.003)
    active = y[mask] if np.any(mask) else y
    rms = float(np.sqrt(np.mean(active ** 2)))
    target_rms = 10.0 ** (target_rms_db / 20.0)
    gain = target_rms / max(rms, 1e-6)
    out = y * gain
    # Gentle soft-knee tanh limiter above 0.72 so loud peaks never starve vocal RMS loudness
    knee = 0.72
    max_peak = 10.0 ** (max_peak_db / 20.0)
    span = max(0.05, max_peak - knee)
    mag = np.abs(out)
    over = mag > knee
    if np.any(over):
        out[over] = np.sign(out[over]) * (knee + span * np.tanh((mag[over] - knee) / span))
    return np.clip(out, -max_peak, max_peak).astype(np.float32)


def concat_with_gap(clips, gap_sec=0.10):
    gap = np.zeros(int(gap_sec * SR), dtype=np.float32)
    parts = []
    for i, c in enumerate(clips):
        if i > 0:
            parts.append(gap)
        parts.append(c)
    return np.concatenate(parts) if parts else np.zeros(1024, dtype=np.float32)


def wav_bytes_pcm16(y: np.ndarray) -> bytes:
    pcm = np.clip(np.round(y * 32767.0), -32768, 32767).astype("<i2").tobytes()
    data_sz = len(pcm)
    # Standard 44-byte RIFF WAVE PCM header
    hdr = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_sz, b"WAVE",
        b"fmt ", 16, 1, 1, SR, SR * 2, 2, 16,
        b"data", data_sz,
    )
    return hdr + pcm


def wav_bytes_silence8(duration_sec: float) -> bytes:
    n = max(800, int(round(duration_sec * SILENCE_SR)))
    pcm = b"\x80" * n  # unsigned 8-bit PCM midpoint = exact 0.0 silence
    hdr = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + n, b"WAVE",
        b"fmt ", 16, 1, 1, SILENCE_SR, SILENCE_SR, 1, 8,
        b"data", n,
    )
    return hdr + pcm


def build_voice_bank() -> dict:
    bank = {}

    def put(key: str, y: np.ndarray, rms_db=-9.5):
        y2 = normalize_clip(y, target_rms_db=rms_db, max_peak_db=-0.2)
        bank[key] = wav_bytes_pcm16(y2)

    # 1) 9 action grunts (动作\)
    action_stems = [
        "1001532124", "345579790", "534023424", "587089659", "778312175",
        "826414262", "859639830", "896890244", "943074412",
    ]
    for i, st in enumerate(action_stems, 1):
        put(f"act_{i:02d}", trim_silence(load_npy("动作", st), pad_pre=0.015, pad_post=0.055, rel_thr=0.010, abs_thr=0.002), rms_db=-9.5)

    # 2) 5 light hits (轻击) — preserve full natural tail & strong vocal punch to cut through -7dB decl + hit SFX
    light_stems = ["轻击", "轻击2", "轻击 (2)", "轻击 (3)", "轻击 (4)"]
    for i, st in enumerate(light_stems, 1):
        put(f"hit_light_{i:02d}", trim_silence(load_npy("受击", st), pad_pre=0.015, pad_post=0.095, rel_thr=0.006, abs_thr=0.0015), rms_db=-6.0)

    # 3) 4 heavy hits (带"重"的都是受到重攻击: 中重, 重或感, 重或死, 重或死 (2)) — strong punch over -9dB decl
    heavy_stems = ["中重", "重或感", "重或死", "重或死 (2)"]
    for i, st in enumerate(heavy_stems, 1):
        put(f"hit_heavy_{i:02d}", trim_silence(load_npy("受击", st), pad_pre=0.015, pad_post=0.100, rel_thr=0.006, abs_thr=0.0015), rms_db=-5.5)

    # 4) Death (死亡)
    put("death_01", trim_silence(load_npy("受击", "死亡"), pad_pre=0.015, pad_post=0.110, rel_thr=0.006, abs_thr=0.0015), rms_db=-5.5)

    # 5) 3 coughs (咳嗽)
    cough_stems = ["咳嗽", "咳嗽 (2)", "咳嗽 (3)"]
    for i, st in enumerate(cough_stems, 1):
        put(f"cough_{i:02d}", trim_silence(load_npy("受击", st), pad_pre=0.015, pad_post=0.060, rel_thr=0.010, abs_thr=0.002), rms_db=-10.0)

    # 6) Struggle QTE: merge 挣扎 + 挣扎？ into smooth looping clips!
    st_a = normalize_clip(trim_silence(load_npy("受击", "挣扎"), pad_pre=0.012, pad_post=0.035, rel_thr=0.008, abs_thr=0.002), target_rms_db=-7.5)
    st_b = normalize_clip(trim_silence(load_npy("受击", "挣扎？"), pad_pre=0.012, pad_post=0.035, rel_thr=0.008, abs_thr=0.002), target_rms_db=-7.5)
    put("struggle_ab", concat_with_gap([st_a, st_b], gap_sec=0.09), rms_db=-7.5)
    put("struggle_ba", concat_with_gap([st_b, st_a], gap_sec=0.09), rms_db=-7.5)
    put("struggle_loop", concat_with_gap([st_a, st_b, st_a, st_b], gap_sec=0.10), rms_db=-7.5)

    # 7) Panting / breathing: slice 喘气 (2).mp3 (11.89s) at natural breath pauses!
    y_br = load_npy("受击", "喘气 (2)")
    def sl(t0, t1):
        return apply_fades(y_br[int(t0 * SR) : int(t1 * SR)], fade_in=0.025, fade_out=0.045)

    put("breath_s1", sl(0.04, 0.85), rms_db=-15.5)
    put("breath_s2", sl(2.85, 3.80), rms_db=-15.5)
    put("breath_s3", sl(6.65, 7.80), rms_db=-15.5)
    put("breath_s4", sl(9.10, 10.05), rms_db=-15.5)
    put("breath_l1", sl(0.04, 1.85), rms_db=-15.5)
    put("breath_l2", sl(2.85, 5.00), rms_db=-15.5)
    put("breath_l3", sl(6.65, 9.95), rms_db=-15.5)

    print(f"Prepared {len(bank)} unique processed Haruka voice clips.")
    return bank


def choose_bank_key(stem: str) -> str:
    """Return bank key (or 'SILENCE') for an in-game / cutscene Sebastian WAV stem."""
    s = stem.lower()
    m = re.search(r"_(\d+)$", s)
    idx = int(m.group(1)) if m else 1

    # 1. Actions (动作 9个)
    if s.startswith("action_jump"):
        return f"act_{((idx - 1) % 9) + 1:02d}"
    if s.startswith("action_shove"):
        return f"act_{((idx + 1) % 9) + 1:02d}"
    if s.startswith("attack_kick_stomp"):
        return f"act_{((idx + 4) % 9) + 1:02d}"
    if s.startswith("attack_knife"):
        picks = [2, 4, 7, 9]
        return f"act_{picks[(idx - 1) % len(picks)]:02d}"
    if s.startswith("attack_punch"):
        return f"act_{((idx - 1) % 9) + 1:02d}"
    if s.startswith("attack_sneak_kill") or s == "seb_ending_01_brain_stomp":
        return "act_09"

    # 2. Grab QTE struggle (合并挣扎俩语音循环播放)
    if s.startswith("action_struggle"):
        return "struggle_ab" if (idx % 2 == 1) else "struggle_ba"
    if s.startswith("damage_choking"):
        return "struggle_loop"

    # 3. Light hits (轻击 5个)
    if s.startswith("damage_shot") or s.startswith("damage_wound_reopened"):
        return f"hit_light_{((idx - 1) % 5) + 1:02d}"

    # 4. Heavy hits (带"重"的 4个: 中重, 重或感, 重或死, 重或死 (2))
    if (
        s.startswith("damage_slashed")
        or s.startswith("damage_burned")
        or s.startswith("damage_stomach")
        or s.startswith("damage_choked")
        or s.startswith("damage_drowning")
        or s.startswith("damage_suffering_")
        or s == "village_m_fall_vox_01"
    ):
        return f"hit_heavy_{((idx - 1) % 4) + 1:02d}"

    # 5. Death (死亡 + 重或死 / 重或死 (2))
    if s.startswith("death_scream_short"):
        picks = ["death_01", "hit_heavy_03", "hit_heavy_04"]
        return picks[(idx - 1) % len(picks)]
    if s.startswith("death_"):
        picks = ["death_01", "death_01", "hit_heavy_04"]
        return picks[(idx - 1) % len(picks)]

    # 6. Coughing (咳嗽 3个)
    if s.startswith("coughing_"):
        return f"cough_{((idx - 1) % 3) + 1:02d}"

    # 7. Panting / Breathing (喘气 (2) 切分)
    if s.startswith("breath01") or s.startswith("breath02") or s.startswith("breathing_run_"):
        return f"breath_s{((idx - 1) % 4) + 1}"
    if (
        s.startswith("breath04")
        or s.startswith("breathing_running_stop")
        or s.startswith("syringe_")
        or s.startswith("lifeup_effect_breath")
    ):
        return f"breath_l{((idx - 1) % 3) + 1}"

    # 8. Remaining in-game cues (notice_*) -> MUTE!
    if s.startswith("notice"):
        return "SILENCE"

    raise ValueError(f"Unmapped Sebastian WAV stem: {stem}")


def parse_bsnd_dur(raw: bytes) -> float:
    if len(raw) < 30 or raw[:4] != b"bsnf":
        return 1.0
    off0 = struct.unpack_from(">I", raw, 9 + 8)[0]
    if off0 + 32 > len(raw):
        return 1.0
    ts, pb, plen, flg, dsz = struct.unpack_from(">5I", raw, off0)
    sr_le = struct.unpack_from("<I", raw, off0 + 24)[0]
    sr_be = struct.unpack_from(">I", raw, off0 + 24)[0]
    sr = sr_le if 8000 <= sr_le <= 96000 else sr_be
    if not sr:
        sr = 44100
    return max(0.15, plen / float(sr))


def main():
    if OUT_OVERLAY.exists():
        shutil.rmtree(OUT_OVERLAY)
    out_base = OUT_OVERLAY / "base"

    bank = build_voice_bank()

    archives = sorted(glob.glob(str(GAME_BASE / "*.tangoresource")))
    seen_wav = {}  # wav_rel -> (kind, dur)
    for ap in archives:
        arc = tango.TangoArchive(ap)
        for p in arc.entries:
            p2 = p.replace("\\", "/")
            pl = p2.lower()
            if not pl.startswith("generated/sound/") or not pl.endswith(".bsnd"):
                continue
            wav_rel = re.sub(r"^generated/", "", pl)
            wav_rel = re.sub(r"_msadpcm\.bsnd$", ".wav", wav_rel)
            wav_rel = re.sub(r"\.bsnd$", ".wav", wav_rel)
            if wav_rel in seen_wav:
                continue

            if "/voice_talk/english/ingame_voice/sebastian/" in pl:
                seen_wav[wav_rel] = ("ingame", parse_bsnd_dur(arc.read(p)))
            elif "/voice_talk/english/ingame_voice/ingame_cutscene/" in pl and (
                "seb" in pl or "village_m_fall_vox" in pl
            ):
                seen_wav[wav_rel] = ("cutscene", parse_bsnd_dur(arc.read(p)))
            elif "/voice_talk/" in pl:
                bn = os.path.splitext(os.path.basename(wav_rel))[0]
                toks = bn.split("_")
                if "seba" in toks or "_seba" in bn or "sebastian" in bn:
                    seen_wav[wav_rel] = ("talk_mute", parse_bsnd_dur(arc.read(p)))

    counts = {"replaced_voice": 0, "muted_notice": 0, "muted_talk": 0}
    total_bytes = 0
    audit = {}

    for wav_rel, (kind, orig_dur) in sorted(seen_wav.items()):
        dst = out_base / wav_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        stem = os.path.splitext(os.path.basename(wav_rel))[0]

        if kind in ("ingame", "cutscene"):
            key = choose_bank_key(stem)
            if key == "SILENCE":
                data = wav_bytes_silence8(0.15)
                counts["muted_notice"] += 1
                audit[wav_rel] = "MUTED_SILENCE"
            else:
                data = bank[key]
                counts["replaced_voice"] += 1
                audit[wav_rel] = key
        else:
            # Duration-matched exact digital silence (keeps cutscenes & subtitles 100% in sync!)
            data = wav_bytes_silence8(orig_dur)
            counts["muted_talk"] += 1
            audit[wav_rel] = f"MUTED_TALK({orig_dur:.2f}s)"

        dst.write_bytes(data)
        total_bytes += len(data)

    (OUT_OVERLAY / "voice_mapping_audit.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nVoice overlay generated at: {OUT_OVERLAY}")
    print(f"Summary: {counts}, total WAVs={sum(counts.values())}, total raw size={total_bytes/1024/1024:.2f} MB")


if __name__ == "__main__":
    main()
