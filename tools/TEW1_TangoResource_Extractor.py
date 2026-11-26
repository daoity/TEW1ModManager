#!/usr/bin/env python3
"""《恶灵附身 1》(The Evil Within 1) 独立零依赖原版模型 & 资源提取工具 (GUI + CLI)

无需安装第三方 Python 库：双击直接弹出图形界面（自动查找游戏目录），
也可通过命令行批量解包 .bmd6model / .decl / .bimage / .wav。

用法示例：
  python TEW1_TangoResource_Extractor.py
  python TEW1_TangoResource_Extractor.py --game "F:\\Games\\TheEvilWithin" --out "./TEW1_原版模型" --scope sebastian
  python TEW1_TangoResource_Extractor.py --scope pl        # 提取所有人物与 NPC (pl*)
  python TEW1_TangoResource_Extractor.py --scope em        # 提取所有怪物与 Boss (em*)
  python TEW1_TangoResource_Extractor.py --scope all       # 提取全游戏全部 .bmd6model
  python TEW1_TangoResource_Extractor.py --filter "pl0000" # 按关键词提取任意资源（模型/贴图/decl/音频）
"""

import argparse
from collections import defaultdict
from pathlib import Path
import re
from struct import iter_unpack, unpack
import sys
import zlib


SEBASTIAN_CORE_MODELS = {
    "pl0000_ng", "pl0001_ng", "pl0002", "pl0003", "pl0004", "pl0005",
    "pl0006", "pl0007", "pl0008", "pl0009_ng", "pl0010_ng", "pl0011_ng",
    "pl0012_ng", "pl0016_ng", "pl0017_ng", "pl0018_ng", "pl0020_ng",
    "pl0200_ng", "pl0201_ng", "pl0210_ng", "pl0220_ng", "pl0220_m",
    "pl0220_l", "pl0230_ng", "pl0300_ng", "pl0301_ng", "em5002_ng",
}

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
    candidates = [Path.cwd(), *Path(__file__).resolve().parents]
    expanded = list(_iter_steam_library_game_dirs())
    for base in candidates:
        expanded.extend([
            base,
            base / "TheEvilWithin",
            base / "TheEvilWithin" / "TheEvilWithin",
            base / "The Evil Within",
        ])
    for drive in ("C", "D", "E", "F", "G", "H"):
        expanded.extend([
            Path(f"{drive}:/Program Files (x86)/Steam/steamapps/common/TheEvilWithin"),
            Path(f"{drive}:/SteamLibrary/steamapps/common/TheEvilWithin"),
            Path(f"{drive}:/Steam/steamapps/common/TheEvilWithin"),
            Path(f"{drive}:/Games/TheEvilWithin"),
            Path(f"{drive}:/Games/The Evil Within"),
            Path(f"{drive}:/TheEvilWithin"),
            Path(f"{drive}:/TheEvilWithin/TheEvilWithin"),
        ])
    for cand in expanded:
        try:
            if is_valid_game_dir(cand):
                return str(cand.resolve())
        except OSError:
            pass
    return ""


def read_tango_index(archive_path):
    entries = defaultdict(list)
    with Path(archive_path).open("rb") as f:
        if f.read(4) != b"\x23\x94\xab\xcd":
            return entries
        sec_count = unpack(">I", f.read(4))[0]
        for _ in range(sec_count):
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
            entries[names[key].decode("utf8", errors="surrogateescape")].append((offset, packed, raw))
    return entries


def read_tango_entry(archive_path, offset, packed, raw):
    with Path(archive_path).open("rb") as f:
        f.seek(offset)
        chunk = f.read(packed)
    if packed != raw:
        inflater = zlib.decompressobj(-15)
        chunk = inflater.decompress(chunk) + inflater.flush()
    if len(chunk) != raw:
        raise ValueError(f"Size mismatch: expected {raw}, got {len(chunk)}")
    return chunk


def iter_game_archives(game_dir):
    base_dir = Path(game_dir) / "base"
    if not base_dir.is_dir():
        raise ValueError(f"找不到 base 目录: {base_dir}")
    by_name = {p.name.lower(): p for p in base_dir.glob("*.tangoresource")}
    ordered = []
    for pref in PREFERRED_ARCHIVES:
        if pref in by_name:
            ordered.append(by_name.pop(pref))
    ordered.extend(sorted(by_name.values(), key=lambda p: p.name.lower()))
    return ordered


def extract_resources(game_dir, out_dir, scope="sebastian", keyword="", progress_cb=None):
    game_path = Path(game_dir).resolve()
    out_path = Path(out_dir).resolve()
    if out_path == game_path or out_path.is_relative_to(game_path):
        raise ValueError("输出目录不能放在游戏本体目录内，请选在游戏目录以外。")

    archives = iter_game_archives(game_path)
    collected = {}
    kw = keyword.strip().lower()

    for idx, arc in enumerate(archives, 1):
        if progress_cb:
            progress_cb(f"正在扫描 ({idx}/{len(archives)}): {arc.name}")
        index = read_tango_index(arc)
        for asset_name, recs in index.items():
            low = asset_name.lower()
            stem = Path(low).stem
            if kw:
                if kw not in low:
                    continue
            else:
                if not low.endswith(".bmd6model"):
                    continue
                if scope == "sebastian" and stem not in SEBASTIAN_CORE_MODELS:
                    continue
                if scope == "pl" and "/characters/pl/" not in low and not stem.startswith("pl"):
                    continue
                if scope == "em" and "/characters/em/" not in low and not stem.startswith("em"):
                    continue
            rec = max(recs, key=lambda r: r[2])
            prev = collected.get(low)
            if prev is None or rec[2] > prev[2][2]:
                collected[low] = (asset_name, arc, rec)
        if not kw and scope == "sebastian" and len(collected) >= len(SEBASTIAN_CORE_MODELS):
            break

    if not collected:
        raise ValueError("未匹配到任何可提取的资源。")

    written = 0
    total = len(collected)
    for idx, low in enumerate(sorted(collected), 1):
        asset_name, arc, rec = collected[low]
        data = read_tango_entry(arc, *rec)
        if not kw and scope == "sebastian":
            dest = out_path / "主角全章节模板" / Path(asset_name).name
        elif not kw and scope == "pl":
            dest = out_path / "人物与NPC_pl" / Path(asset_name).name
        elif not kw and scope == "em":
            dest = out_path / "怪物与Boss_em" / Path(asset_name).name
        else:
            dest = out_path / asset_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        written += 1
        if progress_cb and (idx % 25 == 0 or idx == total):
            progress_cb(f"正在写出 ({idx}/{total}): {Path(asset_name).name}")

    return written, out_path


def launch_gui():
    import os
    import threading
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("《恶灵附身 1》原版模型与资源提取工具 (TangoResource Extractor)")
    root.geometry("620x390")
    root.resizable(False, False)

    detected = auto_detect_game_dir()
    game_var = tk.StringVar(value=detected)
    out_var = tk.StringVar(value=str(Path.home() / "Desktop" / "TEW1_原版模型"))
    scope_var = tk.StringVar(value="sebastian")
    kw_var = tk.StringVar(value="")
    status_var = tk.StringVar(value="准备就绪。选择提取范围后点击「开始提取」。")

    pad = {"padx": 14, "pady": 6}
    frm = ttk.Frame(root, padding=14)
    frm.pack(fill="both", expand=True)

    ttk.Label(frm, text="1. 游戏安装目录（包含 EvilWithin.exe）：").pack(anchor="w")
    r1 = ttk.Frame(frm)
    r1.pack(fill="x", pady=(2, 8))
    ttk.Entry(r1, textvariable=game_var).pack(side="left", fill="x", expand=True)
    ttk.Button(r1, text="自动检测", command=lambda: game_var.set(auto_detect_game_dir() or game_var.get())).pack(side="left", padx=(6, 0))
    ttk.Button(r1, text="浏览...", command=lambda: game_var.set(filedialog.askdirectory(title="选择游戏目录") or game_var.get())).pack(side="left", padx=(4, 0))

    ttk.Label(frm, text="2. 模型保存目录（严禁选在游戏目录内）：").pack(anchor="w")
    r2 = ttk.Frame(frm)
    r2.pack(fill="x", pady=(2, 8))
    ttk.Entry(r2, textvariable=out_var).pack(side="left", fill="x", expand=True)
    ttk.Button(r2, text="浏览...", command=lambda: out_var.set(filedialog.askdirectory(title="选择输出目录") or out_var.get())).pack(side="left", padx=(6, 0))

    ttk.Label(frm, text="3. 选择提取范围：").pack(anchor="w")
    for val, txt in [
        ("sebastian", "主角塞巴斯蒂安全章节模板 (27 个 · pl0000_ng 等，秒完成，Blender 做 Mod 必选)"),
        ("pl", "全游戏所有人物与 NPC 模型 (pl* 约 138 个)"),
        ("em", "全游戏怪物与 Boss 模型 (em* 约 177 个)"),
        ("all", "全游戏全部 .bmd6model 模型 (约 2222 个，保留原路径)"),
    ]:
        ttk.Radiobutton(frm, text=txt, value=val, variable=scope_var).pack(anchor="w", pady=1)

    r3 = ttk.Frame(frm)
    r3.pack(fill="x", pady=(8, 6))
    ttk.Label(r3, text="（可选）按关键词提取任意资源 (.bimage/.decl/.wav)：").pack(side="left")
    ttk.Entry(r3, textvariable=kw_var, width=22).pack(side="left", padx=(6, 0))

    lbl = ttk.Label(frm, textvariable=status_var, foreground="#0a64ad")
    lbl.pack(anchor="w", pady=(8, 4))

    def start_extract():
        gdir = game_var.get().strip()
        odir = out_var.get().strip()
        if not is_valid_game_dir(gdir):
            messagebox.showerror("目录无效", "游戏目录中找不到 EvilWithin.exe 或 base/common.tangoresource。")
            return
        btn.config(state="disabled")

        def worker():
            try:
                cnt, dest = extract_resources(
                    gdir, odir, scope=scope_var.get(), keyword=kw_var.get(),
                    progress_cb=lambda msg: root.after(0, status_var.set, msg),
                )
                root.after(0, lambda: status_var.set(f"提取完成！共写出 {cnt} 个文件到 {dest}"))
                try:
                    os.startfile(str(dest))
                except Exception:
                    pass
                root.after(0, lambda: messagebox.showinfo("提取完成", f"成功提取 {cnt} 个文件到：\n{dest}"))
            except Exception as exc:
                root.after(0, lambda: status_var.set(f"提取失败: {exc}"))
                root.after(0, lambda: messagebox.showerror("提取失败", str(exc)))
            finally:
                root.after(0, lambda: btn.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    btn = ttk.Button(frm, text="开始提取原版模型", command=start_extract)
    btn.pack(fill="x", pady=(6, 0), ipady=6)
    root.mainloop()


def main():
    if len(sys.argv) == 1:
        launch_gui()
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", default="", help="游戏目录（含 EvilWithin.exe）；留空自动搜索")
    parser.add_argument("--out", default="./TEW1_原版模型", help="提取输出目录")
    parser.add_argument("--scope", choices=("sebastian", "pl", "em", "all"), default="sebastian")
    parser.add_argument("--filter", default="", help="按路径关键词过滤任意资源（含 .bimage/.decl/.wav）")
    args = parser.parse_args()
    gdir = args.game or auto_detect_game_dir()
    if not is_valid_game_dir(gdir):
        raise SystemExit("找不到有效游戏目录，请用 --game 指定包含 EvilWithin.exe 的路径。")
    cnt, dest = extract_resources(gdir, args.out, scope=args.scope, keyword=args.filter, progress_cb=print)
    print(f"Done! Extracted {cnt} files -> {dest}")


if __name__ == "__main__":
    main()
