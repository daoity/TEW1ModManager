"""TEW1 overlay presets, native rig mapping and BImage packaging."""

import json
from pathlib import Path, PurePosixPath
import re
from struct import pack, pack_into, unpack_from

from . import build


# Match the verified PC BImage header, leaving dimensions, format and mip
# metadata to the DDS being written.
BIMAGE_HEADER = bytes.fromhex(
    "545c0f36094d4942000000000000000000000010000000100000000000000003000000000a000000050000000000"
)
FORMAT = {
    b"DXT1": (10, 8), b"DXT5": (11, 16),
    71: (10, 8), 72: (10, 8), 77: (11, 16), 78: (11, 16),
}
PRESETS = {
    "OPAQUE": (0, False, "衣服和皮肤"),
    "HAIR": (2, False, "不透明发片"),
    "CUTOUT": (6, True, "睫毛和透明裁切"),
}


def native_material_path(value):
    if not re.fullmatch(r"[a-z0-9_/-]+", value):
        raise ValueError("游戏资源名请用小写英文字母、数字、下划线和斜杠。")
    path = PurePosixPath(value)
    if path.is_absolute() or not value.startswith("textures/") or path.as_posix() != value:
        raise ValueError("材质引用需要形如 textures/作者名/材质名。")
    return path.as_posix()


def bimage_from_dds(dds, require_alpha):
    if len(dds) < 128 or dds[:4] != b"DDS " or unpack_from("<I", dds, 4)[0] != 124:
        raise ValueError("请选择有效的 DDS 文件。")
    height, width, _, depth, count = unpack_from("<5I", dds, 12)
    codec = dds[84:88]
    pos = 128
    cube_or_volume = unpack_from("<I", dds, 112)[0]
    if depth > 1 or cube_or_volume & 0x200200:
        raise ValueError("只支持二维 DDS。")
    if codec == b"DX10":
        code, dimension, flags, array_size, _ = unpack_from("<5I", dds, pos)
        if dimension != 3 or flags & 4 or array_size != 1:
            raise ValueError("只支持一张二维 DDS 图。")
        codec = code
        pos += 20
    layout = FORMAT.get(codec)
    if layout is None:
        raise ValueError("请用已有贴图工具导出 BC1/DXT1 或 BC3/DXT5 DDS。")
    mode, block_bytes = layout
    if require_alpha and mode != 11:
        raise ValueError("裁切材质使用带 Alpha 的 BC3/DXT5。")
    if min(width, height) < 4 or max(width, height) > 8192 or width % 4 or height % 4:
        raise ValueError("DDS 宽高须为 4 的倍数，范围 4–8192。")
    header = bytearray(BIMAGE_HEADER)
    pack_into(">II", header, 16, width, height)
    header[36] = mode
    mips = []
    for level in range(max(1, count)):
        w, h = max(1, width >> level), max(1, height >> level)
        size = ((w + 3) // 4) * ((h + 3) // 4) * block_bytes
        if pos + size > len(dds):
            raise ValueError("DDS 数据不完整。")
        if min(w, h) < 4:
            break
        mips.append(pack(">5I", level, 0, w, h, size) + dds[pos:pos + size])
        pos += size
    pack_into(">I", header, 28, len(mips))
    return bytes(header) + b"".join(mips)


def export_material(root, key, source, preset):
    key = native_material_path(key)
    index, alpha, _ = PRESETS[preset]
    color = key + "_c"
    albedo = bimage_from_dds(source.read_bytes(), alpha)
    declaration = build.material(index, alpha, texture=color)
    build.put(root, f"generated/textures/{color}.bimage", albedo)
    build.put(root, f"generated/decls/material/{key}.decl", declaration)
    return key


def bone_preset(direction):
    mapping = {
        "pelvis": ("pelvis", ()), "spine_01": ("spine_01", ("spine_00",)),
        "spine_02": ("spine_02", ()), "neck": ("neck_00", ("neck_01",)),
        "head": ("head", ()),
    }
    for side in ("L", "R"):
        bone = side.lower() + "_"
        for role, game_name, extras in (
            ("clavicle", "shoulder", ()), ("upperarm", "upperarm", ()), ("forearm", "forearm", ()),
            ("hand", "hand", ()), ("thigh", "thigh", ()), ("shin", "shin", ()),
            ("foot", "foot", ()), ("toe", "toe", ()), ("knee", "sup_knee", ()),
        ):
            mapping[role + "_" + side] = (bone + game_name, tuple(bone + tail for tail in extras))
        for digit in ("thumb", "index", "middle", "ring", "pinky"):
            for segment in (1, 2, 3):
                idx = segment - (1 if digit == "thumb" else 0)
                mapping[f"{digit}_{segment:02}_{side}"] = (f"{bone}{digit}_{idx:02}", ())
    return {
        "preset_info": {"name": "The Evil Within 1 · Sebastian", "type": direction, "version": "2.0"},
        "mappings": {role: {"main": [main], "aux": list(aux)} for role, (main, aux) in mapping.items()},
    }


def export_toolkit_presets(output):
    for folder, role in (("import", "X_PRESET"), ("bone", "Y_PRESET")):
        folder = Path(output) / folder
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "TEW1_Sebastian.json"
        target.write_text(json.dumps(bone_preset(role), ensure_ascii=False, indent=2) + "\n",
                          encoding="utf8")
