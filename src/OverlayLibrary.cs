using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Xml.Linq;

namespace TEW1
{
    internal sealed class ModEntry
    {
        public string Id;
        public string Name;
        public string Version;
        public string Folder;
        public string Overlay;
        public bool IsLinkedFolder;
        public bool FolderMissing;
        public bool HasTexturesFolder;
        public bool HasSoundFolder;
        public bool HasRuntimePack;
        public int ModelCount;
        public int TextureCount;
        public int AudioCount;
        public int DeclCount;
        public int TotalFiles;
        public long TotalBytes;
        public DateTime AddedAt;

        /// <summary>
        /// Functional / addon mod (voice packs, decl patches, texture-only packs, etc. without character/scene models).
        /// These are toggled On/Off and automatically layered onto whichever model Mod is launched.
        /// </summary>
        public bool IsFunctionalAddon
        {
            get { return !FolderMissing && ModelCount == 0; }
        }

        public string SizeText
        {
            get { return FormatBytes(TotalBytes); }
        }

        public static string FormatBytes(long bytes)
        {
            if (bytes < 1024) return bytes + " B";
            double kb = bytes / 1024.0;
            if (kb < 1024.0) return kb.ToString("0.#") + " KB";
            double mb = kb / 1024.0;
            if (mb < 1024.0) return mb.ToString("0.##") + " MB";
            double gb = mb / 1024.0;
            return gb.ToString("0.##") + " GB";
        }
    }

    internal sealed class Library
    {
        // Portable mode: store mods and settings right next to TEW1ModManager.exe
        internal static readonly string DefaultRoot = Path.Combine(
            AppDomain.CurrentDomain.BaseDirectory, "Data");

        private static readonly HashSet<string> Extensions = new HashSet<string>(
            new[] { ".bmd6model", ".bimage", ".decl", ".clh", ".wav" }, StringComparer.OrdinalIgnoreCase);

        private static bool IsAllowedResource(string cleanPath)
        {
            if (Extensions.Contains(Path.GetExtension(cleanPath))) return true;
            string file = Path.GetFileName(cleanPath);
            return String.Equals(file, "tew1_dyn.bin", StringComparison.OrdinalIgnoreCase);
        }

        private readonly string root;
        private string ModsDir { get { return Path.Combine(root, "mods"); } }
        private string GameSettingPath { get { return Path.Combine(root, "game-path.txt"); } }
        private string LinkedFilePath { get { return Path.Combine(root, "linked-overlays.xml"); } }
        private string SettingsFilePath { get { return Path.Combine(root, "settings.xml"); } }

        internal Library(string directory = null)
        {
            root = Path.GetFullPath(directory ?? DefaultRoot);
            Directory.CreateDirectory(ModsDir);
        }

        internal string RootDirectory { get { return root; } }

        internal string Game
        {
            get { return File.Exists(GameSettingPath) ? File.ReadAllText(GameSettingPath, Encoding.UTF8).Trim() : ""; }
            set { AtomicWriteUtf8(GameSettingPath, value ?? ""); }
        }

        internal string ExtraLaunchArgs
        {
            get { return ReadSetting("extraLaunchArgs", ""); }
            set { WriteSetting("extraLaunchArgs", value ?? ""); }
        }

        internal string LastSelectedId
        {
            get { return ReadSetting("lastSelectedId", ""); }
            set { WriteSetting("lastSelectedId", value ?? ""); }
        }

        internal bool EnableHairPhysics
        {
            get { return ReadSetting("enableHairPhysics", "1") != "0"; }
            set { WriteSetting("enableHairPhysics", value ? "1" : "0"); }
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool CreateHardLinkW(string lpFileName, string lpExistingFileName, IntPtr lpSecurityAttributes);

        internal bool EnableIndependentFace
        {
            get { return ReadSetting("enableIndependentFace", "1") != "0"; }
            set { WriteSetting("enableIndependentFace", value ? "1" : "0"); }
        }

        internal HashSet<string> GetEnabledAddonIds()
        {
            var set = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            if (!File.Exists(SettingsFilePath)) return set;
            try
            {
                XElement doc = XElement.Load(SettingsFilePath);
                XElement container = doc.Element("enabledAddons");
                if (container != null)
                {
                    foreach (XElement el in container.Elements("id"))
                    {
                        string val = (el.Value ?? "").Trim();
                        if (val.Length > 0) set.Add(val);
                    }
                }
            }
            catch { }
            return set;
        }

        internal bool IsAddonEnabled(string id)
        {
            if (String.IsNullOrWhiteSpace(id)) return false;
            return GetEnabledAddonIds().Contains(id);
        }

        internal void SetAddonEnabled(string id, bool enabled)
        {
            if (String.IsNullOrWhiteSpace(id)) return;
            HashSet<string> current = GetEnabledAddonIds();
            if (enabled) current.Add(id);
            else current.Remove(id);

            XElement doc;
            if (File.Exists(SettingsFilePath))
            {
                try { doc = XElement.Load(SettingsFilePath); }
                catch { doc = new XElement("settings"); }
            }
            else
            {
                doc = new XElement("settings");
            }

            XElement existing = doc.Element("enabledAddons");
            if (existing != null) existing.Remove();
            var container = new XElement("enabledAddons");
            foreach (string item in current.OrderBy(x => x, StringComparer.OrdinalIgnoreCase))
            {
                container.Add(new XElement("id", item));
            }
            doc.Add(container);
            AtomicWriteUtf8(SettingsFilePath, doc.ToString());
        }

        internal List<ModEntry> GetEnabledAddons(IEnumerable<ModEntry> allEntries)
        {
            HashSet<string> enabledIds = GetEnabledAddonIds();
            if (enabledIds.Count == 0 || allEntries == null) return new List<ModEntry>();
            return allEntries
                .Where(m => m != null && m.IsFunctionalAddon && !m.FolderMissing && enabledIds.Contains(m.Id))
                .ToList();
        }

        /// <summary>
        /// Returns an overlay directory ready to mount:
        /// - Directly returns the single source directory when no merging is needed (zero overhead).
        /// - When combining a model Mod with 1+ enabled functional addons (or 2+ addons),
        ///   assembles Data\merged-overlay using instant NTFS hard links (fallback to copy across drives).
        /// </summary>
        internal string PrepareLaunchOverlay(ModEntry baseModel, IList<ModEntry> enabledAddons)
        {
            var layers = new List<ModEntry>();
            if (baseModel != null && !baseModel.FolderMissing && Directory.Exists(baseModel.Overlay))
            {
                layers.Add(baseModel);
            }
            if (enabledAddons != null)
            {
                foreach (ModEntry addon in enabledAddons)
                {
                    if (addon == null || addon.FolderMissing || !Directory.Exists(addon.Overlay)) continue;
                    if (baseModel != null && String.Equals(addon.Id, baseModel.Id, StringComparison.OrdinalIgnoreCase)) continue;
                    layers.Add(addon);
                }
            }

            if (layers.Count == 0)
                throw new InvalidDataException("没有可挂载的有效 Mod 目录。");
            if (layers.Count == 1)
                return layers[0].Overlay;

            string mergedDir = Path.Combine(root, "merged-overlay");
            if (Directory.Exists(mergedDir))
            {
                Directory.Delete(mergedDir, true);
            }
            Directory.CreateDirectory(mergedDir);

            string[] subDirs = new[] { Path.Combine("base", "generated"), Path.Combine("base", "sound") };
            foreach (ModEntry layer in layers)
            {
                foreach (string sub in subDirs)
                {
                    string srcRoot = Path.Combine(layer.Overlay, sub);
                    if (!Directory.Exists(srcRoot)) continue;
                    string dstRoot = Path.Combine(mergedDir, sub);
                    foreach (string srcFile in Directory.EnumerateFiles(srcRoot, "*", SearchOption.AllDirectories))
                    {
                        string rel = srcFile.Substring(srcRoot.Length).TrimStart(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                        string dstFile = Path.Combine(dstRoot, rel);
                        string dstParent = Path.GetDirectoryName(dstFile);
                        if (!Directory.Exists(dstParent)) Directory.CreateDirectory(dstParent);
                        if (File.Exists(dstFile)) File.Delete(dstFile);

                        if (!CreateHardLinkW(dstFile, srcFile, IntPtr.Zero))
                        {
                            File.Copy(srcFile, dstFile, true);
                        }
                    }
                }
            }

            return mergedDir;
        }

        private string ReadSetting(string key, string fallback)
        {
            if (!File.Exists(SettingsFilePath)) return fallback;
            try
            {
                XElement doc = XElement.Load(SettingsFilePath);
                XElement el = doc.Element(key);
                return el != null ? el.Value : fallback;
            }
            catch { return fallback; }
        }

        private void WriteSetting(string key, string value)
        {
            XElement doc;
            if (File.Exists(SettingsFilePath))
            {
                try { doc = XElement.Load(SettingsFilePath); }
                catch { doc = new XElement("settings"); }
            }
            else
            {
                doc = new XElement("settings");
            }

            XElement el = doc.Element(key);
            if (el == null) doc.Add(new XElement(key, value ?? ""));
            else el.Value = value ?? "";

            AtomicWriteUtf8(SettingsFilePath, doc.ToString());
        }

        private static void AtomicWriteUtf8(string targetPath, string content)
        {
            string dir = Path.GetDirectoryName(targetPath);
            if (!String.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
            string temporary = targetPath + "." + Guid.NewGuid().ToString("N");
            try
            {
                File.WriteAllText(temporary, content, new UTF8Encoding(false));
                if (File.Exists(targetPath))
                    File.Replace(temporary, targetPath, null);
                else
                    File.Move(temporary, targetPath);
            }
            finally
            {
                if (File.Exists(temporary))
                {
                    try { File.Delete(temporary); }
                    catch { }
                }
            }
        }

        internal List<ModEntry> GetAllEntries()
        {
            var list = new List<ModEntry>();
            list.AddRange(GetLinkedFolders());
            list.AddRange(GetInstalledMods());
            return list;
        }

        internal ModEntry[] GetInstalledMods()
        {
            if (!Directory.Exists(ModsDir)) return new ModEntry[0];
            return Directory.GetDirectories(ModsDir)
                .Where(dir => File.Exists(Path.Combine(dir, "entry.xml")) &&
                              !Path.GetFileName(dir).StartsWith("."))
                .Select(ReadLibraryMod)
                .OrderBy(mod => mod.Name, StringComparer.CurrentCultureIgnoreCase)
                .ThenBy(mod => mod.Version, StringComparer.CurrentCultureIgnoreCase)
                .ToArray();
        }

        internal ModEntry[] GetLinkedFolders()
        {
            if (!File.Exists(LinkedFilePath)) return new ModEntry[0];
            try
            {
                XElement doc = XElement.Load(LinkedFilePath);
                var results = new List<ModEntry>();
                foreach (XElement el in doc.Elements("link"))
                {
                    string path = (string)el.Element("path");
                    if (String.IsNullOrWhiteSpace(path)) continue;
                    string id = (string)el.Element("id");
                    if (String.IsNullOrWhiteSpace(id)) id = ComputeLinkId(path);
                    string savedName = (string)el.Element("name");
                    string savedVersion = (string)el.Element("version") ?? "";
                    DateTime added = DateTime.Now;
                    string addedStr = (string)el.Element("added");
                    if (!String.IsNullOrWhiteSpace(addedStr)) DateTime.TryParse(addedStr, out added);

                    results.Add(BuildLinkedEntry(id, path, savedName, savedVersion, added));
                }
                return results
                    .OrderByDescending(x => x.AddedAt)
                    .ThenBy(x => x.Name, StringComparer.CurrentCultureIgnoreCase)
                    .ToArray();
            }
            catch
            {
                return new ModEntry[0];
            }
        }

        internal ModEntry LinkFolder(string directory)
        {
            string validated = ValidateOverlay(directory);
            string id = ComputeLinkId(validated);

            string displayName = Path.GetFileName(validated.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
            if (String.IsNullOrWhiteSpace(displayName)) displayName = validated;
            string version = "";

            string infoPath = Path.Combine(validated, "mod.info");
            if (File.Exists(infoPath))
            {
                try
                {
                    var fi = new FileInfo(infoPath);
                    if (fi.Length <= 8192)
                    {
                        using (var reader = new StreamReader(infoPath, new UTF8Encoding(false, true), true))
                        {
                            ParseModInfo(reader, ref displayName, ref version);
                        }
                    }
                }
                catch { }
            }

            XElement doc;
            if (File.Exists(LinkedFilePath))
            {
                try { doc = XElement.Load(LinkedFilePath); }
                catch { doc = new XElement("links"); }
            }
            else
            {
                doc = new XElement("links");
            }

            XElement existing = doc.Elements("link")
                .FirstOrDefault(x => String.Equals((string)x.Element("id"), id, StringComparison.OrdinalIgnoreCase));

            DateTime now = DateTime.Now;
            if (existing != null)
            {
                existing.SetElementValue("path", validated);
                existing.SetElementValue("name", displayName);
                existing.SetElementValue("version", version);
                existing.SetElementValue("added", now.ToString("o"));
            }
            else
            {
                doc.Add(new XElement("link",
                    new XElement("id", id),
                    new XElement("path", validated),
                    new XElement("name", displayName),
                    new XElement("version", version),
                    new XElement("added", now.ToString("o"))));
            }

            AtomicWriteUtf8(LinkedFilePath, doc.ToString());
            return BuildLinkedEntry(id, validated, displayName, version, now);
        }

        internal void UnlinkFolder(ModEntry entry)
        {
            if (entry == null || !entry.IsLinkedFolder)
                throw new InvalidOperationException("不是有效的直挂目录记录。");
            if (!File.Exists(LinkedFilePath)) return;

            XElement doc;
            try { doc = XElement.Load(LinkedFilePath); }
            catch { return; }

            var matches = doc.Elements("link")
                .Where(x => String.Equals((string)x.Element("id"), entry.Id, StringComparison.OrdinalIgnoreCase))
                .ToList();
            foreach (XElement m in matches) m.Remove();
            AtomicWriteUtf8(LinkedFilePath, doc.ToString());
        }

        private static string ComputeLinkId(string normalizedPath)
        {
            using (var sha = SHA256.Create())
            {
                byte[] bytes = Encoding.UTF8.GetBytes(normalizedPath.ToLowerInvariant());
                byte[] hash = sha.ComputeHash(bytes);
                var sb = new StringBuilder("link:", 21);
                for (int i = 0; i < 8; i++) sb.Append(hash[i].ToString("x2"));
                return sb.ToString();
            }
        }

        private static ModEntry ReadLibraryMod(string directory)
        {
            XElement xml = XElement.Load(Path.Combine(directory, "entry.xml"));
            string overlayPath = Path.Combine(directory, "overlay");
            var entry = new ModEntry
            {
                Id = Path.GetFileName(directory),
                Folder = directory,
                Overlay = overlayPath,
                IsLinkedFolder = false,
                Name = (string)xml.Element("name") ?? Path.GetFileName(directory),
                Version = (string)xml.Element("version") ?? "",
                AddedAt = Directory.GetCreationTime(directory)
            };
            PopulateOverlayStats(entry);
            return entry;
        }

        private static ModEntry BuildLinkedEntry(string id, string path, string name, string version, DateTime added)
        {
            string display = !String.IsNullOrWhiteSpace(name)
                ? name
                : Path.GetFileName(path.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
            if (String.IsNullOrWhiteSpace(display)) display = path;

            var entry = new ModEntry
            {
                Id = id,
                Folder = path,
                Overlay = path,
                IsLinkedFolder = true,
                Name = display,
                Version = version ?? "",
                AddedAt = added
            };
            PopulateOverlayStats(entry);
            return entry;
        }

        private static void PopulateOverlayStats(ModEntry entry)
        {
            string generated = Path.Combine(entry.Overlay, "base", "generated");
            string sound = Path.Combine(entry.Overlay, "base", "sound");
            bool hasGenerated = Directory.Exists(generated);
            bool hasSound = Directory.Exists(sound);
            if (!hasGenerated && !hasSound)
            {
                entry.FolderMissing = true;
                return;
            }

            entry.FolderMissing = false;
            entry.HasTexturesFolder = hasGenerated && Directory.Exists(Path.Combine(generated, "textures"));
            entry.HasSoundFolder = hasSound;
            entry.HasRuntimePack = hasGenerated && File.Exists(Path.Combine(generated, "tew1_dyn.bin"));

            try
            {
                int models = 0, textures = 0, audios = 0, decls = 0, total = 0;
                long bytes = 0;
                var roots = new List<string>();
                if (hasGenerated) roots.Add(generated);
                if (hasSound) roots.Add(sound);
                foreach (string dir in roots)
                {
                    foreach (string file in Directory.EnumerateFiles(dir, "*", SearchOption.AllDirectories))
                    {
                        total++;
                        try { bytes += new FileInfo(file).Length; }
                        catch { }

                        string ext = Path.GetExtension(file);
                        if (String.Equals(ext, ".bmd6model", StringComparison.OrdinalIgnoreCase)) models++;
                        else if (String.Equals(ext, ".bimage", StringComparison.OrdinalIgnoreCase)) textures++;
                        else if (String.Equals(ext, ".wav", StringComparison.OrdinalIgnoreCase)) audios++;
                        else if (String.Equals(ext, ".decl", StringComparison.OrdinalIgnoreCase) ||
                                 String.Equals(ext, ".clh", StringComparison.OrdinalIgnoreCase)) decls++;
                    }
                }

                entry.ModelCount = models;
                entry.TextureCount = textures;
                entry.AudioCount = audios;
                entry.DeclCount = decls;
                entry.TotalFiles = total;
                entry.TotalBytes = bytes;
            }
            catch { }
        }

        private static string CleanEntry(string name)
        {
            string path = name.Replace('\\', '/').TrimEnd('/');
            string[] parts = path.Split('/');
            foreach (string part in parts)
            {
                string prefix = part.Split('.')[0];
                if (part.Length == 0 || part == "." || part == ".." ||
                    part.EndsWith(".") || part.EndsWith(" ") ||
                    part.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 ||
                    String.Equals(prefix, "CON", StringComparison.OrdinalIgnoreCase) ||
                    String.Equals(prefix, "PRN", StringComparison.OrdinalIgnoreCase) ||
                    String.Equals(prefix, "AUX", StringComparison.OrdinalIgnoreCase) ||
                    String.Equals(prefix, "NUL", StringComparison.OrdinalIgnoreCase) ||
                    (prefix.Length == 4 && Char.IsDigit(prefix[3]) &&
                        (prefix.StartsWith("COM", StringComparison.OrdinalIgnoreCase) ||
                         prefix.StartsWith("LPT", StringComparison.OrdinalIgnoreCase))))
                    throw new InvalidDataException("ZIP 含有无效的文件路径：" + name);
            }
            return path;
        }

        private static string OverlayRoot(string path)
        {
            string[] markers = new[] { "base/generated/", "base/sound/" };
            foreach (string marker in markers)
            {
                int after = 0;
                while (after <= path.Length)
                {
                    int at = path.IndexOf(marker, after, StringComparison.OrdinalIgnoreCase);
                    if (at < 0) break;
                    if (at == 0 || path[at - 1] == '/') return path.Substring(0, at);
                    after = at + marker.Length;
                }
            }
            return null;
        }

        private static void ParseModInfo(StreamReader reader, ref string display, ref string version)
        {
            string line;
            while ((line = reader.ReadLine()) != null)
            {
                int split = line.IndexOf('=');
                if (split <= 0) continue;
                string key = line.Substring(0, split).Trim();
                string value = line.Substring(split + 1).Trim();
                if (key == "name" && value.Length > 0) display = value;
                if (key == "version") version = value;
            }
        }

        internal ModEntry ImportZip(string file)
        {
            if (!String.Equals(Path.GetExtension(file), ".zip", StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("请选择 .zip 格式的 Mod 压缩包。");

            using (var input = File.Open(file, FileMode.Open, FileAccess.Read, FileShare.Read))
            using (var sha = SHA256.Create())
            {
                string id = BitConverter.ToString(sha.ComputeHash(input)).Replace("-", "").ToLowerInvariant();
                string entryFolder = Path.Combine(ModsDir, id);
                if (Directory.Exists(entryFolder) && File.Exists(Path.Combine(entryFolder, "entry.xml")))
                    return ReadLibraryMod(entryFolder);

                input.Position = 0;
                string stage = Path.Combine(ModsDir, ".import-" + Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(stage);
                try
                {
                    string display = Path.GetFileNameWithoutExtension(file);
                    string version = "";
                    using (var archive = new ZipArchive(input, ZipArchiveMode.Read, true, Encoding.GetEncoding(936)))
                    {
                        var resources = new Dictionary<string, ZipArchiveEntry>(StringComparer.OrdinalIgnoreCase);
                        var roots = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                        foreach (ZipArchiveEntry entry in archive.Entries)
                        {
                            string clean = CleanEntry(entry.FullName);
                            if (entry.Name.Length == 0) continue;
                            string prefix = OverlayRoot(clean);
                            if (prefix != null && IsAllowedResource(clean))
                            {
                                roots.Add(prefix);
                                if (resources.ContainsKey(clean))
                                    throw new InvalidDataException("ZIP 内存在重复资源路径：" + clean);
                                resources.Add(clean, entry);
                            }
                        }
                        if (roots.Count != 1 || resources.Count == 0)
                            throw new InvalidDataException("需要一个外部挂载 Mod，ZIP 中应包含且仅包含一套 base/generated 资源。");

                        string prefixToSkip = roots.Single();
                        if (resources.Count > 20000 || resources.Values.Sum(entry => entry.Length) > 4L * 1024 * 1024 * 1024)
                            throw new InvalidDataException("ZIP 解压后的资源数量或大小超出支持范围。");

                        string output = Path.Combine(stage, "overlay");
                        foreach (var item in resources)
                        {
                            string relative = item.Key.Substring(prefixToSkip.Length);
                            string destination = Path.GetFullPath(Path.Combine(output, relative.Replace('/', Path.DirectorySeparatorChar)));
                            if (!destination.StartsWith(output + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                                throw new InvalidDataException("资源路径越过 Mod 目录边界。");
                            Directory.CreateDirectory(Path.GetDirectoryName(destination));
                            item.Value.ExtractToFile(destination);
                        }

                        var info = archive.Entries.FirstOrDefault(entry =>
                            (String.Equals(entry.FullName, "mod.info", StringComparison.OrdinalIgnoreCase) ||
                             String.Equals(entry.FullName, prefixToSkip + "mod.info", StringComparison.OrdinalIgnoreCase)) &&
                            entry.Length <= 8192);
                        if (info != null)
                        {
                            using (var text = new StreamReader(info.Open(), new UTF8Encoding(false, true), true))
                            {
                                ParseModInfo(text, ref display, ref version);
                            }
                        }
                    }

                    new XElement("mod",
                        new XElement("name", display),
                        new XElement("version", version))
                        .Save(Path.Combine(stage, "entry.xml"));

                    try { Directory.Move(stage, entryFolder); }
                    catch (IOException)
                    {
                        if (!Directory.Exists(entryFolder)) throw;
                    }
                    return ReadLibraryMod(entryFolder);
                }
                finally
                {
                    if (Directory.Exists(stage))
                    {
                        try { Directory.Delete(stage, true); }
                        catch { }
                    }
                }
            }
        }

        internal void RemoveMod(ModEntry mod)
        {
            if (mod == null) throw new ArgumentNullException("mod");
            SetAddonEnabled(mod.Id, false);
            if (mod.IsLinkedFolder)
            {
                UnlinkFolder(mod);
                return;
            }

            string folder = Path.Combine(ModsDir, mod.Id);
            if (!String.Equals(Path.GetFullPath(mod.Folder), folder, StringComparison.OrdinalIgnoreCase) ||
                mod.Id.Length != 64 || mod.Id.Any(ch => !"0123456789abcdef".Contains(ch)))
                throw new InvalidOperationException("无效的 Mod 存储记录。");
            Directory.Delete(folder, true);
        }

        internal static string ValidateGame(string directory)
        {
            if (String.IsNullOrWhiteSpace(directory))
                throw new InvalidDataException("请先选择包含 EvilWithin.exe 的游戏目录。");
            string root = Path.GetFullPath(directory.Trim());
            if (!File.Exists(Path.Combine(root, "EvilWithin.exe")) ||
                !File.Exists(Path.Combine(root, "base", "common.tangoresource")))
                throw new InvalidDataException("此目录中找不到 EvilWithin.exe 或 base\\common.tangoresource。");
            return root;
        }

        internal static string ValidateOverlay(string directory)
        {
            if (String.IsNullOrWhiteSpace(directory))
                throw new InvalidDataException("请选择有效的 Mod 挂载目录。");
            string root = Path.GetFullPath(directory.Trim());
            if (!Directory.Exists(Path.Combine(root, "base", "generated")) &&
                !Directory.Exists(Path.Combine(root, "base", "sound")))
                throw new InvalidDataException("所选目录中找不到 base\\generated 或 base\\sound 文件夹。");
            return root;
        }

        internal static string AutoDetectGameDirectory()
        {
            var candidates = new List<string>();
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            candidates.Add(baseDir);

            try
            {
                DirectoryInfo cur = new DirectoryInfo(baseDir);
                for (int i = 0; i < 4 && cur != null; i++)
                {
                    candidates.Add(cur.FullName);
                    candidates.Add(Path.Combine(cur.FullName, "TheEvilWithin"));
                    candidates.Add(Path.Combine(cur.FullName, "TheEvilWithin", "TheEvilWithin"));
                    candidates.Add(Path.Combine(cur.FullName, "The Evil Within"));
                    cur = cur.Parent;
                }
            }
            catch { }

            string[] drives = new[] { "C", "D", "E", "F", "G" };
            foreach (string drive in drives)
            {
                candidates.Add(drive + @":\Program Files (x86)\Steam\steamapps\common\TheEvilWithin");
                candidates.Add(drive + @":\SteamLibrary\steamapps\common\TheEvilWithin");
                candidates.Add(drive + @":\Games\TheEvilWithin");
                candidates.Add(drive + @":\TheEvilWithin");
            }

            foreach (string candidate in candidates.Distinct(StringComparer.OrdinalIgnoreCase))
            {
                try
                {
                    if (Directory.Exists(candidate) &&
                        File.Exists(Path.Combine(candidate, "EvilWithin.exe")) &&
                        File.Exists(Path.Combine(candidate, "base", "common.tangoresource")))
                    {
                        return Path.GetFullPath(candidate);
                    }
                }
                catch { }
            }
            return null;
        }
    }
}
