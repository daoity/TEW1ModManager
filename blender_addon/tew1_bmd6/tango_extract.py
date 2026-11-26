"""Extract vanilla .bmd6model templates & game resources directly from TEW1 .tangoresource archives."""

from collections import defaultdict
import os
from pathlib import Path
import re
from struct import iter_unpack, unpack
import tempfile
import zlib

import bpy
from bpy.props import EnumProperty
from bpy_extras.io_utils import ExportHelper


# 27 verified campaign / cutscene / severed-limb models for full-chapter Sebastian replacements
SEBASTIAN_CORE_MODELS = (
    "pl0000_ng",  # Main gameplay playable Sebastian
    "pl0001_ng",  # Severed head prop
    "pl0002",     # Severed right arm
    "pl0003",     # Severed left arm
    "pl0004",     # Severed right leg
    "pl0005",     # Severed left leg
    "pl0006",     # Torso/variant stub
    "pl0007",     # Leg-wound stub (hide 100%)
    "pl0008",     # Severed right hand
    "pl0009_ng",
    "pl0010_ng",  # High-detail cutscene head
    "pl0011_ng",  # High-detail cutscene head
    "pl0012_ng",  # Cutscene head
    "pl0016_ng",  # Crushed head prop
    "pl0017_ng",  # Campaign coat/suit variant
    "pl0018_ng",  # Campaign variant
    "pl0020_ng",  # Hospital / ending variant
    "pl0200_ng",
    "pl0201_ng",
    "pl0210_ng",
    "pl0220_ng",
    "pl0220_m",
    "pl0220_l",
    "pl0230_ng",
    "pl0300_ng",
    "pl0301_ng",
    "em5002_ng",
)

PREFERRED_ARCHIVES = (
    "an_emergency_call.tangoresource",
    "a_planted_seed_will_grow.tangoresource",
    "an_evil_within.tangoresource",
    "inner_recesses.tangoresource",
    "reunion.tangoresource",
    "claws_of_the_horde.tangoresource",
    "the_cruelest_intentions.tangoresource",
    "dlc1_chapter1.tangoresource",
    "dlc1_chapter2.tangoresource",
    "dlc2_chapter3.tangoresource",
    "dlc2_chapter4.tangoresource",
)


def is_valid_game_dir(path):
    if not path:
        return False
    p = Path(path)
    return (p / "EvilWithin.exe").is_file() and (p / "base" / "common.tangoresource").is_file()


def _iter_steam_library_game_dirs():
    steam_roots = []
    try:
        import winreg
        for hive, subkey, valname in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        ):
            try:
                with winreg.OpenKey(hive, subkey) as k:
                    val, _ = winreg.QueryValueEx(k, valname)
                    if val:
                        steam_roots.append(Path(val))
            except OSError:
                pass
    except Exception:
        pass
    out = []
    for root in steam_roots:
        out.append(root / "steamapps" / "common" / "TheEvilWithin")
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            try:
                txt = vdf.read_text(encoding="utf-8", errors="ignore")
                for m in re.finditer(r'"path"\s+"([^"]+)"', txt, re.IGNORECASE):
                    lib = Path(m.group(1).replace("\\\\", "\\"))
                    out.append(lib / "steamapps" / "common" / "TheEvilWithin")
            except OSError:
                pass
    return out


def auto_detect_game_dir():
    """Search Steam registry libraries, common Steam / GOG / local directories for EvilWithin.exe."""
    candidates = list(_iter_steam_library_game_dirs())
    # Check workspace parent folders near this addon
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.extend([
            parent,
            parent / "TheEvilWithin",
            parent / "TheEvilWithin" / "TheEvilWithin",
            parent / "The Evil Within",
        ])

    for drive in ("C", "D", "E", "F", "G", "H"):
        candidates.extend([
            Path(f"{drive}:/Program Files (x86)/Steam/steamapps/common/TheEvilWithin"),
            Path(f"{drive}:/SteamLibrary/steamapps/common/TheEvilWithin"),
            Path(f"{drive}:/Steam/steamapps/common/TheEvilWithin"),
            Path(f"{drive}:/Games/TheEvilWithin"),
            Path(f"{drive}:/Games/The Evil Within"),
            Path(f"{drive}:/TheEvilWithin"),
            Path(f"{drive}:/TheEvilWithin/TheEvilWithin"),
        ])

    seen = set()
    for cand in candidates:
        try:
            key = str(cand.resolve()).lower()
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        if is_valid_game_dir(cand):
            return str(cand.resolve())
    return ""


def read_tango_index(archive_path):
    """Parse header & file table from a TEW1 .tangoresource archive without reading payloads."""
    entries = defaultdict(list)
    path = Path(archive_path)
    with path.open("rb") as f:
        if f.read(4) != b"\x23\x94\xab\xcd":
            return entries
        section_count = unpack(">I", f.read(4))[0]
        for _ in range(section_count):
            for _ in range(2):
                f.seek(unpack("<I", f.read(4))[0], 1)
            f.seek(4, 1)
        f.seek(unpack(">I", f.read(4))[0])
        count, _, _, groups, aliases = unpack(">5I", f.read(20))
        f.seek(2 * (groups + aliases), 1)
        str_size, str_num = unpack(">2I", f.read(8))
        names = f.read(str_size).split(b"\0")[:str_num]
        table = f.read(count * 16)
    if len(table) != count * 16:
        return entries
    for key, offset, packed, raw in iter_unpack(">4I", table):
        if key < len(names):
            nm = names[key].decode("utf8", errors="surrogateescape")
            entries[nm].append((offset, packed, raw))
    return entries


def read_tango_entry(archive_path, offset, packed, raw):
    """Extract and raw-deflate decompress a single resource record."""
    with Path(archive_path).open("rb") as f:
        f.seek(offset)
        chunk = f.read(packed)
    if packed != raw:
        inflater = zlib.decompressobj(-15)
        chunk = inflater.decompress(chunk) + inflater.flush()
    if len(chunk) != raw:
        raise ValueError(f"资源解压长度异常: 期望 {raw}，实际 {len(chunk)}")
    return chunk


def iter_game_archives(game_dir):
    base_dir = Path(game_dir) / "base"
    if not base_dir.is_dir():
        raise ValueError("游戏目录中找不到 base/ 文件夹。")
    by_name = {p.name.lower(): p for p in base_dir.glob("*.tangoresource")}
    ordered = []
    for pref in PREFERRED_ARCHIVES:
        if pref in by_name:
            ordered.append(by_name.pop(pref))
    ordered.extend(sorted(by_name.values(), key=lambda p: p.name.lower()))
    if not ordered:
        raise ValueError("base/ 目录中没有找到任何 .tangoresource 游戏资源包。")
    return ordered


def extract_single_bmd6(game_dir, model_stem, out_file=None):
    """Locate a specific model (e.g. 'pl0000_ng') across archives and extract valid .bmd6model bytes."""
    target_suffix = f"/{model_stem.lower()}.bmd6model"
    best = None
    for arc in iter_game_archives(game_dir):
        idx = read_tango_index(arc)
        for asset_name, recs in idx.items():
            low = asset_name.lower()
            if low.endswith(target_suffix) or low == f"{model_stem.lower()}.bmd6model":
                # Pick the largest record in case of duplicates
                rec = max(recs, key=lambda r: r[2])
                data = read_tango_entry(arc, *rec)
                if data[:4] == b"\x1a\x36MM":
                    best = (asset_name, arc.name, data)
                    break
        if best is not None:
            break
    if best is None:
        raise ValueError(f"未在游戏 .tangoresource 中找到有效模型 {model_stem}.bmd6model。")
    asset_name, arc_name, data = best
    if out_file is not None:
        out_path = Path(out_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
        return out_path, asset_name, arc_name, data
    return None, asset_name, arc_name, data


def extract_models_batch(game_dir, out_dir, scope="SEBASTIAN"):
    """Extract .bmd6model files from all game .tangoresource archives into categorized folders.
    scope: 'SEBASTIAN' | 'PL_ALL' | 'EM_ALL' | 'ALL'
    """
    out_root = Path(out_dir).resolve()
    if any((parent / "EvilWithin.exe").exists() for parent in (out_root, *out_root.parents)):
        raise ValueError("提取输出目录严禁选在游戏本体文件夹内，请另选外部目录。")

    core_set = set(SEBASTIAN_CORE_MODELS)
    collected = {}  # asset_lower -> (asset_name, arc_path, rec)

    for arc in iter_game_archives(game_dir):
        idx = read_tango_index(arc)
        for asset_name, recs in idx.items():
            low = asset_name.lower()
            if not low.endswith(".bmd6model"):
                continue
            stem = Path(low).stem
            if scope == "SEBASTIAN" and stem not in core_set:
                continue
            if scope == "PL_ALL" and "/characters/pl/" not in low and not stem.startswith("pl"):
                continue
            if scope == "EM_ALL" and "/characters/em/" not in low and not stem.startswith("em"):
                continue
            rec = max(recs, key=lambda r: r[2])
            prev = collected.get(low)
            if prev is None or rec[2] > prev[2][2]:
                collected[low] = (asset_name, arc, rec)
        if scope == "SEBASTIAN" and len(collected) >= len(core_set):
            break

    if not collected:
        raise ValueError("所选范围内没有匹配到任何 .bmd6model 文件。")

    written = 0
    for low in sorted(collected):
        asset_name, arc, rec = collected[low]
        data = read_tango_entry(arc, *rec)
        if data[:4] != b"\x1a\x36MM":
            continue
        stem = Path(asset_name).stem
        if scope == "SEBASTIAN":
            dest = out_root / f"{stem}.bmd6model"
        elif scope == "PL_ALL":
            dest = out_root / "人物与NPC_pl" / f"{stem}.bmd6model"
        elif scope == "EM_ALL":
            dest = out_root / "怪物与Boss_em" / f"{stem}.bmd6model"
        else:
            dest = out_root / asset_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        written += 1

    return written, out_root


class TEW1DetectGameDir(bpy.types.Operator):
    bl_idname = "object.tew1_detect_game_dir"
    bl_label = "自动检测游戏目录"
    bl_description = "自动搜索常见 Steam / 本地磁盘中的 EvilWithin.exe 所在目录"

    def execute(self, context):
        ws = context.scene.tew1_workspace
        found = auto_detect_game_dir()
        if not found:
            self.report({"WARNING"}, "未自动检测到 EvilWithin.exe，请手动点「游戏目录」右侧文件夹图标选择。")
            return {"CANCELLED"}
        ws.game_dir = found
        self.report({"INFO"}, f"已自动定位游戏目录: {found}")
        return {"FINISHED"}


class TEW1QuickImportStockModel(bpy.types.Operator):
    bl_idname = "import_scene.tew1_quick_import_stock"
    bl_label = "一键从游戏提取并导入原版模板"
    bl_description = "直接从《恶灵附身 1》游戏目录的 .tangoresource 中提取选定原版模型（默认 pl0000_ng 主角主模）并立刻导入 Blender 场景，无需提前手动解包"

    template_name: EnumProperty(
        name="选择原版模板",
        items=[
            ("pl0000_ng", "pl0000_ng · 主角全章节主模（推荐）", "常规游玩塞巴斯蒂安完整骨架与 31 个断肢槽位模板"),
            ("pl0020_ng", "pl0020_ng · 终章/医院西装变体", "剧情无外套/西装版本角色模板"),
            ("pl0010_ng", "pl0010_ng · CG 过场高精度头部", "含 9 根嘴角/眼睑骨骼的剧情特写头部模板"),
            ("pl0001_ng", "pl0001_ng · 断头掉落头部道具", "被斩首后掉落在地上的独立头部模板"),
        ],
        default="pl0000_ng",
    )

    def invoke(self, context, _event):
        ws = context.scene.tew1_workspace
        if not is_valid_game_dir(bpy.path.abspath(ws.game_dir) if ws.game_dir else ""):
            found = auto_detect_game_dir()
            if found:
                ws.game_dir = found
        return context.window_manager.invoke_props_dialog(self, width=360)

    def execute(self, context):
        from . import import_model
        ws = context.scene.tew1_workspace
        gdir = bpy.path.abspath(ws.game_dir).strip() if ws.game_dir else ""
        if not is_valid_game_dir(gdir):
            gdir = auto_detect_game_dir()
            if gdir:
                ws.game_dir = gdir
        if not is_valid_game_dir(gdir):
            self.report({"ERROR"}, "请先在上方「游戏本体目录」选择包含 EvilWithin.exe 的游戏安装目录。")
            return {"CANCELLED"}

        try:
            # Save extracted stock template outside overlay base/ if overlay is set, else temp dir
            with tempfile.TemporaryDirectory(prefix="tew1_stock_") as tmp:
                tmp_file = Path(tmp) / f"{self.template_name}.bmd6model"
                _p, asset_rel, arc_name, _data = extract_single_bmd6(gdir, self.template_name, tmp_file)
                rig = import_model(context, tmp_file)
                rig["tew1_overlay_asset"] = asset_rel
        except Exception as exc:
            self.report({"ERROR"}, f"提取/导入失败: {exc}")
            return {"CANCELLED"}

        self.report({"INFO"}, f"已直接从 {arc_name} 提取并导入原版模板 {self.template_name}！")
        return {"FINISHED"}


class TEW1ExtractGameModels(bpy.types.Operator, ExportHelper):
    bl_idname = "object.tew1_extract_game_models"
    bl_label = "批量提取原版 .bmd6model 到文件夹"
    bl_description = "从《恶灵附身 1》游戏目录 .tangoresource 中批量解包原版 .bmd6model 角色模型文件到指定文件夹，供随时导入使用"
    filename_ext = ""
    use_filter_folder = True

    scope: EnumProperty(
        name="提取范围",
        items=[
            ("SEBASTIAN", "主角全章节模板 (27个 · pl0000_ng 等，秒完成)", "提取主角全章节、过场头模及断肢道具等全部 27 个核心 .bmd6model"),
            ("PL_ALL",    "全游戏人物与 NPC 模型 (pl* 约 138 个)",         "提取塞巴斯蒂安、基德曼、约瑟夫、NPC 等全部 pl 角色模型"),
            ("EM_ALL",    "全游戏怪物与 Boss 模型 (em* 约 177 个)",        "提取贞子、箱子头、鲁维克、普通丧尸等全部 em 怪物模型"),
            ("ALL",       "全游戏所有 .bmd6model (约 2222 个，保持原路径)", "解包游戏中全部骨骼模型（含武器、道具、角色）并保留目录树"),
        ],
        default="SEBASTIAN",
    )

    def invoke(self, context, event):
        ws = context.scene.tew1_workspace
        if not is_valid_game_dir(bpy.path.abspath(ws.game_dir) if ws.game_dir else ""):
            found = auto_detect_game_dir()
            if found:
                ws.game_dir = found
        self.filepath = str(Path.home() / "Desktop" / "TEW1_原版模型")
        return super().invoke(context, event)

    def execute(self, context):
        ws = context.scene.tew1_workspace
        gdir = bpy.path.abspath(ws.game_dir).strip() if ws.game_dir else ""
        if not is_valid_game_dir(gdir):
            self.report({"ERROR"}, "请先在上方「游戏本体目录」选择包含 EvilWithin.exe 的游戏安装目录。")
            return {"CANCELLED"}
        try:
            out_dir = Path(self.filepath)
            if out_dir.suffix:
                out_dir = out_dir.parent
            count, resolved = extract_models_batch(gdir, out_dir, scope=self.scope)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        try:
            os.startfile(str(resolved))
        except Exception:
            pass
        self.report({"INFO"}, f"提取完成！共导出 {count} 个原版 .bmd6model 文件到: {resolved}")
        return {"FINISHED"}


CLASSES = (
    TEW1DetectGameDir,
    TEW1QuickImportStockModel,
    TEW1ExtractGameModels,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
