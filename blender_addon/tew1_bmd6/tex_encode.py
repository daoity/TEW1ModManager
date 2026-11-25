"""Native BC1/DXT1 & BC3/DXT5 .bimage encoder + 1-click batch material conversion (no external DDS tool required)."""

from pathlib import Path
import re
from struct import pack, pack_into

import bpy
from bpy.props import StringProperty
import numpy as np

from . import build
from .presets import BIMAGE_HEADER, PRESETS, bimage_from_dds, native_material_path


def _pack_rgb565(rgb):
    r = (rgb[..., 0].astype(np.uint16) >> 3) & 0x1F
    g = (rgb[..., 1].astype(np.uint16) >> 2) & 0x3F
    b = (rgb[..., 2].astype(np.uint16) >> 3) & 0x1F
    return (r << 11) | (g << 5) | b


def _unpack_rgb565(c):
    r = ((c >> 11) & 0x1F).astype(np.int32)
    g = ((c >> 5) & 0x3F).astype(np.int32)
    b = (c & 0x1F).astype(np.int32)
    r = (r << 3) | (r >> 2)
    g = (g << 2) | (g >> 4)
    b = (b << 3) | (b >> 2)
    return np.stack((r, g, b), axis=-1)


def _encode_bc1_blocks(rgba_u8):
    """Vectorized fast BC1/DXT1 color block encoder on (H, W, 4) uint8 image (H, W multiples of 4)."""
    h, w, _ = rgba_u8.shape
    bh, bw = h // 4, w // 4
    blocks = rgba_u8[:, :, :3].reshape(bh, 4, bw, 4, 3).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 3)

    c_min = blocks.min(axis=1).astype(np.int32)
    c_max = blocks.max(axis=1).astype(np.int32)
    inset = (c_max - c_min) >> 4
    c_min = np.clip(c_min + inset, 0, 255).astype(np.uint8)
    c_max = np.clip(c_max - inset, 0, 255).astype(np.uint8)

    c0 = _pack_rgb565(c_max)
    c1 = _pack_rgb565(c_min)

    # Guarantee 4-color opaque mode (c0 > c1) whenever colors differ
    swap = c0 < c1
    if np.any(swap):
        tmp = c0[swap].copy()
        c0[swap] = c1[swap]
        c1[swap] = tmp

    p0 = _unpack_rgb565(c0)
    p1 = _unpack_rgb565(c1)
    p2 = (2 * p0 + p1 + 1) // 3
    p3 = (p0 + 2 * p1 + 1) // 3
    pal = np.stack((p0, p1, p2, p3), axis=1)  # (N, 4, 3)

    pix = blocks.astype(np.int32)             # (N, 16, 3)
    diff = pix[:, :, None, :] - pal[:, None, :, :]
    dist = np.einsum("npkc,npkc->npk", diff, diff)
    idx = np.argmin(dist, axis=2).astype(np.uint32)  # (N, 16)
    idx[c0 == c1] = 0

    shifts = (np.arange(16, dtype=np.uint32) * 2)[None, :]
    bits = np.bitwise_or.reduce(idx << shifts, axis=1)

    out = np.empty((len(c0), 8), dtype=np.uint8)
    out[:, 0] = c0 & 0xFF
    out[:, 1] = (c0 >> 8) & 0xFF
    out[:, 2] = c1 & 0xFF
    out[:, 3] = (c1 >> 8) & 0xFF
    out[:, 4] = bits & 0xFF
    out[:, 5] = (bits >> 8) & 0xFF
    out[:, 6] = (bits >> 16) & 0xFF
    out[:, 7] = (bits >> 24) & 0xFF
    return out


def _encode_bc3_alpha(rgba_u8):
    """Vectorized BC3/DXT5 8-level alpha block encoder on (H, W, 4) uint8 image."""
    h, w, _ = rgba_u8.shape
    bh, bw = h // 4, w // 4
    alpha = rgba_u8[:, :, 3].reshape(bh, 4, bw, 4).transpose(0, 2, 1, 3).reshape(-1, 16)

    a0 = alpha.max(axis=1).astype(np.int32)
    a1 = alpha.min(axis=1).astype(np.int32)

    pal = np.stack((
        a0,
        a1,
        (6 * a0 + 1 * a1 + 3) // 7,
        (5 * a0 + 2 * a1 + 3) // 7,
        (4 * a0 + 3 * a1 + 3) // 7,
        (3 * a0 + 4 * a1 + 3) // 7,
        (2 * a0 + 5 * a1 + 3) // 7,
        (1 * a0 + 6 * a1 + 3) // 7,
    ), axis=1)  # (N, 8)

    diff = np.abs(alpha[:, :, None].astype(np.int32) - pal[:, None, :])
    idx = np.argmin(diff, axis=2).astype(np.uint64)
    idx[a0 == a1] = 0

    shifts = (np.arange(16, dtype=np.uint64) * 3)[None, :]
    bits = np.bitwise_or.reduce(idx << shifts, axis=1)

    out = np.empty((len(a0), 8), dtype=np.uint8)
    out[:, 0] = a0.astype(np.uint8)
    out[:, 1] = a1.astype(np.uint8)
    for b in range(6):
        out[:, 2 + b] = ((bits >> np.uint64(8 * b)) & np.uint64(0xFF)).astype(np.uint8)
    return out


def bimage_from_rgba(rgba_u8, use_bc3=False):
    """Encode a top-down (H, W, 4) uint8 RGBA image with full mip chain into a TEW1 .bimage."""
    h, w, _ = rgba_u8.shape
    # Snap dimensions to multiples of 4 (clamp to [4, 4096])
    nw = max(4, min(4096, (w // 4) * 4 or 4))
    nh = max(4, min(4096, (h // 4) * 4 or 4))
    if (nw, nh) != (w, h):
        ys = np.linspace(0, h - 1, nh).astype(np.int32)
        xs = np.linspace(0, w - 1, nw).astype(np.int32)
        cur = rgba_u8[np.ix_(ys, xs)]
    else:
        cur = rgba_u8

    mode = 11 if use_bc3 else 10
    header = bytearray(BIMAGE_HEADER)
    pack_into(">II", header, 16, cur.shape[1], cur.shape[0])
    header[36] = mode

    mips = []
    level = 0
    while cur.shape[0] >= 4 and cur.shape[1] >= 4:
        ch, cw = cur.shape[0], cur.shape[1]
        # Ensure current mip level is multiple of 4
        if ch % 4 or cw % 4:
            break
        if use_bc3:
            a_blk = _encode_bc3_alpha(cur)
            c_blk = _encode_bc1_blocks(cur)
            raw = np.hstack((a_blk, c_blk)).tobytes()
        else:
            raw = _encode_bc1_blocks(cur).tobytes()
        mips.append(pack(">5I", level, 0, cw, ch, len(raw)) + raw)
        level += 1
        nh2, nw2 = ch // 2, cw // 2
        if nh2 < 4 or nw2 < 4 or (nh2 % 4) or (nw2 % 4):
            break
        cur = (
            cur[:nh2 * 2, :nw2 * 2]
            .reshape(nh2, 2, nw2, 2, 4)
            .mean(axis=(1, 3))
            .round()
            .astype(np.uint8)
        )

    pack_into(">I", header, 28, len(mips))
    return bytes(header) + b"".join(mips)


def rgba_from_blender_image(image):
    """Read a Blender Image datablock into a top-down (H, W, 4) uint8 numpy array."""
    w, h = int(image.size[0]), int(image.size[1])
    if w < 4 or h < 4:
        raise ValueError(f"贴图 {image.name} 尺寸过小 ({w}x{h})。")
    buf = np.empty(w * h * 4, dtype=np.float32)
    image.pixels.foreach_get(buf)
    rgba = np.clip(buf.reshape(h, w, 4) * 255.0 + 0.5, 0, 255).astype(np.uint8)
    # Flip vertically: Blender is bottom-to-top, DDS/BImage is top-to-bottom
    return rgba[::-1].copy()


def find_material_albedo_image(mat):
    """Locate the primary Base Color / diffuse Image Texture node in a Blender material (Principled or MMD Shader)."""
    if mat is None or not getattr(mat, "node_tree", None):
        return None
    nodes = mat.node_tree.nodes
    # 1. Check Principled BSDF Base Color link
    for node in nodes:
        if node.type == "BSDF_PRINCIPLED":
            inp = node.inputs.get("Base Color")
            if inp and inp.is_linked:
                src = inp.links[0].from_node
                if src.type == "TEX_IMAGE" and src.image:
                    return src.image
                # Handle MMD / MixRGB / HueSat intermediate nodes
                for sub_in in src.inputs:
                    if sub_in.is_linked and sub_in.links[0].from_node.type == "TEX_IMAGE" and sub_in.links[0].from_node.image:
                        return sub_in.links[0].from_node.image
    # 2. Check MMD Shader group "Base Tex" or first TEX_IMAGE node
    for node in nodes:
        if node.type == "TEX_IMAGE" and node.image:
            low = (node.name + " " + node.label).lower()
            if any(k in low for k in ("base", "diffuse", "albedo", "color", "mmd_base")):
                return node.image
    for node in nodes:
        if node.type == "TEX_IMAGE" and node.image:
            return node.image
    return None


def export_material_any_source(root, key, source_path_or_image, preset):
    """Export TEW1 .bimage + .decl from either a DDS/PNG/TGA/JPG file path OR a Blender Image datablock."""
    key = native_material_path(key)
    index, alpha, _ = PRESETS[preset]
    color = key + "_c"

    if isinstance(source_path_or_image, bpy.types.Image):
        rgba = rgba_from_blender_image(source_path_or_image)
        albedo = bimage_from_rgba(rgba, use_bc3=alpha)
    else:
        path = Path(source_path_or_image)
        if path.suffix.lower() == ".dds":
            albedo = bimage_from_dds(path.read_bytes(), alpha)
        else:
            img = bpy.data.images.load(str(path), check_existing=True)
            try:
                rgba = rgba_from_blender_image(img)
            finally:
                if img.users == 0:
                    bpy.data.images.remove(img)
            albedo = bimage_from_rgba(rgba, use_bc3=alpha)

    declaration = build.material(index, alpha, texture=color)
    build.put(root, f"generated/textures/{color}.bimage", albedo)
    build.put(root, f"generated/decls/material/{key}.decl", declaration)
    return key


def _sanitize_slug(text, fallback):
    slug = re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")
    return slug or fallback


def _guess_preset(mat, rgba):
    name = mat.name.lower()
    # 1. Tight innerwear/panties/bra MUST stay opaque BC1 so transparent-padding pixels never turn innerwear sheer!
    if any(k in name for k in ("panty", "panties", "underwear", "innerwear", "inner_wear", "bra", "lingerie", "briefs", "内裤", "内衣", "胖次", "胸罩")):
        return "OPAQUE"
    # 2. Explicit sheer outerwear
    if any(k in name for k in ("sheer", "gauze", "chiffon", "pajama_outer", "outer_sheer", "透纱", "薄纱", "半透外套", "睡衣外套")):
        return "SHEER_OUTER"
    # 3. Explicit alpha-cutout overlays (eyelashes, blush decals, tears, hair shadow/kiwa, lace)
    if any(k in name for k in (
        "lash", "eyelash", "eyebrush", "brow", "tear", "tere", "blush", "shadow", "kiwa", "hacyu",
        "lace", "alpha", "trans", "cutout", "decal", "睫毛", "眉", "泪", "腮红", "蕾丝", "透明",
    )):
        return "CUTOUT"
    # 4. Solid hair (never misclassify MMD 32-bit TGA hair atlases with empty padding as CUTOUT!)
    if any(k in name for k in ("hair", "maegami", "bang", "ponytail", "braid", "髪", "发")):
        return "HAIR"
    # 5. Core solid face/body/clothing/eye/mouth materials (protect against 32-bit TGA atlas padding!)
    if any(k in name for k in (
        "face", "skin", "body", "head", "wear", "cloth", "shirt", "pants", "skirt", "dress", "coat",
        "jacket", "shoes", "boots", "sock", "hand", "glove", "scarf", "ribbon", "tie", "belt",
        "tongue", "teeth", "mouth", "eye", "eyehole", "hau", "脸", "颜", "肤", "身", "衣", "服", "裤", "鞋", "手", "舌", "眼",
    )):
        return "OPAQUE"
    # 6. Fallback heuristic for unknown material names: require genuine alpha pixels
    if rgba is not None and int((rgba[:, :, 3] < 240).sum()) > max(64, rgba.shape[0] * rgba.shape[1] // 200):
        return "CUTOUT"
    return "OPAQUE"


class TEW1BatchConvertMaterials(bpy.types.Operator):
    bl_idname = "material.tew1_batch_convert"
    bl_label = "一键自动转换角色全部材质 (免手动转DDS)"
    bl_description = "自动读取选中网格或当前骨架下所有自定义网格的 Blender 贴图（PNG/TGA/JPG/内嵌图），自动按贴图去重（大幅减小包体），智能区分不透明/发片/透明裁切/透纱外套，批量生成 .bimage 与 .decl 并绑定路径"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from . import active_rig
        from .dismember import ZERO_HIDE
        from .workflow import loose_root

        ws = context.scene.tew1_workspace
        try:
            root = loose_root(ws.overlay)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        # Gather target meshes: either selected meshes, or all visible custom children of active rig
        meshes = [o for o in context.selected_objects if o.type == "MESH" and not o.get(ZERO_HIDE)]
        if not meshes:
            rig = active_rig(context)
            if rig:
                meshes = [o for o in rig.children if o.type == "MESH" and not o.get(ZERO_HIDE)]
        if not meshes:
            self.report({"ERROR"}, "请先选中角色网格或骨架。")
            return {"CANCELLED"}

        prefix = _sanitize_slug(ws.batch_mat_prefix, "tew_custom")
        converted = {}
        dedup_by_tex = {}  # (image.name, preset) -> key
        skipped = []
        idx = 0
        reused = 0
        for obj in meshes:
            if not obj.data.materials or obj.data.materials[0] is None:
                skipped.append(f"{obj.name}(无材质)")
                continue
            mat = obj.data.materials[0]
            if mat in converted:
                continue
            img = find_material_albedo_image(mat)
            if img is None:
                skipped.append(f"{mat.name}(未找到贴图节点)")
                continue
            try:
                rgba = rgba_from_blender_image(img)
                preset = _guess_preset(mat, rgba)
                tex_sig = (img.name, preset)
                if tex_sig in dedup_by_tex:
                    key = dedup_by_tex[tex_sig]
                    mat["tew1_material_path"] = key
                    mat["tew1_sheer_outer"] = (preset == "SHEER_OUTER")
                    converted[mat] = (key, preset)
                    reused += 1
                    continue
                key = f"textures/{prefix}/mat_{idx:02d}"
                key = native_material_path(key)
                index_num, alpha, _ = PRESETS[preset]
                if not alpha:
                    rgba[:, :, 3] = 255
                color = key + "_c"
                albedo = bimage_from_rgba(rgba, use_bc3=alpha)
                decl = build.material(index_num, alpha, texture=color)
                build.put(root, f"generated/textures/{color}.bimage", albedo)
                build.put(root, f"generated/decls/material/{key}.decl", decl)
                mat["tew1_material_path"] = key
                mat["tew1_sheer_outer"] = (preset == "SHEER_OUTER")
                dedup_by_tex[tex_sig] = key
                converted[mat] = (key, preset)
                idx += 1
            except Exception as err:
                skipped.append(f"{mat.name}({err})")

        if not converted:
            self.report({"ERROR"}, "未能转换任何材质：" + "; ".join(skipped[:4]))
            return {"CANCELLED"}
        extra = f"，跳过 {len(skipped)} 个" if skipped else ""
        dedup_msg = f"（按贴图去重复用 {reused} 处）" if reused else ""
        self.report({"INFO"}, f"已生成 {idx} 套唯一 TEW1 材质并绑定 {len(converted)} 个材质槽{dedup_msg}{extra}！")
        return {"FINISHED"}


CLASSES = (TEW1BatchConvertMaterials,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
