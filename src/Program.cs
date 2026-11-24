using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Windows;

namespace TEW1
{
    internal static class Program
    {
        [STAThread]
        internal static int Main(string[] args)
        {
            if (args != null && args.Length >= 1 && String.Equals(args[0], "--launch", StringComparison.OrdinalIgnoreCase))
            {
                return RunCliLaunch(args);
            }

            var app = new Application
            {
                ShutdownMode = ShutdownMode.OnMainWindowClose
            };

            string[] incoming = (args ?? new string[0])
                .Where(p => !String.IsNullOrWhiteSpace(p) && (File.Exists(p) || Directory.Exists(p)))
                .ToArray();

            var window = new MainWindow(null, incoming);
            app.Run(window);
            return 0;
        }

        private static int RunCliLaunch(string[] args)
        {
            string game = null;
            string overlay = null;
            string saveRoot = null;
            string cacheRoot = null;
            var extra = new List<string>();

            // Support original positional form: --launch <game> <overlay>
            // And optional flags: --save-root <dir> --cache-root <dir>
            var positional = new List<string>();
            for (int i = 1; i < args.Length; i++)
            {
                string arg = args[i];
                if (String.Equals(arg, "--save-root", StringComparison.OrdinalIgnoreCase) && i + 1 < args.Length)
                    saveRoot = args[++i];
                else if (String.Equals(arg, "--cache-root", StringComparison.OrdinalIgnoreCase) && i + 1 < args.Length)
                    cacheRoot = args[++i];
                else if (String.Equals(arg, "--game", StringComparison.OrdinalIgnoreCase) && i + 1 < args.Length)
                    game = args[++i];
                else if (String.Equals(arg, "--overlay", StringComparison.OrdinalIgnoreCase) && i + 1 < args.Length)
                    overlay = args[++i];
                else
                    positional.Add(arg);
            }

            if (game == null && positional.Count >= 1) game = positional[0];
            if (overlay == null && positional.Count >= 2) overlay = positional[1];
            if (positional.Count > 2) extra.AddRange(positional.Skip(2));

            if (String.IsNullOrWhiteSpace(game) || String.IsNullOrWhiteSpace(overlay))
            {
                ModernDialog.Show(null, "参数格式错误",
                    "命令行用法：\nTEW1ModManager.exe --launch <游戏目录> <Mod挂载目录> [--save-root <存档目录>] [--cache-root <缓存目录>]",
                    DialogKind.Warning, "知道了");
                return 2;
            }

            try
            {
                NativeLoader.LaunchWithOverlay(game, overlay, saveRoot, cacheRoot, String.Join(" ", extra));
                return 0;
            }
            catch (Exception ex)
            {
                ModernDialog.Show(null, "Mod 加载器启动失败", ex.Message, DialogKind.Warning, "知道了");
                return 1;
            }
        }
    }
}
