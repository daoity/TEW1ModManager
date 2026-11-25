using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shell;

namespace TEW1
{
    internal enum ExtractScope
    {
        SebastianCore,
        AllPlayers,
        AllEnemies,
        AllModels
    }

    internal sealed class ExtractResult
    {
        public int WrittenCount;
        public int ArchivesScanned;
        public string OutputDir;
    }

    internal static class TangoExtractor
    {
        private static readonly HashSet<string> SebastianCoreStems = new HashSet<string>(
            new[]
            {
                "pl0000_ng", "pl0001_ng", "pl0002", "pl0003", "pl0004", "pl0005",
                "pl0006", "pl0007", "pl0008", "pl0009_ng", "pl0010_ng", "pl0011_ng",
                "pl0012_ng", "pl0016_ng", "pl0017_ng", "pl0018_ng", "pl0020_ng",
                "pl0200_ng", "pl0201_ng", "pl0210_ng", "pl0220_ng", "pl0220_m",
                "pl0220_l", "pl0230_ng", "pl0300_ng", "pl0301_ng", "em5002_ng"
            },
            StringComparer.OrdinalIgnoreCase);

        private static readonly string[] PreferredArchives = new[]
        {
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
            "dlc2_chapter4.tangoresource"
        };

        private static uint ReadUInt32BE(BinaryReader br)
        {
            byte[] b = br.ReadBytes(4);
            if (b.Length < 4) throw new EndOfStreamException();
            return ((uint)b[0] << 24) | ((uint)b[1] << 16) | ((uint)b[2] << 8) | b[3];
        }

        private static uint ReadUInt32BEFromBuffer(byte[] buf, int off)
        {
            return ((uint)buf[off] << 24) | ((uint)buf[off + 1] << 16) | ((uint)buf[off + 2] << 8) | buf[off + 3];
        }

        private static uint ReadUInt32LE(BinaryReader br)
        {
            byte[] b = br.ReadBytes(4);
            if (b.Length < 4) throw new EndOfStreamException();
            return (uint)b[0] | ((uint)b[1] << 8) | ((uint)b[2] << 16) | ((uint)b[3] << 24);
        }

        private struct ArchiveRecord
        {
            public string ArchivePath;
            public string AssetName;
            public uint Offset;
            public uint PackedSize;
            public uint RawSize;
        }

        private static List<string> OrderArchives(string gameDir)
        {
            string baseDir = Path.Combine(gameDir, "base");
            if (!Directory.Exists(baseDir))
                throw new DirectoryNotFoundException("找不到游戏 base 目录：" + baseDir);

            string[] all = Directory.GetFiles(baseDir, "*.tangoresource", SearchOption.TopDirectoryOnly);
            if (all.Length == 0)
                throw new FileNotFoundException("游戏 base 目录中未找到任何 .tangoresource 文件。");

            var byName = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (string p in all)
                byName[Path.GetFileName(p)] = p;

            var ordered = new List<string>();
            foreach (string pref in PreferredArchives)
            {
                string match;
                if (byName.TryGetValue(pref, out match))
                {
                    ordered.Add(match);
                    byName.Remove(pref);
                }
            }
            ordered.AddRange(byName.Values.OrderBy(x => Path.GetFileName(x), StringComparer.OrdinalIgnoreCase));
            return ordered;
        }

        private static void ScanArchive(string archivePath, ExtractScope scope, Dictionary<string, ArchiveRecord> collected)
        {
            using (var fs = new FileStream(archivePath, FileMode.Open, FileAccess.Read, FileShare.Read))
            using (var br = new BinaryReader(fs))
            {
                byte[] magic = br.ReadBytes(4);
                if (magic.Length < 4 || magic[0] != 0x23 || magic[1] != 0x94 || magic[2] != 0xAB || magic[3] != 0xCD)
                    return;

                uint secCount = ReadUInt32BE(br);
                for (uint i = 0; i < secCount; i++)
                {
                    uint len1 = ReadUInt32LE(br);
                    fs.Seek(len1, SeekOrigin.Current);
                    uint len2 = ReadUInt32LE(br);
                    fs.Seek(len2 + 4, SeekOrigin.Current);
                }

                uint indexOffset = ReadUInt32BE(br);
                fs.Seek(indexOffset, SeekOrigin.Begin);

                uint entryCount = ReadUInt32BE(br);
                ReadUInt32BE(br);
                ReadUInt32BE(br);
                uint groups = ReadUInt32BE(br);
                uint aliases = ReadUInt32BE(br);
                fs.Seek(2L * (groups + aliases), SeekOrigin.Current);

                uint strSize = ReadUInt32BE(br);
                uint strCount = ReadUInt32BE(br);
                byte[] nameBytes = br.ReadBytes((int)strSize);
                var names = new List<string>((int)strCount);
                int start = 0;
                for (int i = 0; i < nameBytes.Length && names.Count < strCount; i++)
                {
                    if (nameBytes[i] == 0)
                    {
                        names.Add(Encoding.UTF8.GetString(nameBytes, start, i - start));
                        start = i + 1;
                    }
                }

                byte[] table = br.ReadBytes((int)entryCount * 16);
                int rowCount = table.Length / 16;
                for (int r = 0; r < rowCount; r++)
                {
                    int rowOff = r * 16;
                    uint key = ReadUInt32BEFromBuffer(table, rowOff);
                    if (key >= (uint)names.Count) continue;

                    string asset = names[(int)key];
                    if (!asset.EndsWith(".bmd6model", StringComparison.OrdinalIgnoreCase))
                        continue;

                    string low = asset.ToLowerInvariant();
                    string stem = Path.GetFileNameWithoutExtension(low);
                    if (scope == ExtractScope.SebastianCore && !SebastianCoreStems.Contains(stem))
                        continue;
                    if (scope == ExtractScope.AllPlayers && !low.Contains("/characters/pl/") && !stem.StartsWith("pl"))
                        continue;
                    if (scope == ExtractScope.AllEnemies && !low.Contains("/characters/em/") && !stem.StartsWith("em"))
                        continue;

                    uint offset = ReadUInt32BEFromBuffer(table, rowOff + 4);
                    uint packed = ReadUInt32BEFromBuffer(table, rowOff + 8);
                    uint raw = ReadUInt32BEFromBuffer(table, rowOff + 12);

                    ArchiveRecord existing;
                    if (!collected.TryGetValue(low, out existing) || raw > existing.RawSize)
                    {
                        collected[low] = new ArchiveRecord
                        {
                            ArchivePath = archivePath,
                            AssetName = asset,
                            Offset = offset,
                            PackedSize = packed,
                            RawSize = raw
                        };
                    }
                }
            }
        }

        private static byte[] ReadPayload(ArchiveRecord rec)
        {
            byte[] packedBytes;
            using (var fs = new FileStream(rec.ArchivePath, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                fs.Seek(rec.Offset, SeekOrigin.Begin);
                packedBytes = new byte[rec.PackedSize];
                int readTotal = 0;
                while (readTotal < packedBytes.Length)
                {
                    int n = fs.Read(packedBytes, readTotal, packedBytes.Length - readTotal);
                    if (n <= 0) throw new EndOfStreamException();
                    readTotal += n;
                }
            }

            if (rec.PackedSize == rec.RawSize)
                return packedBytes;

            using (var compressedStream = new MemoryStream(packedBytes))
            using (var deflate = new DeflateStream(compressedStream, CompressionMode.Decompress))
            using (var output = new MemoryStream((int)rec.RawSize))
            {
                deflate.CopyTo(output);
                byte[] rawBytes = output.ToArray();
                if (rawBytes.Length != rec.RawSize)
                    throw new InvalidDataException("解压长度不匹配：" + rec.AssetName);
                return rawBytes;
            }
        }

        internal static ExtractResult ExtractModels(string gameDir, string outputDir, ExtractScope scope)
        {
            string fullGame = Path.GetFullPath(gameDir);
            string fullOut = Path.GetFullPath(outputDir);
            if (fullOut.StartsWith(fullGame + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase) ||
                String.Equals(fullOut, fullGame, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException("提取输出目录不能选在游戏本体目录内，请选在游戏目录以外。");
            }

            List<string> archives = OrderArchives(fullGame);
            var collected = new Dictionary<string, ArchiveRecord>(StringComparer.OrdinalIgnoreCase);
            int scanned = 0;

            foreach (string arc in archives)
            {
                scanned++;
                ScanArchive(arc, scope, collected);
                if (scope == ExtractScope.SebastianCore && collected.Count >= SebastianCoreStems.Count)
                    break;
            }

            if (collected.Count == 0)
                throw new InvalidOperationException("所选范围未找到可提取的 .bmd6model 文件。");

            Directory.CreateDirectory(fullOut);
            int written = 0;
            foreach (var kv in collected.OrderBy(k => k.Key, StringComparer.Ordinal))
            {
                ArchiveRecord rec = kv.Value;
                byte[] data = ReadPayload(rec);
                if (data.Length < 4 || data[0] != 0x1A || data[1] != 0x36 || data[2] != 0x4D || data[3] != 0x4D)
                    continue;

                string fileName = Path.GetFileName(rec.AssetName);
                string destPath;
                if (scope == ExtractScope.SebastianCore)
                    destPath = Path.Combine(fullOut, "主角全章节模板", fileName);
                else if (scope == ExtractScope.AllPlayers)
                    destPath = Path.Combine(fullOut, "人物与NPC_pl", fileName);
                else if (scope == ExtractScope.AllEnemies)
                    destPath = Path.Combine(fullOut, "怪物与Boss_em", fileName);
                else
                    destPath = Path.Combine(fullOut, rec.AssetName.Replace('/', Path.DirectorySeparatorChar));

                Directory.CreateDirectory(Path.GetDirectoryName(destPath));
                File.WriteAllBytes(destPath, data);
                written++;
            }

            return new ExtractResult
            {
                WrittenCount = written,
                ArchivesScanned = scanned,
                OutputDir = fullOut
            };
        }

        internal static ExtractScope? PromptExtractScope(Window owner)
        {
            ExtractScope? chosen = null;
            var dlg = new Window
            {
                Title = "提取游戏原版 .bmd6model 模型",
                Width = 480,
                SizeToContent = SizeToContent.Height,
                ResizeMode = ResizeMode.NoResize,
                WindowStyle = WindowStyle.None,
                WindowStartupLocation = owner != null ? WindowStartupLocation.CenterOwner : WindowStartupLocation.CenterScreen,
                Owner = owner,
                Background = AppTheme.Brush("#141923"),
                Foreground = AppTheme.Brush("#F1F5F9"),
                FontFamily = new FontFamily("Segoe UI Variable Text, Microsoft YaHei UI, Segoe UI"),
                ShowInTaskbar = false
            };
            dlg.Resources.MergedDictionaries.Add(AppTheme.CreateResources());
            AppTheme.ApplyModernWindowChrome(dlg);
            WindowChrome.SetWindowChrome(dlg, new WindowChrome
            {
                CaptionHeight = 40,
                CornerRadius = new CornerRadius(10),
                GlassFrameThickness = new Thickness(0),
                ResizeBorderThickness = new Thickness(0),
                UseAeroCaptionButtons = false
            });

            var outer = new Border
            {
                BorderBrush = AppTheme.Brush("#2B3548"),
                BorderThickness = new Thickness(1),
                Background = AppTheme.Brush("#141923"),
                Padding = new Thickness(22, 18, 22, 18)
            };
            var stack = new StackPanel();
            stack.Children.Add(new TextBlock
            {
                Text = "提取原版 .bmd6model 模型（用于 Blender 导入）",
                FontSize = 15.5,
                FontWeight = FontWeights.SemiBold,
                Foreground = AppTheme.Brush("#F8FAFC"),
                Margin = new Thickness(0, 0, 0, 6)
            });
            stack.Children.Add(new TextBlock
            {
                Text = "原版模型打包在游戏 base/*.tangoresource 中。选择要提取的范围后，指定输出文件夹即可导出可直接拖入 Blender「TEW Mesh → 导入 BMD6」的模型文件：",
                FontSize = 12,
                LineHeight = 18,
                Foreground = AppTheme.Brush("#94A3B8"),
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 0, 0, 12)
            });

            var rbCore = new RadioButton
            {
                Content = "主角塞巴斯蒂安全章节模板 (27 个 · 含 pl0000_ng 主模、过场头、断肢，秒完成)",
                IsChecked = true,
                Foreground = AppTheme.Brush("#F1F5F9"),
                FontSize = 12.5,
                Margin = new Thickness(0, 0, 0, 8)
            };
            var rbPl = new RadioButton
            {
                Content = "全游戏所有人物与 NPC (pl* 约 138 个 · 含基德曼/约瑟夫/医生等)",
                Foreground = AppTheme.Brush("#CBD5E1"),
                FontSize = 12.5,
                Margin = new Thickness(0, 0, 0, 8)
            };
            var rbEm = new RadioButton
            {
                Content = "全游戏怪物与 Boss 模型 (em* 约 177 个 · 含贞子/箱子头/丧尸等)",
                Foreground = AppTheme.Brush("#CBD5E1"),
                FontSize = 12.5,
                Margin = new Thickness(0, 0, 0, 8)
            };
            var rbAll = new RadioButton
            {
                Content = "全游戏所有 .bmd6model 模型 (约 2222 个 · 保持原版目录结构)",
                Foreground = AppTheme.Brush("#CBD5E1"),
                FontSize = 12.5,
                Margin = new Thickness(0, 0, 0, 14)
            };
            stack.Children.Add(rbCore);
            stack.Children.Add(rbPl);
            stack.Children.Add(rbEm);
            stack.Children.Add(rbAll);

            var buttons = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Right
            };
            var cancelBtn = new Button
            {
                Content = "取消",
                Style = (Style)dlg.FindResource("SecondaryButton"),
                MinWidth = 82,
                Margin = new Thickness(0, 0, 10, 0),
                IsCancel = true
            };
            cancelBtn.Click += delegate { chosen = null; dlg.Close(); };
            buttons.Children.Add(cancelBtn);

            var okBtn = new Button
            {
                Content = "选择保存位置并提取",
                Style = (Style)dlg.FindResource("PrimaryButton"),
                MinWidth = 136,
                IsDefault = true
            };
            okBtn.Click += delegate
            {
                if (rbPl.IsChecked == true) chosen = ExtractScope.AllPlayers;
                else if (rbEm.IsChecked == true) chosen = ExtractScope.AllEnemies;
                else if (rbAll.IsChecked == true) chosen = ExtractScope.AllModels;
                else chosen = ExtractScope.SebastianCore;
                dlg.Close();
            };
            buttons.Children.Add(okBtn);
            stack.Children.Add(buttons);

            outer.Child = stack;
            dlg.Content = outer;
            dlg.KeyDown += delegate(object s, KeyEventArgs e)
            {
                if (e.Key == Key.Escape)
                {
                    chosen = null;
                    dlg.Close();
                }
            };
            dlg.ShowDialog();
            return chosen;
        }
    }
}
