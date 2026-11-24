using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;

namespace TEW1
{
    internal enum GameCheckState
    {
        NotConfigured,
        MissingFiles,
        UnsupportedBuild,
        Ready
    }

    internal sealed class GameValidationResult
    {
        public GameCheckState State;
        public string NormalizedPath;
        public string Sha256;
        public string Message;
    }

    /// <summary>
    /// Native x64 Windows loader for The Evil Within loose-asset overlay mounting.
    /// Implements the exact memory-patching protocol of mount.py without requiring an external Python runtime.
    /// </summary>
    internal static class NativeLoader
    {
        internal const string SupportedExeSha256 = "8737abc65d2b575cb6acb8c435dd7e2ce1053411a084b87f24e493b68df2c0ab";

        private const long LooseResourceCheckOffset = 0x787EF;
        private const int ProductionLimitIndex = 18;
        private const long ModelOpenCallOffset = 0x18F67E;
        private const long ImageOpenCallOffset = 0x1BA9DB;
        private const long WaveOpenCallOffset = 0x3141A1;
        private const long WaveLangSubCallOffset = 0x313F52;
        private const long SoundLoadCallOffset = 0x305DB2;
        private const long SoundLoadWavOffset = 0x306040;
        private const long SoundLoadGeneratedOffset = 0x306D00;

        private const uint ProcessAccess = 0x0438; // QUERY_INFO | VM_OPERATION | VM_READ | VM_WRITE
        private const uint MemCommitReserve = 0x3000;
        private const uint PageExecuteRead = 0x20;
        private const uint PageExecuteReadWrite = 0x40;

        private static readonly byte[] StockCheck = new byte[]
        {
            0x83, 0x3d, 0xd2, 0x11, 0x73, 0x02, 0x00,
            0x48, 0x8b, 0xd9, 0x74, 0x7d,
            0x83, 0x3d, 0xae, 0x62, 0xa8, 0x09, 0x03,
            0x7d, 0x74
        };

        private static readonly byte[] StockModelOpen = new byte[]
        {
            0xff, 0x90, 0x48, 0x01, 0x00, 0x00
        };

        private static readonly byte[] StockSoundLoadCall = new byte[]
        {
            0xe8, 0x49, 0x0f, 0x00, 0x00
        };

        // In idWaveFile::Open, bypass language-segment rewrite ("english" -> currentLang)
        // so loose WAV mods placed under base/sound/voice_talk/english/... work in ALL game audio languages!
        private static readonly byte[] StockWaveLangSubCall = new byte[]
        {
            0xe8, 0x29, 0x4d, 0xd6, 0xff
        };

        private static readonly byte[] PatchWaveLangBypass = new byte[]
        {
            0x4c, 0x89, 0xc0, 0x90, 0x90  // mov rax, r8; nop; nop
        };

        // In idSoundSample::LoadResource, try loading a loose .wav via LoadWav first.
        // If found, mark sample as RAM-backed loaded (streamFile=NULL, loadState=1);
        // otherwise fall back seamlessly to LoadGeneratedSound (.bsnd + .streamed).
        private static readonly byte[] SoundLoadOverlayTemplate = new byte[]
        {
            0x48, 0x83, 0xec, 0x48,
            0x48, 0x89, 0x4c, 0x24, 0x30,
            0x48, 0x89, 0x54, 0x24, 0x38,
            0x48, 0x8b, 0x41, 0x08,
            0x48, 0x85, 0xc0,
            0x74, 0x31,
            0x48, 0x89, 0x44, 0x24, 0x28,
            0x48, 0x8d, 0x54, 0x24, 0x20,
            0xe8, 0x00, 0x00, 0x00, 0x00,  // +0x22: rel32 to LoadWav (0x306040), next IP +0x26
            0x84, 0xc0,
            0x74, 0x1e,
            0x48, 0x8b, 0x4c, 0x24, 0x30,
            0x48, 0xc7, 0x41, 0x68, 0x00, 0x00, 0x00, 0x00,
            0xc7, 0x81, 0xc4, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00,
            0xb0, 0x01,
            0x48, 0x83, 0xc4, 0x48,
            0xc3,
            // fallback (+0x48):
            0x48, 0x8b, 0x4c, 0x24, 0x30,
            0x48, 0x8b, 0x54, 0x24, 0x38,
            0xe8, 0x00, 0x00, 0x00, 0x00,  // +0x53: rel32 to LoadGeneratedSound (0x306D00), next IP +0x57
            0x48, 0x83, 0xc4, 0x48,
            0xc3
        };

        // Try native filesystem with archive callbacks disabled first, then fall back to archive path.
        private static readonly byte[] ModelOpenOverlay = new byte[]
        {
            0x48, 0x83, 0xec, 0x48,
            0x48, 0x89, 0x4c, 0x24, 0x28,
            0x48, 0x89, 0x54, 0x24, 0x30,
            0x48, 0x89, 0x44, 0x24, 0x38,
            0x48, 0xc7, 0x44, 0x24, 0x20, 0x00, 0x00, 0x00, 0x00,
            0x45, 0x33, 0xc0, 0x45, 0x33, 0xc9,
            0xff, 0x90, 0x48, 0x01, 0x00, 0x00,
            0x48, 0x85, 0xc0, 0x75, 0x1e,
            0x48, 0x8b, 0x4c, 0x24, 0x28,
            0x48, 0x8b, 0x54, 0x24, 0x30,
            0x48, 0x8b, 0x44, 0x24, 0x38,
            0x41, 0xb8, 0x01, 0x00, 0x00, 0x00,
            0x45, 0x33, 0xc9,
            0xff, 0x90, 0x48, 0x01, 0x00, 0x00,
            0x48, 0x83, 0xc4, 0x48, 0xc3
        };

        [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr FindWindowW(string lpClassName, string lpWindowName);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr OpenProcess(uint dwDesiredAccess, [MarshalAs(UnmanagedType.Bool)] bool bInheritHandle, int dwProcessId);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool CloseHandle(IntPtr hObject);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool K32EnumProcessModules(IntPtr hProcess, out IntPtr lphModule, uint cb, out uint lpcbNeeded);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool ReadProcessMemory(IntPtr hProcess, IntPtr lpBaseAddress, [Out] byte[] lpBuffer, UIntPtr nSize, out UIntPtr lpNumberOfBytesRead);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool WriteProcessMemory(IntPtr hProcess, IntPtr lpBaseAddress, byte[] lpBuffer, UIntPtr nSize, out UIntPtr lpNumberOfBytesWritten);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool VirtualProtectEx(IntPtr hProcess, IntPtr lpBaseAddress, UIntPtr dwSize, uint flNewProtect, out uint lpflOldProtect);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr VirtualAllocEx(IntPtr hProcess, IntPtr lpAddress, UIntPtr dwSize, uint flAllocationType, uint flProtect);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool FlushInstructionCache(IntPtr hProcess, IntPtr lpBaseAddress, UIntPtr dwSize);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool VirtualFreeEx(IntPtr hProcess, IntPtr lpAddress, UIntPtr dwSize, uint dwFreeType);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr CreateRemoteThread(IntPtr hProcess, IntPtr lpThreadAttributes, UIntPtr dwStackSize,
            IntPtr lpStartAddress, IntPtr lpParameter, uint dwCreationFlags, out uint lpThreadId);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern uint WaitForSingleObject(IntPtr hHandle, uint dwMilliseconds);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr GetModuleHandleW(string lpModuleName);

        [DllImport("kernel32.dll", CharSet = CharSet.Ansi, SetLastError = true)]
        private static extern IntPtr GetProcAddress(IntPtr hModule, string lpProcName);

        internal static bool HasRuntimeDllAvailable()
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            if (File.Exists(Path.Combine(baseDir, "tew1_dyn_runtime.dll"))) return true;
            var asm = typeof(NativeLoader).Assembly;
            return asm.GetManifestResourceInfo("tew1_dyn_runtime.dll") != null;
        }

        internal static string FindRuntimePack(string overlayDirectory)
        {
            if (String.IsNullOrWhiteSpace(overlayDirectory)) return null;
            string inOverlay = Path.Combine(overlayDirectory, "base", "generated", "tew1_dyn.bin");
            return File.Exists(inOverlay) ? inOverlay : null;
        }

        private static string ResolveRuntimeDll()
        {
            string besideExe = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "tew1_dyn_runtime.dll");
            if (File.Exists(besideExe)) return besideExe;

            var asm = typeof(NativeLoader).Assembly;
            using (Stream res = asm.GetManifestResourceStream("tew1_dyn_runtime.dll"))
            {
                if (res == null) return null;
                byte[] embedded = new byte[res.Length];
                int offset = 0;
                while (offset < embedded.Length)
                {
                    int n = res.Read(embedded, offset, embedded.Length - offset);
                    if (n <= 0) break;
                    offset += n;
                }

                string rtDir = Path.Combine(Library.DefaultRoot, "runtime");
                Directory.CreateDirectory(rtDir);
                string dst = Path.Combine(rtDir, "tew1_dyn_runtime.dll");
                bool needWrite = true;
                if (File.Exists(dst))
                {
                    try
                    {
                        byte[] existing = File.ReadAllBytes(dst);
                        if (existing.Length == embedded.Length)
                        {
                            bool same = true;
                            for (int i = 0; i < existing.Length; i++)
                            {
                                if (existing[i] != embedded[i]) { same = false; break; }
                            }
                            if (same) needWrite = false;
                        }
                    }
                    catch { }
                }
                if (needWrite)
                {
                    File.WriteAllBytes(dst, embedded);
                }
                return dst;
            }
        }

        private static bool InjectDll(int pid, string dllPath)
        {
            if (!File.Exists(dllPath)) return false;
            IntPtr hKernel = GetModuleHandleW("kernel32.dll");
            IntPtr pLoadLib = GetProcAddress(hKernel, "LoadLibraryW");
            if (pLoadLib == IntPtr.Zero) return false;

            // PROCESS_CREATE_THREAD(0x02) | VM_OPERATION(0x08) | VM_READ(0x10) | VM_WRITE(0x20) | QUERY_INFO(0x400) = 0x043A
            IntPtr proc = OpenProcess(0x043A, false, pid);
            if (proc == IntPtr.Zero) return false;
            try
            {
                byte[] pathBytes = Encoding.Unicode.GetBytes(Path.GetFullPath(dllPath) + "\0");
                IntPtr remoteBuf = VirtualAllocEx(proc, IntPtr.Zero, (UIntPtr)pathBytes.Length, MemCommitReserve, 0x04);
                if (remoteBuf == IntPtr.Zero) return false;
                try
                {
                    UIntPtr written;
                    if (!WriteProcessMemory(proc, remoteBuf, pathBytes, (UIntPtr)pathBytes.Length, out written))
                        return false;
                    uint tid;
                    IntPtr thread = CreateRemoteThread(proc, IntPtr.Zero, UIntPtr.Zero, pLoadLib, remoteBuf, 0, out tid);
                    if (thread == IntPtr.Zero) return false;
                    try
                    {
                        return WaitForSingleObject(thread, 10000) == 0;
                    }
                    finally { CloseHandle(thread); }
                }
                finally { VirtualFreeEx(proc, remoteBuf, UIntPtr.Zero, 0x8000); }
            }
            finally { CloseHandle(proc); }
        }

        internal static bool IsGameWindowOpen()
        {
            return FindWindowW("The Evil Within", null) != IntPtr.Zero ||
                   FindWindowW("The Evil Within WinConsole", null) != IntPtr.Zero;
        }

        internal static string ComputeSha256(string filePath)
        {
            using (var stream = new FileStream(filePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            using (var sha = SHA256.Create())
            {
                byte[] hash = sha.ComputeHash(stream);
                var sb = new StringBuilder(hash.Length * 2);
                for (int i = 0; i < hash.Length; i++)
                    sb.Append(hash[i].ToString("x2"));
                return sb.ToString();
            }
        }

        internal static GameValidationResult InspectGameDirectory(string directory)
        {
            if (String.IsNullOrWhiteSpace(directory))
            {
                return new GameValidationResult
                {
                    State = GameCheckState.NotConfigured,
                    NormalizedPath = "",
                    Message = "尚未设置游戏目录"
                };
            }

            string root;
            try { root = Path.GetFullPath(directory.Trim()); }
            catch
            {
                return new GameValidationResult
                {
                    State = GameCheckState.MissingFiles,
                    NormalizedPath = directory,
                    Message = "游戏目录路径格式无效"
                };
            }

            string exePath = Path.Combine(root, "EvilWithin.exe");
            string archivePath = Path.Combine(root, "base", "common.tangoresource");
            if (!File.Exists(exePath) || !File.Exists(archivePath))
            {
                return new GameValidationResult
                {
                    State = GameCheckState.MissingFiles,
                    NormalizedPath = root,
                    Message = "找不到 EvilWithin.exe 或 base\\common.tangoresource"
                };
            }

            try
            {
                string sha = ComputeSha256(exePath);
                if (!String.Equals(sha, SupportedExeSha256, StringComparison.OrdinalIgnoreCase))
                {
                    return new GameValidationResult
                    {
                        State = GameCheckState.UnsupportedBuild,
                        NormalizedPath = root,
                        Sha256 = sha,
                        Message = "EvilWithin.exe 版本不匹配（SHA-256 校验未通过）"
                    };
                }

                return new GameValidationResult
                {
                    State = GameCheckState.Ready,
                    NormalizedPath = root,
                    Sha256 = sha,
                    Message = "已校验 · 支持的 Windows x64 构建"
                };
            }
            catch (Exception ex)
            {
                return new GameValidationResult
                {
                    State = GameCheckState.MissingFiles,
                    NormalizedPath = root,
                    Message = "无法读取 EvilWithin.exe：" + ex.Message
                };
            }
        }

        internal static bool ArePathsNestedOrEqual(string pathA, string pathB)
        {
            string a = Path.GetFullPath(pathA).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            string b = Path.GetFullPath(pathB).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            if (String.Equals(a, b, StringComparison.OrdinalIgnoreCase)) return true;
            string aSlash = a + Path.DirectorySeparatorChar;
            string bSlash = b + Path.DirectorySeparatorChar;
            return aSlash.StartsWith(bSlash, StringComparison.OrdinalIgnoreCase) ||
                   bSlash.StartsWith(aSlash, StringComparison.OrdinalIgnoreCase);
        }

        internal static string QuoteArgument(string argument)
        {
            if (argument == null) throw new ArgumentNullException("argument");
            if (argument.Contains("\"")) throw new ArgumentException("路径包含非法引号字符。");
            return "\"" + (argument.EndsWith("\\") ? argument + "\\" : argument) + "\"";
        }

        internal static int LaunchVanilla(string gameDirectory, string extraArguments)
        {
            string game = Library.ValidateGame(gameDirectory);
            if (IsGameWindowOpen())
                throw new InvalidOperationException("游戏窗口已经打开。请先关闭游戏，再重新启动。");

            string exePath = Path.Combine(game, "EvilWithin.exe");
            var info = new ProcessStartInfo
            {
                FileName = exePath,
                Arguments = String.IsNullOrWhiteSpace(extraArguments) ? "" : extraArguments.Trim(),
                WorkingDirectory = game,
                UseShellExecute = false
            };
            Process child = Process.Start(info);
            if (child == null)
                throw new InvalidOperationException("无法启动 EvilWithin.exe。");
            return child.Id;
        }

        internal static string LaunchWithOverlay(
            string gameDirectory,
            string overlayDirectory,
            string saveRoot = null,
            string cacheRoot = null,
            string extraArguments = null,
            int timeoutMs = 20000,
            bool enableHairPhysics = true,
            bool enableIndependentFace = true)
        {
            if (IntPtr.Size != 8)
                throw new InvalidOperationException("需要 64 位 Windows 环境以运行加载器。");

            string game = Library.ValidateGame(gameDirectory);
            string overlay = Library.ValidateOverlay(overlayDirectory);

            if (ArePathsNestedOrEqual(game, overlay))
                throw new InvalidDataException("Mod 挂载目录不能与游戏目录相同或互相嵌套。请勿将本程序直接放在游戏根目录内部。");

            if (IsGameWindowOpen())
                throw new InvalidOperationException("游戏窗口已经打开。请先关闭游戏，再启动 Mod。");

            string exePath = Path.Combine(game, "EvilWithin.exe");
            string actualSha = ComputeSha256(exePath);
            if (!String.Equals(actualSha, SupportedExeSha256, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException(
                    "当前 EvilWithin.exe 版本与此加载器不匹配。\n" +
                    "期望 SHA-256：" + SupportedExeSha256 + "\n" +
                    "当前 SHA-256：" + actualSha);
            }

            using (var mutex = new Mutex(false, @"Local\TEW1LooseOverlayLaunch"))
            {
                bool acquired;
                try { acquired = mutex.WaitOne(0); }
                catch (AbandonedMutexException) { acquired = true; }
                if (!acquired)
                    throw new InvalidOperationException("已有一个 Mod 正在启动中，请稍候。");

                try
                {
                    var args = new List<string>();
                    args.Add("+set fs_basepath " + QuoteArgument(game));
                    args.Add("+set fs_installpath " + QuoteArgument(overlay));

                    if (!String.IsNullOrWhiteSpace(saveRoot))
                    {
                        string resolvedSave = Path.GetFullPath(saveRoot);
                        Directory.CreateDirectory(resolvedSave);
                        args.Add("+set fs_savepath " + QuoteArgument(resolvedSave));
                    }
                    if (!String.IsNullOrWhiteSpace(cacheRoot))
                    {
                        string resolvedCache = Path.GetFullPath(cacheRoot);
                        Directory.CreateDirectory(resolvedCache);
                        args.Add("+set fs_cachepath " + QuoteArgument(resolvedCache));
                    }
                    if (!String.IsNullOrWhiteSpace(extraArguments))
                    {
                        args.Add(extraArguments.Trim());
                    }
                    args.Add("+set resource_loadLooseFiles 1");

                    var startInfo = new ProcessStartInfo
                    {
                        FileName = exePath,
                        Arguments = String.Join(" ", args),
                        WorkingDirectory = game,
                        UseShellExecute = false
                    };

                    // Generic Mod-side dynamic physics & facial morph extension (activated only if Mod contains base/generated/tew1_dyn.bin)
                    string runtimePack = FindRuntimePack(overlay);
                    bool anyEnabled = enableHairPhysics || enableIndependentFace;
                    string runtimeDll = (runtimePack != null && anyEnabled) ? ResolveRuntimeDll() : null;
                    bool wantRuntime = runtimeDll != null && runtimePack != null;
                    if (wantRuntime)
                    {
                        startInfo.EnvironmentVariables["TEW1_DYN_PACK"] = runtimePack;
                        startInfo.EnvironmentVariables["TEW1_DYN_HAIR"] = enableHairPhysics ? "1" : "0";
                        startInfo.EnvironmentVariables["TEW1_DYN_FACE"] = enableIndependentFace ? "1" : "0";
                    }

                    Process child = Process.Start(startInfo);
                    if (child == null)
                        throw new InvalidOperationException("无法启动 EvilWithin.exe 进程。");

                    bool hasTextures = Directory.Exists(Path.Combine(overlay, "base", "generated", "textures"));
                    bool hasSounds = Directory.Exists(Path.Combine(overlay, "base", "sound"));
                    try
                    {
                        EnableOverlay(child, hasTextures, hasSounds, timeoutMs);
                    }
                    catch
                    {
                        try
                        {
                            if (!child.HasExited)
                            {
                                child.Kill();
                                child.WaitForExit(3000);
                            }
                        }
                        catch { }
                        throw;
                    }

                    bool runtimeLoaded = false;
                    if (wantRuntime)
                    {
                        runtimeLoaded = InjectDll(child.Id, runtimeDll);
                    }

                    return String.Format("Loose resources enabled for EvilWithin.exe (PID {0}, textures={1}, sounds={2}, runtime={3}).",
                        child.Id, hasTextures ? "on" : "off", hasSounds ? "on" : "off", runtimeLoaded ? "on" : "off");
                }
                finally
                {
                    mutex.ReleaseMutex();
                }
            }
        }

        private static void EnableOverlay(Process child, bool hasTextures, bool hasSounds, int timeoutMs)
        {
            var stopwatch = Stopwatch.StartNew();
            using (var proc = new GameProcessHandle(child.Id))
            {
                while (stopwatch.ElapsedMilliseconds < timeoutMs && !child.HasExited)
                {
                    long imageBase = proc.GetImageBase();
                    if (imageBase != 0)
                    {
                        byte[] current = proc.Read(imageBase + LooseResourceCheckOffset, StockCheck.Length);
                        if (BytesEqual(current, StockCheck))
                        {
                            var siteList = new List<long> { ModelOpenCallOffset };
                            if (hasTextures) siteList.Add(ImageOpenCallOffset);
                            if (hasSounds) siteList.Add(WaveOpenCallOffset);

                            long allocated = proc.InstallResourceOpen(imageBase, siteList.ToArray());
                            if (hasSounds)
                            {
                                proc.InstallSoundLoadHook(imageBase, allocated + 0x100);
                            }

                            byte limit = (hasTextures || hasSounds) ? (byte)0x05 : (byte)0x04;
                            byte[] expected = (byte[])StockCheck.Clone();
                            expected[ProductionLimitIndex] = limit;

                            proc.WriteCode(imageBase + LooseResourceCheckOffset + ProductionLimitIndex, new byte[] { limit });

                            byte[] verify = proc.Read(imageBase + LooseResourceCheckOffset, StockCheck.Length);
                            if (!BytesEqual(verify, expected))
                                throw new IOException("游戏内存中的资源检查位未保持预期修改。");

                            return;
                        }
                    }
                    Thread.Sleep(25);
                }
            }

            string exitInfo = child.HasExited ? child.ExitCode.ToString() : "仍在运行";
            throw new InvalidOperationException("未能在超时时间内定位到受支持的游戏资源读取入口（进程状态：" + exitInfo + "）。");
        }

        private static bool BytesEqual(byte[] a, byte[] b)
        {
            if (a == null || b == null || a.Length != b.Length) return false;
            for (int i = 0; i < a.Length; i++)
                if (a[i] != b[i]) return false;
            return true;
        }

        private sealed class GameProcessHandle : IDisposable
        {
            private IntPtr handle;

            public GameProcessHandle(int pid)
            {
                handle = OpenProcess(ProcessAccess, false, pid);
                if (handle == IntPtr.Zero)
                    throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "无法打开游戏进程句柄（OpenProcess 失败）。");
            }

            public long GetImageBase()
            {
                IntPtr firstModule;
                uint needed;
                if (!K32EnumProcessModules(handle, out firstModule, (uint)IntPtr.Size, out needed))
                    return 0;
                return firstModule.ToInt64();
            }

            public byte[] Read(long address, int count)
            {
                byte[] buffer = new byte[count];
                UIntPtr read;
                if (!ReadProcessMemory(handle, new IntPtr(address), buffer, (UIntPtr)count, out read))
                    return new byte[0];
                int actual = (int)read.ToUInt64();
                if (actual == count) return buffer;
                byte[] sliced = new byte[actual];
                Buffer.BlockCopy(buffer, 0, sliced, 0, actual);
                return sliced;
            }

            public void WriteCode(long address, byte[] data)
            {
                uint oldProtect;
                IntPtr ptr = new IntPtr(address);
                UIntPtr size = (UIntPtr)data.Length;
                if (!VirtualProtectEx(handle, ptr, size, PageExecuteReadWrite, out oldProtect))
                    throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "VirtualProtectEx 修改内存保护失败。");
                try
                {
                    UIntPtr written;
                    if (!WriteProcessMemory(handle, ptr, data, size, out written))
                        throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "WriteProcessMemory 写入内存失败。");
                    if ((int)written.ToUInt64() != data.Length || !FlushInstructionCache(handle, ptr, size))
                        throw new IOException("游戏进程指令缓存刷新失败。");
                }
                finally
                {
                    uint unused;
                    if (!VirtualProtectEx(handle, ptr, size, oldProtect, out unused))
                        throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "VirtualProtectEx 恢复内存保护失败。");
                }
            }

            public long InstallResourceOpen(long imageBase, long[] sites)
            {
                foreach (long siteOffset in sites)
                {
                    byte[] actual = Read(imageBase + siteOffset, StockModelOpen.Length);
                    if (!BytesEqual(actual, StockModelOpen))
                        throw new InvalidOperationException("资源读取调用点特征码与受支持的构建不匹配。");
                }

                long allocated = 0;
                for (long delta = 0x10000000L; delta < 0x70000000L; delta += 0x10000L)
                {
                    IntPtr result = VirtualAllocEx(handle, new IntPtr(imageBase + delta), (UIntPtr)4096, MemCommitReserve, PageExecuteRead);
                    if (result != IntPtr.Zero)
                    {
                        allocated = result.ToInt64();
                        break;
                    }
                }
                if (allocated == 0)
                    throw new InvalidOperationException("无法在模型资源读取器附近分配可执行内存页。");

                WriteCode(allocated, ModelOpenOverlay);

                foreach (long siteOffset in sites)
                {
                    long site = imageBase + siteOffset;
                    int rel32 = checked((int)(allocated - site - 5));
                    byte[] relBytes = BitConverter.GetBytes(rel32);
                    byte[] instruction = new byte[6];
                    instruction[0] = 0xE8;
                    Buffer.BlockCopy(relBytes, 0, instruction, 1, 4);
                    instruction[5] = 0x90;

                    WriteCode(site, instruction);

                    byte[] check = Read(site, instruction.Length);
                    if (!BytesEqual(check, instruction))
                        throw new IOException("资源读取器跳转指令校验失败。");
                }

                return allocated;
            }

            public void InstallSoundLoadHook(long imageBase, long stubAddress)
            {
                long langSite = imageBase + WaveLangSubCallOffset;
                byte[] langActual = Read(langSite, StockWaveLangSubCall.Length);
                if (!BytesEqual(langActual, StockWaveLangSubCall))
                    throw new InvalidOperationException("音频语言路径调用点特征码与受支持的构建不匹配。");
                WriteCode(langSite, PatchWaveLangBypass);
                if (!BytesEqual(Read(langSite, PatchWaveLangBypass.Length), PatchWaveLangBypass))
                    throw new IOException("音频语言路径补丁校验失败。");

                long callSite = imageBase + SoundLoadCallOffset;
                byte[] actual = Read(callSite, StockSoundLoadCall.Length);
                if (!BytesEqual(actual, StockSoundLoadCall))
                    throw new InvalidOperationException("音频加载调用点特征码与受支持的构建不匹配。");

                byte[] stub = (byte[])SoundLoadOverlayTemplate.Clone();
                int relLoadWav = checked((int)((imageBase + SoundLoadWavOffset) - (stubAddress + 0x26)));
                int relLoadGen = checked((int)((imageBase + SoundLoadGeneratedOffset) - (stubAddress + 0x57)));
                Buffer.BlockCopy(BitConverter.GetBytes(relLoadWav), 0, stub, 0x22, 4);
                Buffer.BlockCopy(BitConverter.GetBytes(relLoadGen), 0, stub, 0x53, 4);

                WriteCode(stubAddress, stub);

                int relCall = checked((int)(stubAddress - callSite - 5));
                byte[] patch = new byte[5];
                patch[0] = 0xE8;
                Buffer.BlockCopy(BitConverter.GetBytes(relCall), 0, patch, 1, 4);

                WriteCode(callSite, patch);

                byte[] check = Read(callSite, patch.Length);
                if (!BytesEqual(check, patch))
                    throw new IOException("音频加载跳转指令校验失败。");
            }

            public void Dispose()
            {
                if (handle != IntPtr.Zero)
                {
                    CloseHandle(handle);
                    handle = IntPtr.Zero;
                }
            }
        }
    }
}
