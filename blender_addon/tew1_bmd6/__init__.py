"""Blender import and export for TEW1 PC skinned BMD6 resources."""
bl_info = {
    "name": "TEW1 BMD6 & TEW Physical 制作套件 (Blender 4-5)",
    "author": "TEW1 Mod Tools",
    "version": (2, 7, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar (TEW Mesh / TEW Physical) & File > Import / Export",
    "description": "兼容 Blender 4.0–5.2+：内置原版游戏 .tangoresource 一键提取与导入、BMD6 读写、MMD/VRChat 一键对骨（防双开门窄肩+脚掌1:1+内衣防穿模）、免转DDS/透纱材质、断肢拆分、TEW Physical 物理与 TEW Facial 表情。",
    "category": "Import-Export",
}

from collections import defaultdict
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from struct import pack, unpack_from
from tempfile import NamedTemporaryFile, TemporaryDirectory
import base64
import re

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper
from mathutils import Matrix
import numpy as np

from . import bmd6, build


TEMPLATE = "tew1_bmd6_template"
SLOT = "tew1_surface_index"
SIGNATURE = "tew1_original_signature"


def template_bytes(rig):
    text = bpy.data.texts.get(rig.get(TEMPLATE, ""))
    if text is None:
        raise ValueError("所选骨架没有保存 BMD6 原始模板。")
    return base64.b64decode(text.as_string())


def make_rig(context, model, name, collection):
    bones = bpy.data.armatures.new(name)
    rig = bpy.data.objects.new(name, bones)
    collection.objects.link(rig)
    context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        for index, joint in enumerate(model.skeleton.names):
            inverse = np.vstack((model.skeleton.inverse[index], (0, 0, 0, 1)))
            world = Matrix(np.linalg.inv(inverse).tolist())
            bone = bones.edit_bones.new(joint)
            bone.length = 2.0
            bone.matrix = world
            parent = model.skeleton.parents[index]
            if parent != 0xFFFF:
                bone.parent = bones.edit_bones[model.skeleton.names[parent]]
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    return rig


def skin_weights(rows, skeleton):
    names = dict(zip(skeleton.remap, skeleton.names))
    for row in rows:
        code = int(row[23])
        b, c, d = (code >> 4) / 30.0, ((code >> 2) & 3) / 9.0, (code & 3) / 12.0
        result = defaultdict(float)
        for joint, value in zip(row[28:32], (1 - b - c - d, b, c, d)):
            if joint in names and value > 1e-7:
                result[names[joint]] += value
        yield result


def encode_weights(groups, skeleton, original=None):
    if original is not None and groups == original[0]:
        return original[1]
    by_name = dict(zip(skeleton.names, skeleton.remap))
    order = sorted(((name, weight) for name, weight in groups.items() if name in by_name and weight > 1e-7),
                   key=lambda item: -item[1])[:4]
    if not order:
        raise ValueError("网格含有未绑定到原生骨骼的顶点。")
    total = sum(item[1] for item in order)
    ids = [by_name[name] for name, _ in order]
    ids += [ids[0]] * (4 - len(ids))
    weight = [item[1] / total for item in order[1:]]
    weight += [0.0] * (3 - len(weight))
    b, c, d = (round(x * scale) for x, scale in zip(weight, (30, 9, 12)))
    return (b * 16 + c * 4 + d, *ids)


def dds_from_bimage(data):
    if data[4:8] != b"\x09MIB":
        raise ValueError("无效的 BImage 标记。")
    codec = {10: b"DXT1", 11: b"DXT5"}.get(data[36])
    if codec is None:
        raise ValueError("预览只支持 BC1 和 BC3 BImage。")
    width, height = unpack_from(">II", data, 16)
    index, _face, row_width, row_height, size = unpack_from(">5I", data, 46)
    expected = ((width + 3) // 4) * ((height + 3) // 4) * (8 if codec == b"DXT1" else 16)
    if index or size != expected or (width, height) != (row_width, row_height) or len(data) < 66 + size:
        raise ValueError("BImage 主级贴图尺寸无效。")
    header = b"DDS " + pack("<7I", 124, 0x81007, height, width, size, 0, 1) + bytes(44)
    header += pack("<2I4s5I", 32, 4, codec, 0, 0, 0, 0, 0) + pack("<5I", 0x1000, 0, 0, 0, 0)
    return header + data[66:66 + size]


def preview_material(path, base, materials):
    if path in materials:
        return materials[path]
    mat = bpy.data.materials.new(path.rsplit("/", 1)[-1])
    mat["tew1_material_path"] = path
    materials[path] = mat
    if base is None:
        return mat
    decl_root = base / "generated/decls/material"
    decl = (decl_root / (path + ".decl")).resolve()
    if not decl.is_relative_to(decl_root) or not decl.is_file():
        return mat
    text = decl.read_text(encoding="utf8", errors="replace")
    source = re.search(r'(?m)^\s*(?:transmap|diffusemap)\s+"?([^\s"]+)', text)
    if not source:
        return mat
    texture_root = base / "generated/textures"
    image_path = (texture_root / (source.group(1) + ".bimage")).resolve()
    if image_path.is_relative_to(texture_root) and image_path.is_file():
        try:
            dds = dds_from_bimage(image_path.read_bytes())
        except (ValueError, IndexError):
            return mat
        with TemporaryDirectory(prefix="tew1-preview-") as folder:
            temporary = Path(folder) / (image_path.stem + ".dds")
            temporary.write_bytes(dds)
            image = bpy.data.images.load(str(temporary))
            image.pack()
            image.filepath = image_path.name
        from .compat import ensure_material_nodes
        nt = ensure_material_nodes(mat)
        nodes = nt.nodes
        shader = next((node for node in nodes if node.type == "BSDF_PRINCIPLED"), None)
        if shader is not None:
            texture = nodes.new("ShaderNodeTexImage")
            texture.image = image
            nt.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    return mat


def has_area(surface):
    positions = surface.positions[surface.indices].astype(float)
    return np.linalg.norm(np.cross(positions[:, 1] - positions[:, 0], positions[:, 2] - positions[:, 0]), axis=1) > 1e-9


def make_mesh(surface, collection, rig, skeleton, slot, base, materials):
    source_faces = surface.indices[has_area(surface)]
    if not len(source_faces):
        return None
    rows = np.frombuffer(surface.vertices, "u1").reshape(-1, 32)
    mesh = bpy.data.meshes.new(surface.name)
    faces = source_faces[:, [0, 2, 1]]
    mesh.from_pydata(surface.positions.tolist(), [], faces.tolist(), shade_flat=False)
    texture = np.ndarray((surface.count, 2), dtype=">f4", buffer=surface.vertices, offset=12, strides=(32, 4))
    texture = texture.astype("f4")
    texture[:, 1] = 1 - texture[:, 1]
    layer = mesh.uv_layers.new(name="TEW1 UV")
    layer.uv.foreach_set("vector", texture[faces.ravel()].ravel())
    normal = build.normalize(rows[:, 20:23].astype(float) - 127.5)
    mesh.normals_split_custom_set_from_vertices(normal.tolist())
    source_indices = mesh.attributes.new("tew1_source_vertex", "INT", "POINT")
    source_indices.data.foreach_set("value", np.arange(surface.count, dtype="i4"))
    obj = bpy.data.objects.new(surface.name, mesh)
    collection.objects.link(obj)
    obj.parent = rig
    obj[SLOT] = slot
    mesh.materials.append(preview_material(surface.material, base, materials))
    groups = {}
    for index, weights in enumerate(skin_weights(rows, skeleton)):
        for name, value in weights.items():
            if name not in groups:
                groups[name] = obj.vertex_groups.new(name=name)
            groups[name].add([index], value, "REPLACE")
    modifier = obj.modifiers.new("TEW1 Armature", "ARMATURE")
    modifier.object = rig
    return obj


def gather_mesh(obj, rig):
    mesh = obj.data
    if not mesh.uv_layers.active:
        raise ValueError(f"{obj.name} 缺少 UV。")
    mesh.calc_loop_triangles()
    if not mesh.loop_triangles:
        raise ValueError(f"{obj.name} 没有可导出的三角面。")
    if any(mod.show_viewport and mod.type != "ARMATURE" for mod in obj.modifiers):
        raise ValueError(f"{obj.name} 含有未应用的网格修改器，请先应用。")
    transform = rig.matrix_world.inverted() @ obj.matrix_world
    world = np.asarray(transform, dtype=float)
    vertices = np.empty((len(mesh.vertices), 3), dtype="f4")
    mesh.vertices.foreach_get("co", vertices.ravel())
    points = vertices @ world[:3, :3].T + world[:3, 3]
    normal = np.empty((len(mesh.loops), 3), dtype="f4")
    mesh.corner_normals.foreach_get("vector", normal.ravel())
    normal = build.normalize(normal @ np.linalg.inv(world[:3, :3]))
    uv = np.empty((len(mesh.loops), 2), dtype="f4")
    mesh.uv_layers.active.uv.foreach_get("vector", uv.ravel())
    uv[:, 1] = 1 - uv[:, 1]
    loop_ids = np.empty((len(mesh.loop_triangles), 3), dtype="i4")
    mesh.loop_triangles.foreach_get("loops", loop_ids.ravel())
    vertex_ids = np.empty(len(mesh.loops), dtype="i4")
    mesh.loops.foreach_get("vertex_index", vertex_ids)
    options = {group.index: group.name for group in obj.vertex_groups}
    groups = [{options[g.group]: round(g.weight, 7) for g in vertex.groups} for vertex in mesh.vertices]
    attributes = mesh.attributes.get("tew1_source_vertex")
    sources = np.full(len(vertices), -1, dtype="i4")
    if attributes is not None and attributes.domain == "POINT" and attributes.data_type == "INT":
        attributes.data.foreach_get("value", sources)
    return points, normal, uv, loop_ids, vertex_ids, groups, sources


def signature(arrays):
    digest = sha256()
    for a in (*arrays[:5], arrays[6]):
        digest.update(a.tobytes())
    for groups in arrays[5]:
        digest.update(repr(sorted(groups.items())).encode("utf8"))
    return digest.hexdigest()


def bound_material(obj, fallback):
    if obj.data.materials and obj.data.materials[0] is not None:
        return obj.data.materials[0].get("tew1_material_path", fallback)
    return fallback


def import_model(context, filename):
    data = filename.read_bytes()
    model = bmd6.read_model(data)
    base = next((folder for folder in filename.parents if folder.name.lower() == "base"), None)
    collection = bpy.data.collections.new(filename.stem)
    context.collection.children.link(collection)
    rig = make_rig(context, model, filename.stem, collection)
    text = bpy.data.texts.new(filename.name + " · BMD6 template")
    text.from_string(base64.encodebytes(data).decode("ascii"))
    text.use_fake_user = True
    rig[TEMPLATE] = text.name
    if base is not None:
        relative = filename.relative_to(base).as_posix()
        if relative.startswith("generated/nextgen/"):
            rig["tew1_overlay_asset"] = relative
    elif re.fullmatch(r"(?:pl|em)[0-9]{4}(?:_[a-z]+)?", filename.stem):
        rig["tew1_overlay_asset"] = build.relative_asset(filename.stem)
    materials = {}
    for slot, surface in enumerate(model.surfaces):
        obj = make_mesh(surface, collection, rig, model.skeleton, slot, base, materials)
        if obj is not None:
            context.view_layer.update()
            obj[SIGNATURE] = signature(gather_mesh(obj, rig))
    rig.show_in_front = True
    context.view_layer.objects.active = rig
    return rig


def export_surface(obj, rig, original, skeleton, continuous):
    if obj.get("tew1_zero_hide"):
        return replace(original, indices=np.zeros((1, 3), dtype=">u2"))
    arrays = gather_mesh(obj, rig)
    material = bound_material(obj, original.material)
    if obj.get(SIGNATURE) == signature(arrays):
        return original if material == original.material else replace(original, material=material)
    points, normals, uv, faces, vertex_ids, groups, sources = arrays
    src = np.frombuffer(original.vertices, "u1").reshape(-1, 32)
    src_groups = [{name: round(float(weight), 7) for name, weight in g.items()} for g in skin_weights(src, skeleton)]
    src_wire = src[:, [23, 28, 29, 30, 31]]
    raw_weights = []
    for index in np.unique(vertex_ids[faces]):
        incoming = int(sources[index])
        stored = (src_groups[incoming], src_wire[incoming]) if 0 <= incoming < len(src) else None
        raw_weights.append(encode_weights(groups[index], skeleton, stored))
    used_vertices = np.unique(vertex_ids[faces])
    rows = np.zeros((len(points), 5), dtype="u1")
    rows[used_vertices] = raw_weights
    loops = faces.ravel()
    loop_keys = np.column_stack((vertex_ids[loops], uv[loops], normals[loops]))
    unique, indices = np.unique(loop_keys, axis=0, return_inverse=True)
    mapping = unique[:, 0].astype(np.intp)
    stream, triangles, _ = build.mesh_stream(
        points[mapping], unique[:, 3:], unique[:, 1:3], indices.reshape(-1, 3), rows[mapping],
        continuous_tangents=continuous,
    )
    return replace(original, material=material, vertices=stream, indices=triangles)


def active_rig(context):
    obj = context.view_layer.objects.active
    if obj is None:
        return None
    if obj.type == "ARMATURE" and TEMPLATE in obj:
        return obj
    if obj.parent and obj.parent.type == "ARMATURE" and TEMPLATE in obj.parent:
        return obj.parent
    return None


def export_model(filename, rig, continuous):
    raw = template_bytes(rig)
    model = bmd6.read_model(raw)
    surfaces = list(model.surfaces)
    selected = {}
    appends = []
    for obj in rig.children:
        if obj.type == "MESH" and SLOT in obj:
            slot = int(obj[SLOT])
            if slot == -1:
                aname = str(obj.get("tew1_append_surface_name", "")).strip()
                if not aname:
                    raise ValueError(f"追加网格 {obj.name} 缺少 tew1_append_surface_name。")
                appends.append((aname, obj))
                continue
            if slot in selected or not 0 <= slot < len(surfaces):
                raise ValueError(f'重复或无效的 BMD6 槽号 {slot}。')
            selected[slot] = obj
    for slot, obj in selected.items():
        surfaces[slot] = export_surface(obj, rig, surfaces[slot], model.skeleton, continuous)
    if appends:
        # Place sheer outerwear surfaces last so body/legs/innerwear always render before semi-transparent cloth
        def _is_sheer(pair):
            _aname, o = pair
            if o.data.materials and o.data.materials[0] is not None:
                return bool(o.data.materials[0].get("tew1_sheer_outer", False))
            return False

        appends.sort(key=lambda pair: (1 if _is_sheer(pair) else 0))
        template_surf = next((s for s in model.surfaces if s.name == "m_face"), model.surfaces[0])
        for aname, obj in appends:
            seed = replace(template_surf, name=aname)
            surfaces.append(export_surface(obj, rig, seed, model.skeleton, continuous))
    if len(surfaces) > 31:
        raise ValueError(f"导出总表面数 ({len(surfaces)}) 超过 TEW1 安全上限 31，请减少追加槽位。")
    if len(surfaces) == len(model.surfaces) and all(
        before is after for before, after in zip(model.surfaces, surfaces, strict=True)
    ):
        output = raw
    else:
        output = bmd6.write_model(model, surfaces)
        result = bmd6.read_model(output)
        if result.prefix != model.prefix or len(result.surfaces) != len(surfaces):
            raise ValueError("导出后的原生骨架或网格槽校验失败。")
    temporary = None
    try:
        with NamedTemporaryFile(dir=filename.parent, suffix=".bmd6model", delete=False) as file:
            temporary = Path(file.name)
            file.write(output)
        temporary.replace(filename)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class TEW1Import(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.tew1_bmd6"
    bl_label = "导入恶灵附身 BMD6"
    bl_description = "导入恶灵附身 1 原版或 Mod 的 .bmd6model 角色模型，同时在骨架内保存原生模板供后续换骨、断肢与无损导出使用"
    filename_ext = ".bmd6model"
    filter_glob: StringProperty(default="*.bmd6model", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context):
        try:
            import_model(context, Path(self.filepath))
        except (ValueError, OSError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class TEW1Export(bpy.types.Operator, ExportHelper):
    bl_idname = "export_scene.tew1_bmd6"
    bl_label = "另存为恶灵附身 BMD6"
    bl_description = "将当前选中的 TEW1 模板骨架及其所有已分配槽位的子网格另存为任意位置的 .bmd6model 文件"
    filename_ext = ".bmd6model"
    filter_glob: StringProperty(default="*.bmd6model", options={"HIDDEN"})

    continuous_tangents: BoolProperty(
        name="连续切线",
        description="开启后生成平滑连续切线，适用于二次元或无重法线贴图角色；需要严格按 UV 切线渲染法线贴图时可关闭",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and active_rig(context) is not None

    def execute(self, context):
        try:
            export_model(Path(self.filepath), active_rig(context), self.continuous_tangents)
        except (ValueError, OSError, RuntimeError, np.linalg.LinAlgError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


class TEW1ReplaceSlot(bpy.types.Operator):
    bl_idname = "object.tew1_replace_slot"
    bl_label = "按编号替换 TEW1 网格槽"
    bl_description = "按数字槽位号替换原版模板网格（推荐改用面板中的「指派/追加 网格与断肢槽位」，可直观看到每个槽位的安全提示）"
    bl_options = {"REGISTER", "UNDO"}

    slot: IntProperty(name="网格槽编号", min=0, description="目标模板表面槽位序号（从 0 开始）")

    @classmethod
    def poll(cls, context):
        return active_rig(context) is not None and any(
            obj.type == "MESH" and SLOT not in obj for obj in context.selected_objects)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        rig = active_rig(context)
        meshes = [obj for obj in context.selected_objects if obj.type == "MESH" and SLOT not in obj]
        slots = bmd6.read_model(template_bytes(rig)).surfaces
        if len(meshes) != 1 or self.slot >= len(slots):
            self.report({"ERROR"}, "请选择一个新网格和导入的骨架，并填写有效网格槽号。")
            return {"CANCELLED"}
        obj = meshes[0]
        for child in list(rig.children):
            if child.get(SLOT) == self.slot:
                del child[SLOT]
                child.hide_set(True)
        matrix = obj.matrix_world.copy()
        obj.parent = rig
        obj.matrix_world = matrix
        obj[SLOT] = self.slot
        self.report({"INFO"}, "已替换 " + slots[self.slot].name)
        return {"FINISHED"}


def import_menu(self, _context):
    self.layout.operator(TEW1Import.bl_idname, text="恶灵附身 BMD6 (.bmd6model)")


def export_menu(self, _context):
    self.layout.operator(TEW1Export.bl_idname, text="恶灵附身 BMD6 (.bmd6model)")


CLASSES = (TEW1Import, TEW1Export, TEW1ReplaceSlot)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(import_menu)
    bpy.types.TOPBAR_MT_file_export.append(export_menu)
    from . import dismember, dyn_export, facial_author, hair_author, rig_tools, tango_extract, tex_encode, ui_panels, workflow
    tango_extract.register()
    dismember.register()
    rig_tools.register()
    tex_encode.register()
    workflow.register()
    hair_author.register()
    facial_author.register()
    dyn_export.register()
    ui_panels.register()


def unregister():
    from . import dismember, dyn_export, facial_author, hair_author, rig_tools, tango_extract, tex_encode, ui_panels, workflow
    ui_panels.unregister()
    dyn_export.unregister()
    facial_author.unregister()
    hair_author.unregister()
    workflow.unregister()
    tex_encode.unregister()
    rig_tools.unregister()
    dismember.unregister()
    tango_extract.unregister()
    bpy.types.TOPBAR_MT_file_export.remove(export_menu)
    bpy.types.TOPBAR_MT_file_import.remove(import_menu)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
