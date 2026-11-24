"""RE-Mesh-Editor-inspired Blender UI panels for TEW1 modding (Blender 4.0 - 5.2+):
- N-Panel Tab 1: 'TEW Mesh' (1. IO -> 2. MMD/VRChat 1-Click Rigging -> 3. 1-Click Materials -> 4. Dismemberment -> 5. Pack ZIP)
- N-Panel Tab 2: 'TEW Physical' (1. Overview -> 2. Chains -> 3. Visual 5-Slot Colliders -> 4. Bake/Emissive -> 5. TEW Facial & CG Mouth -> 6. Export v2)
- Properties > Material: 'TEW1 材质属性 (TEW Mat)'
"""

import bpy
from bpy.props import IntProperty

from . import bmd6
from .dismember import (
    APPEND_NAME,
    EXCLUDE_EMISSIVE,
    MAX_SAFE_SURFACES,
    SLOT,
    ZERO_HIDE,
    count_exported_surfaces,
    slot_role_tag,
)
from .dyn_export import COLLIDER_BONES, scan_rig_shape_keys
from .facial_author import CORE_FACIAL_SLOTS, read_facial_map
from .hair_author import (
    HELPER,
    MAX_RUNTIME_CHAINS,
    MAX_RUNTIME_COLLIDERS,
    PREVIEW,
    profile as hair_profile,
    rig_object,
)


class TEW1SelectChainRow(bpy.types.Operator):
    bl_idname = "tew1.select_chain_row"
    bl_label = "选择物理链条目"
    bl_description = "点击选中该物理骨骼链，并将其刚度、阻尼、重力与半径加载到下方参数区供调整"
    bl_options = {"INTERNAL"}

    index: IntProperty(default=0)

    def execute(self, context):
        context.scene.tew1_hair.active_chain_index = self.index
        return {"FINISHED"}


class TEW1SelectColliderRow(bpy.types.Operator):
    bl_idname = "tew1.select_collider_row"
    bl_label = "选择碰撞体条目"
    bl_description = "点击选中该胶囊碰撞体，并将其绑定骨骼、端点坐标与半径加载到下方参数区"
    bl_options = {"INTERNAL"}

    index: IntProperty(default=0)

    def execute(self, context):
        context.scene.tew1_hair.active_collider_index = self.index
        return {"FINISHED"}


def _template_surface_info(rig):
    from . import TEMPLATE, template_bytes
    if rig is None or TEMPLATE not in rig:
        return None, 0
    try:
        model = bmd6.read_model(template_bytes(rig))
        return model, count_exported_surfaces(rig, model)
    except Exception:
        return None, 0


# ============================================================================
# TAB 1: TEW Mesh (modeled after NSACloud/RE-Mesh-Editor consolidated layout)
# ============================================================================

class VIEW3D_PT_tew1_io(bpy.types.Panel):
    bl_idname = "VIEW3D_PT_tew1_io"
    bl_label = "1. 导入导出 & 挂载区"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "TEW Mesh"

    def draw(self, context):
        from . import active_rig
        layout = self.layout
        ws = context.scene.tew1_workspace
        rig = active_rig(context)

        # Quick Import / Export row (RE-Mesh-Editor signature 2-col header)
        row = layout.row(align=True)
        row.scale_y = 1.25
        row.operator("import_scene.tew1_bmd6", text="导入 BMD6", icon="IMPORT")
        row.operator("export_scene.tew1_bmd6", text="另存 BMD6", icon="EXPORT")

        # Workspace / Overlay Box
        box = layout.box()
        box.label(text="Mod 外部挂载目录（切勿选游戏本体目录）", icon="FILE_FOLDER")
        box.prop(ws, "overlay", text="")
        box.prop(ws, "continuous_tangents")

        # Active Rig Status Banner
        status = layout.box()
        if rig is None:
            status.label(text="未选中带 BMD6 模板的骨架", icon="INFO")
            status.label(text="先点上方「导入 BMD6」载入 pl0000_ng")
        else:
            model, total_surfs = _template_surface_info(rig)
            asset = rig.get("tew1_overlay_asset", "（未记录原生路径）")
            status.label(text=f"活动模板骨架: {rig.name}", icon="OUTLINER_OB_ARMATURE")
            col = status.column(align=True)
            col.scale_y = 0.85
            col.label(text=f"目标资源: {asset.rsplit('/', 1)[-1]}")
            if model is not None:
                over = total_surfs > MAX_SAFE_SURFACES
                icon = "ERROR" if over else "CHECKMARK"
                col.label(text=f"导出表面数: {total_surfs} / {MAX_SAFE_SURFACES}", icon=icon)

            actions = layout.column(align=True)
            actions.scale_y = 1.15
            actions.operator("export_scene.tew1_overlay_model", text="导出 BMD6 到挂载目录", icon="EXPORT")
            actions.operator("export_scene.tew1_sync_export_all", text="一键同步导出 BMD6 + 物理表情包", icon="FILE_REFRESH")


class VIEW3D_PT_tew1_rig_tools(bpy.types.Panel):
    bl_idname = "VIEW3D_PT_tew1_rig_tools"
    bl_label = "2. 一键对骨、重命名与换骨 (MMD/VRChat)"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "TEW Mesh"

    def draw(self, context):
        layout = self.layout
        rt = context.scene.tew1_rig_tools
        ws = context.scene.tew1_workspace

        box = layout.box()
        box.label(text="内置 ModToolkit 预设：MMD & VRChat", icon="ARMATURE_DATA")
        box.prop(rt, "source_rig")
        box.prop(rt, "target_rig")
        box.prop(rt, "source_preset")

        opts = box.column(align=True)
        opts.prop(rt, "align_limb_pose")
        opts.prop(rt, "merge_aux_weights")
        opts.prop(rt, "migrate_to_tew_rig")

        main = layout.column(align=True)
        main.scale_y = 1.25
        main.operator("object.tew1_oneclick_align_and_bind", text="一键对骨、重命名并绑定到 TEW1 骨架", icon="CHECKMARK")

        sub = layout.box()
        sub.label(text="分步微调工具（可选）", icon="TOOL_SETTINGS")
        col = sub.column(align=True)
        col.operator("object.tew1_mmd_a_to_tpose", text="MMD A-Pose 一键转 T-Pose（保留形态键）", icon="OUTLINER_OB_ARMATURE")
        col.operator("object.tew1_rename_bones_preset", text="仅执行一键骨骼重命名 + 合并辅助权重", icon="BONE_DATA")
        col.operator("object.tew1_align_rig_transform", text="仅自动对齐体型缩放与朝向", icon="ORIENTATION_GLOBAL")

        disp = layout.row(align=True)
        op1 = disp.operator("object.tew1_toggle_rig_display", text="透视骨架", icon="ARMATURE_DATA")
        op1.mode = "IN_FRONT"
        op2 = disp.operator("object.tew1_toggle_rig_display", text="骨骼名称", icon="FILE_TEXT")
        op2.mode = "NAMES"

        # Optional external ModToolkit preset export (compact)
        ext = layout.box()
        ext.label(text="（可选）导出外部 ModToolkit 预设", icon="PRESET")
        row = ext.row(align=True)
        row.prop(ws, "toolkit_folder", text="")
        row.operator("object.tew1_write_toolkit_presets", text="导出", icon="EXPORT")


class VIEW3D_PT_tew1_materials(bpy.types.Panel):
    bl_idname = "VIEW3D_PT_tew1_materials"
    bl_label = "3. 材质制作 (一键免转 DDS)"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "TEW Mesh"

    def draw(self, context):
        layout = self.layout
        ws = context.scene.tew1_workspace
        obj = context.object

        # 1-Click Batch Material Conversion (the easiest path!)
        batch = layout.box()
        batch.label(text="推荐：自动读取贴图一键批量生成材质", icon="MATERIAL")
        batch.prop(ws, "batch_mat_prefix")
        btn = batch.row()
        btn.scale_y = 1.2
        btn.operator("material.tew1_batch_convert", text="一键转换角色全部材质 (免转DDS)", icon="SHADING_TEXTURE")

        # Single Material Override (PNG/TGA/JPG/DDS or active node image)
        single = layout.box()
        single.label(text="单材质精细替换（支持 PNG/TGA/JPG/DDS）", icon="TEXTURE")
        if obj and obj.type == "MESH" and obj.active_material:
            mat = obj.active_material
            cur = mat.get("tew1_material_path", "（未绑定）")
            sub = single.row()
            sub.scale_y = 0.85
            sub.label(text=f"当前: {mat.name} → {cur}")
        col = single.column(align=True)
        col.prop(ws, "preset")
        col.prop(ws, "key")
        col.prop(ws, "albedo")
        col.operator("material.tew1_write", text="生成单材质 .decl + .bimage 并绑定", icon="MATERIAL")
        col.operator("material.tew1_apply_path", text="仅写入材质路径 (不重转贴图)", icon="LINKED")


class VIEW3D_PT_tew1_mesh_tools(bpy.types.Panel):
    bl_idname = "VIEW3D_PT_tew1_mesh_tools"
    bl_label = "4. 网格与断肢工具"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "TEW Mesh"

    def draw(self, context):
        from . import active_rig
        layout = self.layout
        rig = active_rig(context)
        obj = context.object

        info = layout.box()
        if obj and obj.type == "MESH":
            slot = obj.get(SLOT, None)
            if slot is None:
                info.label(text=f"{obj.name} · 未绑定槽位", icon="MESH_DATA")
            elif int(slot) == -1:
                aname = obj.get(APPEND_NAME, "?")
                info.label(text=f"{obj.name} · 追加槽 [{aname}]", icon="ADD")
            else:
                sname = f"槽 #{int(slot)}"
                role = ""
                model, _ = _template_surface_info(rig)
                if model and 0 <= int(slot) < len(model.surfaces):
                    sname = model.surfaces[int(slot)].name
                    role = f" ({slot_role_tag(sname)})"
                hidden = " [已安全隐藏]" if obj.get(ZERO_HIDE) else ""
                info.label(text=f"[{int(slot):02d}] {sname}{hidden}", icon="MESH_DATA")
                if role:
                    sub = info.row()
                    sub.scale_y = 0.8
                    sub.label(text=role)
        else:
            info.label(text="选中任意网格以查看/分配槽位", icon="INFO")

        col = layout.column(align=True)
        col.operator("object.tew1_assign_slot", text="指派/追加 网格与断肢槽位...", icon="MESH_DATA")
        col.operator("object.tew1_split_body_dismember", text="一键按权重拆分身体断肢 (4部位)", icon="MOD_EXPLODE")
        col.operator("object.tew1_safe_hide_slot", text="切换原版槽「安全清零隐藏」", icon="HIDE_ON")

        layout.separator(factor=0.5)
        clean = layout.column(align=True)
        clean.label(text="权重规范化与导出体检", icon="TOOL_SETTINGS")
        op = clean.operator("object.tew1_normalize_weights", text="规范化权重 (上限4骨骼，保留物理骨)", icon="GROUP_VERTEX")
        op.remove_non_native = False
        op2 = clean.operator("object.tew1_normalize_weights", text="清理多余组并规范化 (不含物理骨)", icon="GROUP_VERTEX")
        op2.remove_non_native = True
        clean.operator("object.tew1_validate_model", text="导出前全面体检 (<=31表面/断头检查)", icon="CHECKMARK")


class VIEW3D_PT_tew1_package(bpy.types.Panel):
    bl_idname = "VIEW3D_PT_tew1_package"
    bl_label = "5. 一键打包 Mod ZIP"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "TEW Mesh"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        ws = context.scene.tew1_workspace
        col = layout.column(align=True)
        col.prop(ws, "mod_name")
        col.prop(ws, "mod_author")
        col.prop(ws, "mod_version")
        col.prop(ws, "mod_desc")
        btn = layout.row()
        btn.scale_y = 1.2
        btn.operator("export_scene.tew1_pack_mod_zip", text="导出可导入管理器的 Mod ZIP", icon="EXPORT")


# ============================================================================
# TAB 2: TEW Physical (Step-by-Step TEW1 Physics & Facial Workflow)
# ============================================================================

class VIEW3D_PT_tew1_phys_overview(bpy.types.Panel):
    bl_idname = "VIEW3D_PT_tew1_phys_overview"
    bl_label = "1. 物理总览与一键识链"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "TEW Physical"

    def draw(self, context):
        layout = self.layout
        rig = rig_object(context)
        state = context.scene.tew1_hair

        if rig is None:
            box = layout.box()
            box.label(text="请先在视口选中 TEW1 角色骨架或其子网格", icon="INFO")
            return

        data = hair_profile(rig)
        n_chains = len(data["chains"])
        n_bones = sum(len(c["bones"]) for c in data["chains"])
        n_cols = len(data["colliders"])
        has_head = "head" in rig.data.bones
        col_ok = sum(1 for b in COLLIDER_BONES if b in rig.data.bones)

        box = layout.box()
        box.label(text=f"当前骨架: {rig.name}", icon="PHYSICS")
        col = box.column(align=True)
        col.scale_y = 0.85
        col.label(text=f"原生 head 骨骼: {'正常' if has_head else '缺失!'} · 碰撞槽骨骼 {col_ok}/5",
                  icon="CHECKMARK" if has_head else "ERROR")
        col.label(text=f"物理骨骼链: {n_chains}/{MAX_RUNTIME_CHAINS} 条（共 {n_bones} 节骨骼）")
        col.label(text=f"胶囊碰撞体: {n_cols}/{MAX_RUNTIME_COLLIDERS} 个")

        auto = layout.box()
        auto.label(text="快速开始：自动扫描发骨/飘带/裙摆链", icon="BONE_DATA")
        auto.prop(state, "physics_preset", text="默认风格")
        auto.prop(state, "autodetect_keywords", text="关键词")
        btn = auto.row()
        btn.scale_y = 1.15
        btn.operator("pose.tew1_autodetect_chains", text="一键自动识别物理骨骼链", icon="BONE_DATA")


class VIEW3D_PT_tew1_phys_chains(bpy.types.Panel):
    bl_idname = "VIEW3D_PT_tew1_phys_chains"
    bl_label = "2. 物理骨骼链 (发束 / 飘带 / 衣摆)"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "TEW Physical"

    def draw(self, context):
        layout = self.layout
        rig = rig_object(context)
        if rig is None:
            layout.label(text="未选中骨架", icon="INFO")
            return

        state = context.scene.tew1_hair
        chains = hair_profile(rig)["chains"]

        lst = layout.box()
        head_row = lst.row(align=True)
        head_row.label(text=f"已配置物理链 ({len(chains)}/{MAX_RUNTIME_CHAINS})", icon="MOD_CLOTH")
        if chains:
            clr = head_row.operator("object.tew1_remove_hair_item", text="", icon="TRASH")
            clr.kind = "chains"
            clr.clear_all = True

        if not chains:
            lst.label(text="点上方「一键自动识别」或在姿态模式选中骨骼添加", icon="INFO")
        else:
            list_col = lst.column(align=True)
            for idx, ch in enumerate(chains):
                row = list_col.row(align=True)
                is_active = (idx == state.active_chain_index)
                label = f"{ch['name']} ({len(ch['bones'])}节)  K={ch['stiffness']:.0f} D={ch['damping']:.2f}"
                sel = row.operator("tew1.select_chain_row", text=label, depress=is_active)
                sel.index = idx
                pick = row.operator("pose.tew1_select_chain_bones", text="", icon="RESTRICT_SELECT_OFF")
                pick.chain_index = idx

        ed = layout.box()
        ed.label(text="物理参数调节（鼠标悬停可看说明）", icon="TOOL_SETTINGS")
        ed.prop(state, "physics_preset", text="风格预设")
        grid = ed.column(align=True)
        grid.prop(state, "stiffness")
        grid.prop(state, "damping")
        grid.prop(state, "gravity")
        grid.prop(state, "strand_radius")

        act = layout.column(align=True)
        act.operator("pose.tew1_mark_hair", text="从姿态模式选中骨骼添加/更新链", icon="ADD")
        if chains:
            row = act.row(align=True)
            op_one = row.operator("object.tew1_apply_chain_params", text="应用到当前链")
            op_one.apply_all = False
            op_all = row.operator("object.tew1_apply_chain_params", text="应用到全部链")
            op_all.apply_all = True
            rm = act.operator("object.tew1_remove_hair_item", text="移除当前选中链", icon="TRASH")
            rm.kind = "chains"
            rm.clear_all = False


class VIEW3D_PT_tew1_phys_colliders(bpy.types.Panel):
    bl_idname = "VIEW3D_PT_tew1_phys_colliders"
    bl_label = "3. 胶囊碰撞体 (5槽位可视化)"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "TEW Physical"

    def draw(self, context):
        layout = self.layout
        rig = rig_object(context)
        if rig is None:
            layout.label(text="未选中骨架", icon="INFO")
            return

        state = context.scene.tew1_hair
        cols = hair_profile(rig)["colliders"]
        has_gizmos = any(c.get(HELPER) for c in rig.children)

        top = layout.column(align=True)
        top.scale_y = 1.15
        top.operator("object.tew1_create_default_colliders", text="一键生成默认人形 5 碰撞体", icon="MESH_UVSPHERE")
        row = top.row(align=True)
        row.operator("object.tew1_toggle_collider_gizmos",
                     text="隐藏视口球体" if has_gizmos else "显示视口球体",
                     icon="HIDE_OFF" if has_gizmos else "HIDE_ON")
        row.operator("object.tew1_sync_colliders_from_scene", text="从视口同步回数据", icon="FILE_REFRESH")
        layout.prop(state, "gizmos_selectable")

        lst = layout.box()
        lst.label(text=f"碰撞体列表 ({len(cols)}/{MAX_RUNTIME_COLLIDERS}) · 支持 head/neck/spine/左右肩", icon="MESH_UVSPHERE")
        if not cols:
            lst.label(text="点上方按钮一键生成，然后在视口拖拽球体即可", icon="INFO")
        else:
            col_ui = lst.column(align=True)
            for idx, c in enumerate(cols):
                row = col_ui.row(align=True)
                is_active = (idx == state.active_collider_index)
                lbl = f"{c['name']} [{c['bone']}]  R={c['radius']:.2f}"
                op = row.operator("tew1.select_collider_row", text=lbl, depress=is_active)
                op.index = idx

        ed = layout.box()
        ed.prop(state, "label")
        ed.prop_search(state, "bone", rig.data, "bones")
        ed.prop(state, "start")
        ed.prop(state, "end")
        ed.prop(state, "capsule_radius")
        row = ed.row(align=True)
        row.operator("object.tew1_mark_collider", text="保存/更新碰撞体", icon="CHECKMARK")
        if cols:
            rm = row.operator("object.tew1_remove_hair_item", text="移除", icon="TRASH")
            rm.kind = "colliders"
            rm.clear_all = False


class VIEW3D_PT_tew1_phys_preview(bpy.types.Panel):
    bl_idname = "VIEW3D_PT_tew1_phys_preview"
    bl_label = "4. 视口预览烘焙 & 自发光标记"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "TEW Physical"

    def draw(self, context):
        layout = self.layout
        rig = rig_object(context)
        state = context.scene.tew1_hair

        bake_box = layout.box()
        bake_box.label(text="Blender 时间轴预览（不开游戏直看物理）", icon="PLAY")
        row = bake_box.row(align=True)
        row.operator("object.tew1_bake_hair", text="烘焙物理预览", icon="PLAY")
        has_baked = bool(rig and rig.animation_data and rig.animation_data.action and rig.animation_data.action.get(PREVIEW))
        if has_baked:
            row.operator("object.tew1_restore_hair_action", text="恢复原动作", icon="LOOP_BACK")

        em_box = layout.box()
        em_box.label(text="游戏内三档角色自发光 (F7 / F8 / F9)", icon="LIGHT")
        em_box.prop(state, "auto_include_emissive")
        obj = context.object
        if obj and obj.type == "MESH":
            excluded = bool(obj.get(EXCLUDE_EMISSIVE, False))
            em_box.operator(
                "object.tew1_toggle_mesh_emissive",
                text=f"当前网格 ({obj.name}): {'已排除自发光' if excluded else '已纳入自发光'}",
                icon="HIDE_ON" if excluded else "CHECKMARK",
            )


class VIEW3D_PT_tew1_phys_facial(bpy.types.Panel):
    bl_idname = "VIEW3D_PT_tew1_phys_facial"
    bl_label = "5. 物理表情与 CG 嘴骨 (TEW Facial)"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "TEW Physical"

    def draw(self, context):
        layout = self.layout
        rig = rig_object(context)
        obj = context.object
        fst = context.scene.tew1_facial

        # Rig-wide summary
        if rig is not None:
            matched = scan_rig_shape_keys(rig)
            top = layout.box()
            top.label(text=f"角色已识别形态键通道: {len(matched)} / 15", icon="SHAPEKEY_DATA")

        if not (obj and obj.type == "MESH"):
            layout.label(text="选中面部网格以绑定表情形态键与生成 CG 嘴骨", icon="INFO")
            return

        # Auto-detect & starter keys
        act = layout.column(align=True)
        act.operator("object.tew1_autodetect_facial_keys", text="一键自动匹配 MMD/VRChat 形态键", icon="SHAPEKEY_DATA")
        act.operator("object.tew1_create_starter_shapekeys", text="无形态键？一键新建空白核心形态键", icon="ADD")

        # Core 5 searchable dropdowns
        if obj.data.shape_keys:
            kbs = obj.data.shape_keys
            slots = layout.box()
            slots.label(text=f"当前面片: {obj.name}（下拉自由指定）", icon="MESH_DATA")
            for _ch, prop_name, label, _tip in CORE_FACIAL_SLOTS:
                slots.prop_search(fst, prop_name, kbs, "key_blocks", text=label)

            # 4-button real-time in-game expression preview
            prev = layout.box()
            prev.label(text="视口实时预览游戏内表情（防穿模检查）", icon="HIDE_OFF")
            row1 = prev.row(align=True)
            p_idle = row1.operator("object.tew1_preview_facial", text="待机归零")
            p_idle.preset = "IDLE"
            p_blink = row1.operator("object.tew1_preview_facial", text="自然眨眼")
            p_blink.preset = "BLINK"
            row2 = prev.row(align=True)
            p_hurt = row2.operator("object.tew1_preview_facial", text="受击表情")
            p_hurt.preset = "HURT"
            p_death = row2.operator("object.tew1_preview_facial", text="死亡表情")
            p_death.preset = "DEATH"

            # Native CG mouth jaw weight generator
            cg = layout.box()
            cg.label(text="CG 过场原生骨骼嘴型（让过场说话嘴会动）", icon="BONE_DATA")
            cg.prop(fst, "jaw_strength")
            cg.operator("object.tew1_generate_cg_mouth_weights", text="一键从张嘴形态键生成 CG 嘴骨权重", icon="GROUP_VERTEX")
        else:
            note = layout.box()
            note.label(text=f"{obj.name} 暂无形态键", icon="INFO")
            note.label(text="点上方「新建空白核心形态键」即可开始手作")


class VIEW3D_PT_tew1_phys_export(bpy.types.Panel):
    bl_idname = "VIEW3D_PT_tew1_phys_export"
    bl_label = "6. 校验并导出物理表情包 (v2)"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "TEW Physical"

    def draw(self, context):
        layout = self.layout
        ws = context.scene.tew1_workspace

        layout.prop(ws, "overlay", text="挂载目录")
        col = layout.column(align=True)
        col.operator("object.tew1_validate_physics", text="物理与表情导出前检查", icon="CHECKMARK")
        main = layout.column(align=True)
        main.scale_y = 1.2
        main.operator("export_scene.tew1_sync_export_all", text="一键同步导出 BMD6 + tew1_dyn.bin", icon="FILE_REFRESH")
        main.operator("export_scene.tew1_dyn_pack", text="仅重编译导出 tew1_dyn.bin (v2)", icon="EXPORT")
        main.operator("export_scene.tew1_pack_mod_zip", text="一键打包为 Mod ZIP", icon="FILE_FOLDER")

        layout.separator(factor=0.4)
        io_row = layout.row(align=True)
        io_row.operator("import_scene.tew1_hair_profile", text="导入 JSON 预设", icon="IMPORT")
        io_row.operator("export_scene.tew1_hair_profile", text="导出 JSON 预设", icon="EXPORT")


# ============================================================================
# PROPERTIES > MATERIAL TAB: TEW1 Material Properties (RE MDF style)
# ============================================================================

class MATERIAL_PT_tew1_material(bpy.types.Panel):
    bl_idname = "MATERIAL_PT_tew1_material"
    bl_label = "TEW1 材质属性 (TEW Mat)"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "material"

    @classmethod
    def poll(cls, context):
        return bool(context.material)

    def draw(self, context):
        layout = self.layout
        mat = context.material
        ws = context.scene.tew1_workspace
        cur = mat.get("tew1_material_path", "")
        box = layout.box()
        box.label(text=f"tew1_material_path: {cur or '（未设置）'}",
                  icon="CHECKMARK" if cur else "INFO")
        col = layout.column(align=True)
        col.prop(ws, "preset")
        col.prop(ws, "key")
        col.prop(ws, "albedo")
        col.operator("material.tew1_write", text="生成 .decl + .bimage 并绑定到此材质", icon="MATERIAL")
        col.operator("material.tew1_apply_path", text="仅写入路径到此材质", icon="LINKED")


CLASSES = (
    TEW1SelectChainRow,
    TEW1SelectColliderRow,
    VIEW3D_PT_tew1_io,
    VIEW3D_PT_tew1_rig_tools,
    VIEW3D_PT_tew1_materials,
    VIEW3D_PT_tew1_mesh_tools,
    VIEW3D_PT_tew1_package,
    VIEW3D_PT_tew1_phys_overview,
    VIEW3D_PT_tew1_phys_chains,
    VIEW3D_PT_tew1_phys_colliders,
    VIEW3D_PT_tew1_phys_preview,
    VIEW3D_PT_tew1_phys_facial,
    VIEW3D_PT_tew1_phys_export,
    MATERIAL_PT_tew1_material,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
