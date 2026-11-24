"""TEW1 workspace properties, overlay export, 1-click PNG/DDS material generator & ModToolkit presets."""

from pathlib import Path, PurePosixPath

import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty, StringProperty

from .presets import PRESETS, export_toolkit_presets


def loose_root(value):
    if not value.strip():
        raise ValueError("请先在面板中选择外部 Mod 挂载目录。")
    path = Path(bpy.path.abspath(value)).resolve()
    if any((parent / "EvilWithin.exe").exists() for parent in (path, *path.parents)):
        raise ValueError("请选择游戏目录以外的路径（严禁直接写入游戏本体目录）。")
    return path


class TEW1Workspace(bpy.types.PropertyGroup):
    overlay: StringProperty(
        name="挂载目录",
        subtype="DIR_PATH",
        description="Mod 外部挂载输出目录（会自动建立 base/generated/...），请务必选择游戏本体目录以外的文件夹",
    )
    continuous_tangents: BoolProperty(
        name="连续切线",
        description="开启后生成平滑连续切线，适用于二次元或平滑角色着色；需要严格按 UV 切线显示法线贴图时可关闭",
        default=True,
    )
    batch_mat_prefix: StringProperty(
        name="角色材质前缀名",
        default="tew_custom",
        description="一键批量转换全部材质时的文件夹名（仅小写英文/数字/下划线，例如 tew_haruka，将输出 textures/tew_haruka/mat_00..）",
    )
    key: StringProperty(
        name="单材质游戏路径",
        default="textures/tew_author/outfit",
        description="单个材质的游戏内路径，形如 textures/作者名/材质名（仅小写英文字母、数字、下划线、斜杠）",
    )
    albedo: StringProperty(
        name="底色贴图 (PNG/TGA/JPG/DDS)",
        subtype="FILE_PATH",
        description="支持直接选择 PNG / TGA / JPG / DDS；留空时会自动读取当前 Blender 材质节点中已连接的底色贴图！",
    )
    preset: EnumProperty(
        name="着色预设",
        items=[
            ("OPAQUE", "衣服和皮肤 (OPAQUE)", "不透明漫反射前向着色（BC1/DXT1），适用于皮肤、衣服、金属等常规材质"),
            ("HAIR",   "不透明发片 (HAIR)",   "前向发片着色（BC1/DXT1），适用于常规实体头发"),
            ("CUTOUT", "透明裁切 (CUTOUT)",   "带 Alpha 裁切前向着色（BC3/DXT5），适用于睫毛、蕾丝、透明发梢等镂空材质"),
        ],
        description="选择 TEW1 前向着色器类型（自动绕过原版 Megatexture，兼容游戏光照与 F7/F8/F9 自发光）",
    )
    toolkit_folder: StringProperty(
        name="外部 ModToolkit 预设目录",
        subtype="DIR_PATH",
        description="如果你仍想给外部 ModToolkit 插件使用塞巴斯蒂安预设，选其 presets 目录即可导出（本插件现已内置一键对骨，通常无需导出）",
    )
    # Mod ZIP metadata
    mod_name: StringProperty(
        name="Mod 名称",
        default="My TEW1 Character Mod",
        description="显示在 TEW1ModManager 管理器列表中的 Mod 标题",
    )
    mod_author: StringProperty(
        name="作者",
        default="Author",
        description="写入 mod.info 的作者署名",
    )
    mod_version: StringProperty(
        name="版本",
        default="1.0",
        description="写入 mod.info 的版本号（如 1.0）",
    )
    mod_desc: StringProperty(
        name="简介",
        default="含自定义模型与 TEW Physical 实时物理",
        description="显示在管理器中的 Mod 简介说明",
    )


class TEW1WriteMaterial(bpy.types.Operator):
    bl_idname = "material.tew1_write"
    bl_label = "生成单材质 .decl + .bimage 并绑定"
    bl_description = "将所选 PNG/TGA/JPG/DDS 贴图（留空则自动读取当前材质节点贴图）编码为游戏 .bimage 并生成前向 .decl 写入挂载目录，同时绑定到当前活动材质"

    @classmethod
    def poll(cls, context):
        return bool(context.object and context.object.type == "MESH" and context.object.active_material)

    def execute(self, context):
        from .tex_encode import export_material_any_source, find_material_albedo_image
        settings = context.scene.tew1_workspace
        try:
            if context.object.active_material_index != 0:
                raise ValueError("请先把游戏材质放在网格的第一个材质槽（槽 0）。")
            mat = context.object.active_material
            if settings.albedo.strip():
                source = Path(bpy.path.abspath(settings.albedo)).resolve(strict=True)
            else:
                source = find_material_albedo_image(mat)
                if source is None:
                    raise ValueError("底色贴图路径为空，且当前材质节点中未找到图片节点，请指定 PNG/TGA/JPG/DDS 文件。")
            key = export_material_any_source(loose_root(settings.overlay), settings.key, source, settings.preset)
            mat["tew1_material_path"] = key
        except (OSError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, "已生成并绑定材质: " + key)
        return {"FINISHED"}


class TEW1ApplyMaterialPath(bpy.types.Operator):
    bl_idname = "material.tew1_apply_path"
    bl_label = "仅写入路径到当前材质 (不重转贴图)"
    bl_description = "仅将上方「单材质游戏路径」写入当前活动材质的 tew1_material_path 属性（用于多个网格共用同一套已生成材质）"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(context.object and context.object.type == "MESH" and context.object.active_material)

    def execute(self, context):
        settings = context.scene.tew1_workspace
        val = settings.key.strip()
        if not val:
            self.report({"ERROR"}, "材质路径不能为空。")
            return {"CANCELLED"}
        context.object.active_material["tew1_material_path"] = val
        self.report({"INFO"}, f"已绑定 {context.object.active_material.name} -> {val}")
        return {"FINISHED"}


class TEW1WriteOverlayModel(bpy.types.Operator):
    bl_idname = "export_scene.tew1_overlay_model"
    bl_label = "导出 BMD6 到挂载目录"
    bl_description = "按模板记录的游戏内原生路径（如 pl0000_ng.bmd6model）直接导出到挂载目录 base/generated/..."

    @classmethod
    def poll(cls, context):
        from . import active_rig
        rig = active_rig(context)
        return bool(context.mode == "OBJECT" and rig and rig.get("tew1_overlay_asset"))

    def execute(self, context):
        from . import active_rig, export_model
        settings = context.scene.tew1_workspace
        rig = active_rig(context)
        try:
            root = loose_root(settings.overlay)
            key = PurePosixPath(rig["tew1_overlay_asset"])
            if key.is_absolute() or ".." in key.parts or not key.as_posix().startswith("generated/nextgen/"):
                raise ValueError("模板没有可用的游戏内资源路径。")
            path = (root / "base" / key).resolve()
            if not path.is_relative_to(root) or path.suffix != ".bmd6model":
                raise ValueError("BMD6 输出路径无效。")
            path.parent.mkdir(parents=True, exist_ok=True)
            export_model(path, rig, settings.continuous_tangents)
        except (OSError, ValueError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, "已按原生路径导出 " + path.name)
        return {"FINISHED"}


class TEW1WriteToolkitPreset(bpy.types.Operator):
    bl_idname = "object.tew1_write_toolkit_presets"
    bl_label = "导出外部 ModToolkit 骨骼预设"
    bl_description = "为外部 ModToolkit 插件导出塞巴斯蒂安源/目标骨骼预设文件 TEW1_Sebastian.json（可选，本插件现已内置 MMD/VRChat 一键对骨）"

    def execute(self, context):
        value = context.scene.tew1_workspace.toolkit_folder
        if not value.strip():
            self.report({"ERROR"}, "请选择预设输出目录。")
            return {"CANCELLED"}
        try:
            export_toolkit_presets(Path(bpy.path.abspath(value)).resolve())
        except OSError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, "已导出 TEW1_Sebastian.json（源骨架与目标骨架预设）。")
        return {"FINISHED"}


class TEW1ToggleRigDisplay(bpy.types.Operator):
    bl_idname = "object.tew1_toggle_rig_display"
    bl_label = "切换骨架显示方式"
    bl_description = "一键切换当前骨架的「在最前透视显示 (In Front)」或「显示骨骼名称」，方便查看对骨与物理发骨"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(
        items=[
            ("IN_FRONT", "透视", "切换骨架在模型前方透视显示"),
            ("NAMES",    "名称", "切换在 3D 视口中显示每根骨骼的名称"),
        ],
        default="IN_FRONT",
    )

    @classmethod
    def poll(cls, context):
        from .hair_author import rig_object
        return rig_object(context) is not None

    def execute(self, context):
        from .hair_author import rig_object
        rig = rig_object(context)
        if self.mode == "IN_FRONT":
            rig.show_in_front = not rig.show_in_front
        else:
            rig.data.show_names = not rig.data.show_names
        return {"FINISHED"}


CLASSES = (
    TEW1Workspace,
    TEW1WriteMaterial,
    TEW1ApplyMaterialPath,
    TEW1WriteOverlayModel,
    TEW1WriteToolkitPreset,
    TEW1ToggleRigDisplay,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.tew1_workspace = PointerProperty(type=TEW1Workspace)


def unregister():
    del bpy.types.Scene.tew1_workspace
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
