"""Package Haruka Mod ZIPs:
1) Haruka_全章节_物理表情语音一体版.zip  (Full Native Mouth Rig + Fixed Head/Limb Dismemberment + Blink/Hurt/Death + Tuned Hair Physics + Self-Illum + Boosted Voice)
2) Haruka_全章节_物理表情一体版.zip      (Model + Full Native Mouth Rig + Fixed Head/Limb Dismemberment + Blink/Hurt/Death + Tuned Hair Physics + Self-Illum, no voice)
3) Haruka_主角动作受击语音包.zip          (Standalone Boosted Voice Replacement + Mute Remaining)
"""

from pathlib import Path
import struct
import sys
import zipfile
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"F:\dspr_mod\tew_external_mount\haruka")
import bmd6
from patch_haruka_mouth_jaw import HarukaJawPatcher
from patch_haruka_dismember import patch_all_dismemberment

BASE_ZIP = Path(r"F:\dspr_mod\tew_external_mount\release\Haruka_全章节外部挂载.zip")
RUNTIME_BIN = Path(r"F:\HG\evil\TEW1ModManager\runtime_src\haruka_runtime.bin")
VOICE_OVERLAY = Path(r"F:\HG\evil\TEW1ModManager\runtime_src\haruka_voice_overlay")

OUT_ALL_ZIP = Path(r"F:\HG\evil\TEW1ModManager\dist\Haruka_全章节_物理表情语音一体版.zip")
OUT_MODEL_ZIP = Path(r"F:\HG\evil\TEW1ModManager\dist\Haruka_全章节_物理表情一体版.zip")
OUT_VOICE_ZIP = Path(r"F:\HG\evil\TEW1ModManager\dist\Haruka_主角动作受击语音包.zip")

if not BASE_ZIP.is_file():
    raise FileNotFoundError(f"Missing baseline ZIP: {BASE_ZIP}")
if not RUNTIME_BIN.is_file():
    raise FileNotFoundError(f"Missing compiled runtime pack: {RUNTIME_BIN}")
if not (VOICE_OVERLAY / "base" / "sound").is_dir():
    raise FileNotFoundError(f"Missing voice overlay: {VOICE_OVERLAY}")

voice_files = []
for sub in ("sound", "generated"):
    root = VOICE_OVERLAY / "base" / sub
    if root.is_dir():
        for p in sorted(root.rglob("*")):
            if p.is_file():
                rel = p.relative_to(VOICE_OVERLAY).as_posix()
                voice_files.append((p, rel))

OUT_ALL_ZIP.parent.mkdir(parents=True, exist_ok=True)

# Step 1: Restore full native CG + gameplay mouth skeleton weights on all Haruka models
patcher = HarukaJawPatcher()
patched_entries = []
prefix = None
patched_model_cnt = 0
patched_vert_cnt = 0

with zipfile.ZipFile(BASE_ZIP, "r") as zin:
    for info in zin.infolist():
        name = info.filename.replace("\\", "/")
        if prefix is None and "base/generated/" in name.lower():
            idx = name.lower().index("base/generated/")
            prefix = name[:idx]
        nl = name.lower()
        if nl.endswith("mod.info") or nl.endswith("haruka_runtime.bin") or nl.endswith("tew1_dyn.bin"):
            continue
        data = zin.read(info.filename)
        if nl.endswith(".bmd6model"):
            data, n_v = patcher.patch_bmd6_bytes(data, Path(name).stem)
            if n_v > 0:
                patched_model_cnt += 1
                patched_vert_cnt += n_v
        patched_entries.append((name, data))

if prefix is None:
    prefix = "Haruka-overlay/"

print(f"Restored native mouth skeleton skinning on {patched_model_cnt} models ({patched_vert_cnt} mouth vertices).")

# Step 2: Fix head/hair/accessory decapitation & split pl0000_ng arms/legs/torso dismemberment
patched_entries = patch_all_dismemberment(patched_entries)


def update_runtime_bin_extra_fps(base_bin: bytes, entries: list) -> bytes:
    """Ensure every non-hair/non-face Haruka surface in patched_entries is registered in tew1_dyn.bin v2 Section 6."""
    # Parse up to Section 6 offset
    off = 4
    ver, nSkel, nChains, nCols, nHairFps, nFaces, nMorphs = struct.unpack_from("<7I", base_bin, off)
    assert ver == 2, f"Expected tew1_dyn.bin v2, got v{ver}"
    off += 28
    off += nSkel * (4 + 12 + 48 + 7 * 16)
    for _ in range(nChains):
        nb = struct.unpack_from("<I", base_bin, off)[0]
        off += 20 + (nb + 1) * 12
    off += nCols * 32
    off += nHairFps * 44
    nhv = struct.unpack_from("<I", base_bin, off)[0]
    off += 4 + nhv * 8
    for _ in range(nFaces):
        off += 44
        for _ in range(nMorphs):
            cnt = struct.unpack_from("<I", base_bin, off)[0]
            off += 4 + cnt * 16

    sec6_off = off
    nExtra = struct.unpack_from("<I", base_bin, off)[0]
    off += 4
    extra_fps = {}
    for _ in range(nExtra):
        vc = struct.unpack_from("<I", base_bin, off)[0]
        pts_bytes = base_bin[off + 4 : off + 40]
        extra_fps[(vc, pts_bytes)] = (vc, pts_bytes)
        off += 40

    # Add every Haruka body/eye/accessory/severed-limb surface from patched_entries
    FACE_PARTS = (3, 5, 6, 7)
    for name, data in entries:
        if not name.lower().endswith(".bmd6model"):
            continue
        m = bmd6.read_model(data)
        for s in m.surfaces:
            if not s.material.startswith("textures/tew_haruka/mat_0"):
                continue
            part = int(s.material[-2:])
            if part == 2 or part in FACE_PARTS:
                continue
            pts_bytes = s.positions[:3].astype("<f4").tobytes()
            key = (s.count, pts_bytes)
            if key not in extra_fps:
                extra_fps[key] = key

    new_sec6 = bytearray(struct.pack("<I", len(extra_fps)))
    for vc, pts_bytes in extra_fps.values():
        new_sec6.extend(struct.pack("<I", vc))
        new_sec6.extend(pts_bytes)
    print(f"Updated tew1_dyn.bin v2 Section 6 extraCharFps: {nExtra} -> {len(extra_fps)} surface fingerprints.")
    return base_bin[:sec6_off] + bytes(new_sec6)


runtime_bin_bytes = update_runtime_bin_extra_fps(RUNTIME_BIN.read_bytes(), patched_entries)


def write_model_zip(out_zip: Path, include_voice: bool, mod_info_text: str):
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zout:
        written = set()
        for name, data in patched_entries:
            zout.writestr(name, data)
            written.add(name.lower())
        zout.writestr(prefix + "base/generated/tew1_dyn.bin", runtime_bin_bytes)
        written.add((prefix + "base/generated/tew1_dyn.bin").lower())
        if include_voice:
            for p, rel in voice_files:
                arcname = prefix + rel
                if arcname.lower() in written:
                    continue
                zout.write(p, arcname)
                written.add(arcname.lower())
        zout.writestr(prefix + "mod.info", mod_info_text.encode("utf-8"))

    with zipfile.ZipFile(out_zip, "r") as zchk:
        names = zchk.namelist()
        wavs = sum(1 for n in names if n.lower().endswith(".wav"))
        print(f"Created: {out_zip} ({out_zip.stat().st_size:,} bytes, entries={len(names)}, wavs={wavs}, has_dyn={any(n.endswith('tew1_dyn.bin') for n in names)})")


# 1) All-in-one Haruka ZIP
write_model_zip(
    OUT_ALL_ZIP,
    include_voice=True,
    mod_info_text=(
        "name=Haruka 全章节 · 物理表情 & 语音一体版\n"
        "version=v3.5 (完整断肢修复 + 原生CG嘴部骨骼 + 柔和受击表情 + F7/F8/F9三档自发光 + 增强受击语音)\n"
    ),
)

# 2) Model-only Haruka ZIP
write_model_zip(
    OUT_MODEL_ZIP,
    include_voice=False,
    mod_info_text=(
        "name=Haruka 全章节 · 物理表情一体版\n"
        "version=v3.5 (完整断肢修复 + 原生CG嘴部骨骼 + 柔和受击表情 + F7/F8/F9三档自发光)\n"
    ),
)

# 3) Standalone Voice-Only ZIP
with zipfile.ZipFile(OUT_VOICE_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zout:
    vprefix = "Haruka-voice-overlay/"
    for p, rel in voice_files:
        zout.write(p, vprefix + rel)
    vinfo = (
        "name=Haruka 主角语音包 (动作/增强受击/QTE挣扎 + 隐藏原版剩余语音)\n"
        "version=v1.1\n"
    ).encode("utf-8")
    zout.writestr(vprefix + "mod.info", vinfo)

print(f"Created: {OUT_VOICE_ZIP} ({OUT_VOICE_ZIP.stat().st_size:,} bytes)")
with zipfile.ZipFile(OUT_VOICE_ZIP, "r") as zchk:
    names = zchk.namelist()
    wavs = sum(1 for n in names if n.lower().endswith(".wav"))
    print(f"  Entries={len(names)}, wavs={wavs}")
