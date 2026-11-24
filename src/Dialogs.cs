using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shell;

namespace TEW1
{
    internal enum DialogKind
    {
        Info,
        Warning,
        ConfirmDanger
    }

    internal static class ModernDialog
    {
        internal static bool Show(Window owner, string title, string message, DialogKind kind, string confirmText = "确定", string cancelText = "取消")
        {
            var dlg = new Window
            {
                Title = title,
                Width = 440,
                SizeToContent = SizeToContent.Height,
                ResizeMode = ResizeMode.NoResize,
                WindowStyle = WindowStyle.None,
                WindowStartupLocation = owner != null ? WindowStartupLocation.CenterOwner : WindowStartupLocation.CenterScreen,
                Owner = owner,
                Background = AppTheme.Brush("#141923"),
                Foreground = AppTheme.Brush("#F1F5F9"),
                FontFamily = new FontFamily("Segoe UI Variable Text, Microsoft YaHei UI, Segoe UI"),
                ShowInTaskbar = owner == null
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

            bool result = false;

            var outer = new Border
            {
                BorderBrush = AppTheme.Brush("#2B3548"),
                BorderThickness = new Thickness(1),
                Background = AppTheme.Brush("#141923"),
                Padding = new Thickness(22, 18, 22, 18)
            };

            var stack = new StackPanel();

            var header = new DockPanel { Margin = new Thickness(0, 0, 0, 12) };
            string accentHex = kind == DialogKind.Info ? "#4DA3FF" : (kind == DialogKind.Warning ? "#E8A838" : "#DC3545");
            string softHex = kind == DialogKind.Info ? "#142338" : (kind == DialogKind.Warning ? "#292113" : "#2A161B");
            string iconPath = kind == DialogKind.Info
                ? "M12,2 A10,10 0 1,0 22,12 A10,10 0 0,0 12,2 Z M12,10 L12,16 M12,7 L12,7.5"
                : "M12,3 L22,20 L2,20 Z M12,9 L12,14 M12,17 L12,17.5";

            var iconBadge = new Border
            {
                Width = 34,
                Height = 34,
                CornerRadius = new CornerRadius(9),
                Background = AppTheme.Brush(softHex),
                Margin = new Thickness(0, 0, 12, 0),
                Child = AppTheme.Icon(iconPath, 17, AppTheme.Brush(accentHex), false)
            };
            DockPanel.SetDock(iconBadge, Dock.Left);
            header.Children.Add(iconBadge);

            header.Children.Add(new TextBlock
            {
                Text = title,
                FontSize = 15.5,
                FontWeight = FontWeights.SemiBold,
                Foreground = AppTheme.Brush("#F1F5F9"),
                VerticalAlignment = VerticalAlignment.Center
            });
            stack.Children.Add(header);

            var scroll = new ScrollViewer
            {
                MaxHeight = 260,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                Margin = new Thickness(0, 0, 0, 18),
                Content = new TextBlock
                {
                    Text = message,
                    TextWrapping = TextWrapping.Wrap,
                    FontSize = 13,
                    LineHeight = 20,
                    Foreground = AppTheme.Brush("#CBD5E1")
                }
            };
            stack.Children.Add(scroll);

            var buttons = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Right
            };

            if (kind == DialogKind.ConfirmDanger)
            {
                var cancelBtn = new Button
                {
                    Content = cancelText,
                    Style = (Style)dlg.FindResource("SecondaryButton"),
                    MinWidth = 84,
                    Margin = new Thickness(0, 0, 10, 0),
                    IsCancel = true
                };
                cancelBtn.Click += delegate { result = false; dlg.Close(); };
                buttons.Children.Add(cancelBtn);
            }

            var okBtn = new Button
            {
                Content = confirmText,
                Style = (Style)dlg.FindResource(kind == DialogKind.ConfirmDanger ? "PrimaryButton" : "SecondaryButton"),
                MinWidth = 88,
                IsDefault = true
            };
            okBtn.Click += delegate { result = true; dlg.Close(); };
            buttons.Children.Add(okBtn);

            stack.Children.Add(buttons);
            outer.Child = stack;
            dlg.Content = outer;

            dlg.KeyDown += delegate(object sender, KeyEventArgs e)
            {
                if (e.Key == Key.Escape)
                {
                    result = false;
                    dlg.Close();
                }
            };

            dlg.ShowDialog();
            return result;
        }
    }
}
