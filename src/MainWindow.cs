using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Shapes;
using System.Windows.Shell;
using Microsoft.Win32;

namespace TEW1
{
    internal sealed class MainWindow : Window
    {
        // Crisp vector icon paths (24x24 viewbox coordinates)
        private const string IconFolder = "M3,6 C3,4.9 3.9,4 5,4 L9.5,4 L11.5,6.5 L19,6.5 C20.1,6.5 21,7.4 21,8.5 L21,18 C21,19.1 20.1,20 19,20 L5,20 C3.9,20 3,19.1 3,18 Z";
        private const string IconZip = "M5,3 L14,3 L19,8 L19,20 C19,20.6 18.6,21 18,21 L6,21 C5.4,21 5,20.6 5,20 Z M14,3 L14,8 L19,8 M10,11 L14,11 M10,14 L14,14 M10,17 L14,17";
        private const string IconLink = "M10,13 A4.5,4.5 0 0,0 16.5,13 L19,10.5 A4.5,4.5 0 0,0 12.6,4.1 L11,5.7 M14,11 A4.5,4.5 0 0,0 7.5,11 L5,13.5 A4.5,4.5 0 0,0 11.4,19.9 L13,18.3";
        private const string IconPlay = "M7,5.5 L19,12 L7,18.5 Z";
        private const string IconTrash = "M4,7 L20,7 M9,7 L9,4 L15,4 L15,7 M6,7 L7,20 C7,20.6 7.4,21 8,21 L16,21 C16.6,21 17,20.6 17,20 L18,7 M10,11 L10,17 M14,11 L14,17";
        private const string IconExternal = "M14,4 L20,4 L20,10 M20,4 L11,13 M17,13 L17,19 C17,19.6 16.6,20 16,20 L5,20 C4.4,20 4,19.6 4,19 L4,8 C4,7.4 4.4,7 5,7 L11,7";
        private const string IconSearch = "M10.5,4 A6.5,6.5 0 1,0 10.5,17 A6.5,6.5 0 1,0 10.5,4 Z M15.5,15.5 L20,20";
        private const string IconRefresh = "M20,12 A8,8 0 1,1 17.6,6.3 M20,4 L20,9 L15,9";
        private const string IconUpload = "M12,16 L12,5 M7.5,9.5 L12,5 L16.5,9.5 M4,16 L4,18.5 C4,19.3 4.7,20 5.5,20 L18.5,20 C19.3,20 20,19.3 20,18.5 L20,16";
        private const string IconCopy = "M9,9 L19,9 L19,19 L9,19 Z M5,15 L5,5 L15,5";
        private const string IconSpark = "M12,3 L14.2,9.8 L21,12 L14.2,14.2 L12,21 L9.8,14.2 L3,12 L9.8,9.8 Z";
        private const string IconChevronDown = "M6,9 L12,15 L18,9";
        private const string IconChevronUp = "M6,15 L12,9 L18,15";

        private readonly Library library;
        private readonly string[] startupPaths;
        private List<ModEntry> allEntries = new List<ModEntry>();
        private GameValidationResult gameStatus = new GameValidationResult { State = GameCheckState.NotConfigured };
        private bool isBusy;
        private bool advancedOpen;

        // UI Elements
        private Grid rootGrid;
        private Button maxRestoreBtn;
        private TextBlock gamePathText;
        private Border gameBadgeBorder;
        private Ellipse gameBadgeDot;
        private TextBlock gameBadgeText;
        private Button detectGameBtn;
        private Button chooseGameBtn;

        private TextBlock countBadgeText;
        private Button refreshBtn;
        private Button importZipBtn;
        private Button linkFolderBtn;
        private TextBox searchBox;
        private TextBlock searchPlaceholder;
        private Button clearSearchBtn;
        private ListBox modListBox;
        private Border emptyStateCard;
        private TextBlock emptyTitleText;
        private TextBlock emptySubtitleText;

        private Grid detailPanel;
        private Grid welcomePanel;
        private Border modePill;
        private TextBlock modePillText;
        private Border hookPill;
        private TextBlock hookPillText;
        private Border dynPill;
        private Button openFolderBtn;
        private Button removeBtn;
        private TextBlock removeBtnText;
        private TextBlock detailTitle;
        private TextBlock detailSubtitle;
        private Border missingBanner;
        private TextBlock statCard1Title;
        private TextBlock statCard1Sub;
        private TextBlock statCard2Title;
        private TextBlock statCard2Sub;
        private TextBlock statModelsText;
        private TextBlock statTexturesText;
        private TextBlock statSizeText;
        private TextBlock statFilesSubText;
        private TextBlock detailPathText;
        private TextBlock detailMechanismText;
        private Border activeAddonsBanner;
        private TextBlock activeAddonsBannerText;
        private Button advancedToggleBtn;
        private UIElement advancedChevron;
        private Border advancedBody;
        private TextBox extraArgsBox;
        private CheckBox hairPhysicsToggle;
        private CheckBox independentFaceToggle;
        private Border extCard;
        private Border extStatusPill;
        private TextBlock extStatusPillText;
        private Button launchModBtn;
        private Border launchModIconWrap;
        private TextBlock launchModBtnText;
        private Button launchVanillaBtn;
        private Button welcomeVanillaBtn;

        private Ellipse statusDot;
        private TextBlock statusText;

        private Border dragOverlay;
        private TextBlock dragOverlayTitle;
        private TextBlock dragOverlaySub;

        internal MainWindow(Library library = null, string[] startupArgs = null)
        {
            this.library = library ?? new Library();
            this.startupPaths = startupArgs ?? new string[0];

            Title = "恶灵附身 · Mod 管理器 & 加载器";
            Width = 1000;
            Height = 762;
            MinWidth = 840;
            MinHeight = 600;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            WindowStyle = WindowStyle.None;
            ResizeMode = ResizeMode.CanResize;
            Background = AppTheme.Brush("#0D1016");
            Foreground = AppTheme.Brush("#F1F5F9");
            FontFamily = new FontFamily("Segoe UI Variable Text, Microsoft YaHei UI, Segoe UI");
            AllowDrop = true;

            Resources.MergedDictionaries.Add(AppTheme.CreateResources());
            AppTheme.ApplyModernWindowChrome(this);
            WindowChrome.SetWindowChrome(this, new WindowChrome
            {
                CaptionHeight = 46,
                CornerRadius = new CornerRadius(10),
                GlassFrameThickness = new Thickness(0),
                ResizeBorderThickness = new Thickness(6),
                UseAeroCaptionButtons = false
            });

            BuildLayout();

            StateChanged += delegate { UpdateMaximizeState(); };
            PreviewDragEnter += OnWindowDragOver;
            PreviewDragOver += OnWindowDragOver;
            PreviewDragLeave += OnWindowDragLeave;
            PreviewDrop += OnWindowDrop;
            Loaded += OnWindowLoaded;
        }

        private void BuildLayout()
        {
            rootGrid = new Grid { Background = AppTheme.Brush("#0D1016") };

            // Subtle atmospheric crimson glow in top-right corner
            var ambientGlow = new Border
            {
                IsHitTestVisible = false,
                HorizontalAlignment = HorizontalAlignment.Right,
                VerticalAlignment = VerticalAlignment.Top,
                Width = 520,
                Height = 280,
                Background = new RadialGradientBrush
                {
                    GradientOrigin = new Point(0.85, 0.1),
                    Center = new Point(0.85, 0.1),
                    RadiusX = 0.85,
                    RadiusY = 0.85,
                    GradientStops = new GradientStopCollection
                    {
                        new GradientStop(Color.FromArgb(30, 220, 53, 69), 0.0),
                        new GradientStop(Color.FromArgb(0, 220, 53, 69), 1.0)
                    }
                }
            };
            rootGrid.Children.Add(ambientGlow);

            var mainShell = new Grid();
            mainShell.RowDefinitions.Add(new RowDefinition { Height = new GridLength(48) });
            mainShell.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            mainShell.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            mainShell.RowDefinitions.Add(new RowDefinition { Height = new GridLength(34) });
            rootGrid.Children.Add(mainShell);

            // Row 0: Title Bar
            UIElement titleBar = BuildTitleBar();
            Grid.SetRow(titleBar, 0);
            mainShell.Children.Add(titleBar);

            // Row 1: Game Directory Bar
            UIElement gameBar = BuildGameBar();
            Grid.SetRow(gameBar, 1);
            mainShell.Children.Add(gameBar);

            // Row 2: Split Workspace
            var splitGrid = new Grid { Margin = new Thickness(18, 12, 18, 10) };
            splitGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(0.95, GridUnitType.Star), MinWidth = 315 });
            splitGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(14) });
            splitGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1.25, GridUnitType.Star), MinWidth = 400 });

            UIElement leftPane = BuildModListPane();
            Grid.SetColumn(leftPane, 0);
            splitGrid.Children.Add(leftPane);

            UIElement rightPane = BuildDetailPane();
            Grid.SetColumn(rightPane, 2);
            splitGrid.Children.Add(rightPane);

            Grid.SetRow(splitGrid, 2);
            mainShell.Children.Add(splitGrid);

            // Row 3: Status Bar
            UIElement statusBar = BuildStatusBar();
            Grid.SetRow(statusBar, 3);
            mainShell.Children.Add(statusBar);

            // Full-window Drag Overlay
            dragOverlay = BuildDragOverlay();
            rootGrid.Children.Add(dragOverlay);

            Content = rootGrid;
        }

        private UIElement BuildTitleBar()
        {
            var bar = new DockPanel
            {
                Background = Brushes.Transparent,
                Margin = new Thickness(18, 0, 10, 0),
                LastChildFill = true
            };

            // Right window buttons
            var controls = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                VerticalAlignment = VerticalAlignment.Center
            };
            DockPanel.SetDock(controls, Dock.Right);

            var minBtn = new Button
            {
                Style = (Style)FindResource("CaptionButton"),
                Content = AppTheme.Icon("M6,12 L18,12", 11, AppTheme.Brush("#94A3B8"), false),
                ToolTip = "最小化"
            };
            WindowChrome.SetIsHitTestVisibleInChrome(minBtn, true);
            minBtn.Click += delegate { WindowState = WindowState.Minimized; };
            controls.Children.Add(minBtn);

            maxRestoreBtn = new Button
            {
                Style = (Style)FindResource("CaptionButton"),
                Content = AppTheme.Icon("M6,6 L18,6 L18,18 L6,18 Z", 10.5, AppTheme.Brush("#94A3B8"), false),
                ToolTip = "最大化"
            };
            WindowChrome.SetIsHitTestVisibleInChrome(maxRestoreBtn, true);
            maxRestoreBtn.Click += delegate
            {
                WindowState = WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized;
            };
            controls.Children.Add(maxRestoreBtn);

            var closeBtn = new Button
            {
                Style = (Style)FindResource("CloseCaptionButton"),
                Content = AppTheme.Icon("M6,6 L18,18 M18,6 L6,18", 10.5, AppTheme.Brush("#CBD5E1"), false),
                ToolTip = "关闭"
            };
            WindowChrome.SetIsHitTestVisibleInChrome(closeBtn, true);
            closeBtn.Click += delegate { Close(); };
            controls.Children.Add(closeBtn);

            bar.Children.Add(controls);

            // Left branding
            var brand = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                VerticalAlignment = VerticalAlignment.Center
            };

            var emblem = new Border
            {
                Width = 26,
                Height = 26,
                CornerRadius = new CornerRadius(7),
                Margin = new Thickness(0, 0, 10, 0),
                Background = new LinearGradientBrush(
                    (Color)ColorConverter.ConvertFromString("#E03A4B"),
                    (Color)ColorConverter.ConvertFromString("#8F1B28"),
                    45),
                Child = new TextBlock
                {
                    Text = "EW",
                    FontSize = 10.5,
                    FontWeight = FontWeights.Bold,
                    Foreground = Brushes.White,
                    HorizontalAlignment = HorizontalAlignment.Center,
                    VerticalAlignment = VerticalAlignment.Center
                }
            };
            brand.Children.Add(emblem);

            brand.Children.Add(new TextBlock
            {
                Text = "恶灵附身",
                FontSize = 14.5,
                FontWeight = FontWeights.SemiBold,
                Foreground = AppTheme.Brush("#F8FAFC"),
                VerticalAlignment = VerticalAlignment.Center
            });

            brand.Children.Add(new TextBlock
            {
                Text = "  Mod 管理器 & 加载器",
                FontSize = 13,
                Foreground = AppTheme.Brush("#94A3B8"),
                VerticalAlignment = VerticalAlignment.Center
            });

            var editionPill = new Border
            {
                Background = AppTheme.Brush("#1B2332"),
                BorderBrush = AppTheme.Brush("#2B374D"),
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(10),
                Padding = new Thickness(8, 2, 8, 2),
                Margin = new Thickness(10, 0, 0, 0),
                VerticalAlignment = VerticalAlignment.Center,
                Child = new TextBlock
                {
                    Text = "原生一体版",
                    FontSize = 10.5,
                    FontWeight = FontWeights.Medium,
                    Foreground = AppTheme.Brush("#94A3B8")
                }
            };
            brand.Children.Add(editionPill);

            bar.Children.Add(brand);
            return bar;
        }

        private UIElement BuildGameBar()
        {
            var card = new Border
            {
                Margin = new Thickness(18, 2, 18, 0),
                Padding = new Thickness(14, 10, 14, 10),
                Background = AppTheme.Brush("#141923"),
                BorderBrush = AppTheme.Brush("#232C3D"),
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(11)
            };

            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            var labelPanel = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(0, 0, 12, 0)
            };
            labelPanel.Children.Add(new Border
            {
                Width = 30,
                Height = 30,
                CornerRadius = new CornerRadius(8),
                Background = AppTheme.Brush("#1C2434"),
                Margin = new Thickness(0, 0, 10, 0),
                Child = AppTheme.Icon(IconFolder, 15, AppTheme.Brush("#94A3B8"), false)
            });
            labelPanel.Children.Add(new TextBlock
            {
                Text = "游戏目录",
                FontSize = 13,
                FontWeight = FontWeights.SemiBold,
                Foreground = AppTheme.Brush("#CBD5E1"),
                VerticalAlignment = VerticalAlignment.Center
            });
            Grid.SetColumn(labelPanel, 0);
            grid.Children.Add(labelPanel);

            gamePathText = new TextBlock
            {
                Text = "尚未选择包含 EvilWithin.exe 的游戏目录",
                FontSize = 12.5,
                Foreground = AppTheme.Brush("#64748B"),
                VerticalAlignment = VerticalAlignment.Center,
                TextTrimming = TextTrimming.CharacterEllipsis,
                Margin = new Thickness(0, 0, 12, 0)
            };
            Grid.SetColumn(gamePathText, 1);
            grid.Children.Add(gamePathText);

            // Verification status pill
            var badgeStack = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            gameBadgeDot = new Ellipse
            {
                Width = 7,
                Height = 7,
                Fill = AppTheme.Brush("#E8A838"),
                Margin = new Thickness(0, 0, 6, 0),
                VerticalAlignment = VerticalAlignment.Center
            };
            gameBadgeText = new TextBlock
            {
                Text = "未配置",
                FontSize = 11.5,
                FontWeight = FontWeights.Medium,
                Foreground = AppTheme.Brush("#E8A838"),
                VerticalAlignment = VerticalAlignment.Center
            };
            badgeStack.Children.Add(gameBadgeDot);
            badgeStack.Children.Add(gameBadgeText);

            gameBadgeBorder = new Border
            {
                Background = AppTheme.Brush("#292113"),
                BorderBrush = AppTheme.Brush("#664C1E"),
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(12),
                Padding = new Thickness(10, 4, 10, 4),
                Margin = new Thickness(0, 0, 10, 0),
                VerticalAlignment = VerticalAlignment.Center,
                Child = badgeStack
            };
            Grid.SetColumn(gameBadgeBorder, 2);
            grid.Children.Add(gameBadgeBorder);

            var btnRow = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            detectGameBtn = new Button
            {
                Style = (Style)FindResource("GhostButton"),
                Content = "自动检测",
                Margin = new Thickness(0, 0, 6, 0),
                ToolTip = "自动搜索附近与常见安装路径中的 EvilWithin.exe"
            };
            detectGameBtn.Click += delegate { AutoDetectGame(true); };
            btnRow.Children.Add(detectGameBtn);

            chooseGameBtn = new Button
            {
                Style = (Style)FindResource("SecondaryButton"),
                Content = "选择目录",
                Padding = new Thickness(13, 6, 13, 6)
            };
            chooseGameBtn.Click += delegate { ChooseGameDirectory(); };
            btnRow.Children.Add(chooseGameBtn);

            Grid.SetColumn(btnRow, 3);
            grid.Children.Add(btnRow);

            card.Child = grid;
            return card;
        }

        private UIElement BuildModListPane()
        {
            var card = new Border
            {
                Background = AppTheme.Brush("#141923"),
                BorderBrush = AppTheme.Brush("#232C3D"),
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(12),
                Padding = new Thickness(14, 14, 14, 12)
            };

            var grid = new Grid();
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            grid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });

            // Row 0: Header
            var header = new DockPanel { Margin = new Thickness(2, 0, 0, 12) };
            refreshBtn = new Button
            {
                Style = (Style)FindResource("GhostButton"),
                Padding = new Thickness(7, 6, 7, 6),
                Content = AppTheme.Icon(IconRefresh, 14, AppTheme.Brush("#94A3B8"), false),
                ToolTip = "刷新 Mod 列表与资源统计"
            };
            refreshBtn.Click += delegate
            {
                ModEntry sel = SelectedEntry();
                RefreshEntries(sel != null ? sel.Id : null);
                SetStatus("已刷新 Mod 列表。", "#2EC476");
            };
            DockPanel.SetDock(refreshBtn, Dock.Right);
            header.Children.Add(refreshBtn);

            var titleRow = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            titleRow.Children.Add(new TextBlock
            {
                Text = "模组库与直挂",
                FontSize = 14,
                FontWeight = FontWeights.SemiBold,
                Foreground = AppTheme.Brush("#F1F5F9"),
                VerticalAlignment = VerticalAlignment.Center
            });
            countBadgeText = new TextBlock
            {
                Text = "0",
                FontSize = 11.5,
                FontWeight = FontWeights.SemiBold,
                Foreground = AppTheme.Brush("#CBD5E1")
            };
            titleRow.Children.Add(new Border
            {
                Background = AppTheme.Brush("#1E2636"),
                CornerRadius = new CornerRadius(10),
                Padding = new Thickness(8, 1.5, 8, 1.5),
                Margin = new Thickness(8, 0, 0, 0),
                VerticalAlignment = VerticalAlignment.Center,
                Child = countBadgeText
            });
            header.Children.Add(titleRow);
            Grid.SetRow(header, 0);
            grid.Children.Add(header);

            // Row 1: Action buttons (Import ZIP + Direct Mount Folder)
            var actionGrid = new Grid { Margin = new Thickness(0, 0, 0, 10) };
            actionGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            actionGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(8) });
            actionGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

            importZipBtn = new Button
            {
                Style = (Style)FindResource("SecondaryButton"),
                Padding = new Thickness(10, 8, 10, 8),
                Content = IconLabel(IconZip, 14, "#F87171", "导入 ZIP", "#F1F5F9"),
                ToolTip = "导入一个或多个 Mod .zip 压缩包到管理器库中"
            };
            importZipBtn.Click += delegate { ChooseZipFiles(); };
            Grid.SetColumn(importZipBtn, 0);
            actionGrid.Children.Add(importZipBtn);

            linkFolderBtn = new Button
            {
                Style = (Style)FindResource("SecondaryButton"),
                Padding = new Thickness(10, 8, 10, 8),
                Content = IconLabel(IconLink, 14, "#E8A838", "直挂目录", "#F1F5F9"),
                ToolTip = "直接挂载含 base/generated 的已解压 Mod 文件夹（不复制文件）"
            };
            linkFolderBtn.Click += delegate { ChooseDirectFolder(); };
            Grid.SetColumn(linkFolderBtn, 2);
            actionGrid.Children.Add(linkFolderBtn);

            Grid.SetRow(actionGrid, 1);
            grid.Children.Add(actionGrid);

            // Row 2: Search Box
            var searchWrap = new Grid { Margin = new Thickness(0, 0, 0, 10) };
            searchBox = new TextBox
            {
                Style = (Style)FindResource("DarkTextBox"),
                Padding = new Thickness(30, 7, 28, 7),
                FontSize = 12.5
            };
            searchBox.TextChanged += delegate
            {
                bool hasText = !String.IsNullOrEmpty(searchBox.Text);
                searchPlaceholder.Visibility = hasText ? Visibility.Collapsed : Visibility.Visible;
                clearSearchBtn.Visibility = hasText ? Visibility.Visible : Visibility.Collapsed;
                ApplyFilter(SelectedEntry() != null ? SelectedEntry().Id : null);
            };
            searchWrap.Children.Add(searchBox);

            var searchIconWrap = new Border
            {
                IsHitTestVisible = false,
                HorizontalAlignment = HorizontalAlignment.Left,
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(11, 0, 0, 0),
                Child = AppTheme.Icon(IconSearch, 13.5, AppTheme.Brush("#64748B"), false)
            };
            searchWrap.Children.Add(searchIconWrap);

            searchPlaceholder = new TextBlock
            {
                Text = "搜索 Mod 名称或目录…",
                FontSize = 12.5,
                Foreground = AppTheme.Brush("#64748B"),
                IsHitTestVisible = false,
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(34, 0, 28, 0)
            };
            searchWrap.Children.Add(searchPlaceholder);

            clearSearchBtn = new Button
            {
                Style = (Style)FindResource("GhostButton"),
                Content = "×",
                FontSize = 14,
                Padding = new Thickness(6, 2, 6, 2),
                HorizontalAlignment = HorizontalAlignment.Right,
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(0, 0, 4, 0),
                Visibility = Visibility.Collapsed
            };
            clearSearchBtn.Click += delegate { searchBox.Text = ""; searchBox.Focus(); };
            searchWrap.Children.Add(clearSearchBtn);

            Grid.SetRow(searchWrap, 2);
            grid.Children.Add(searchWrap);

            // Row 3: ListBox + Empty State
            var listHost = new Grid();
            modListBox = new ListBox
            {
                Background = Brushes.Transparent,
                BorderThickness = new Thickness(0),
                ItemContainerStyle = (Style)FindResource("ModCardItemStyle"),
                HorizontalContentAlignment = HorizontalAlignment.Stretch,
                Padding = new Thickness(0, 2, 2, 2)
            };
            ScrollViewer.SetHorizontalScrollBarVisibility(modListBox, ScrollBarVisibility.Disabled);
            modListBox.SelectionChanged += delegate { OnSelectionChanged(); };
            modListBox.MouseDoubleClick += delegate
            {
                ModEntry sel = SelectedEntry();
                if (sel == null || isBusy) return;
                if (sel.IsFunctionalAddon)
                    ToggleAddon(sel, !library.IsAddonEnabled(sel.Id));
                else
                    StartSelectedMod();
            };
            listHost.Children.Add(modListBox);

            emptyStateCard = new Border
            {
                Background = AppTheme.Brush("#10151E"),
                BorderBrush = AppTheme.Brush("#2A3549"),
                BorderThickness = new Thickness(1.2),
                CornerRadius = new CornerRadius(11),
                Padding = new Thickness(20),
                VerticalAlignment = VerticalAlignment.Stretch,
                Visibility = Visibility.Collapsed
            };
            var emptyStack = new StackPanel
            {
                VerticalAlignment = VerticalAlignment.Center,
                HorizontalAlignment = HorizontalAlignment.Center
            };
            emptyStack.Children.Add(new Border
            {
                Width = 48,
                Height = 48,
                CornerRadius = new CornerRadius(14),
                Background = AppTheme.Brush("#1A2231"),
                Margin = new Thickness(0, 0, 0, 14),
                Child = AppTheme.Icon(IconUpload, 22, AppTheme.Brush("#94A3B8"), false)
            });
            emptyTitleText = new TextBlock
            {
                Text = "还没有导入任何 Mod",
                FontSize = 14,
                FontWeight = FontWeights.SemiBold,
                Foreground = AppTheme.Brush("#E2E8F0"),
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(0, 0, 0, 6)
            };
            emptyStack.Children.Add(emptyTitleText);
            emptySubtitleText = new TextBlock
            {
                Text = "将 .zip 压缩包或含 base/generated 的\n文件夹直接拖入窗口即可添加",
                FontSize = 12,
                Foreground = AppTheme.Brush("#64748B"),
                TextAlignment = TextAlignment.Center,
                LineHeight = 19,
                HorizontalAlignment = HorizontalAlignment.Center
            };
            emptyStack.Children.Add(emptySubtitleText);
            emptyStateCard.Child = emptyStack;
            listHost.Children.Add(emptyStateCard);

            Grid.SetRow(listHost, 3);
            grid.Children.Add(listHost);

            card.Child = grid;
            return card;
        }

        private UIElement BuildDetailPane()
        {
            var card = new Border
            {
                Background = AppTheme.Brush("#141923"),
                BorderBrush = AppTheme.Brush("#232C3D"),
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(12)
            };

            var host = new Grid();
            detailPanel = BuildSelectedDetailView();
            welcomePanel = BuildWelcomeView();
            host.Children.Add(detailPanel);
            host.Children.Add(welcomePanel);

            card.Child = host;
            return card;
        }

        private Grid BuildSelectedDetailView()
        {
            var grid = new Grid { Visibility = Visibility.Collapsed };
            grid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

            var scroll = new ScrollViewer
            {
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                Padding = new Thickness(20, 15, 20, 10)
            };

            var content = new StackPanel();

            // Top badges + action buttons
            var topRow = new DockPanel { Margin = new Thickness(0, 0, 0, 10) };
            var rightActions = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            DockPanel.SetDock(rightActions, Dock.Right);

            openFolderBtn = new Button
            {
                Style = (Style)FindResource("SecondaryButton"),
                Padding = new Thickness(10, 6, 10, 6),
                Margin = new Thickness(0, 0, 8, 0),
                Content = IconLabel(IconExternal, 13, "#94A3B8", "打开目录", "#E2E8F0"),
                ToolTip = "在资源管理器中打开此 Mod 所在文件夹"
            };
            openFolderBtn.Click += delegate { OpenSelectedFolder(); };
            rightActions.Children.Add(openFolderBtn);

            removeBtnText = new TextBlock { Text = "移除", VerticalAlignment = VerticalAlignment.Center };
            var removeStack = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            removeStack.Children.Add(new Border
            {
                Margin = new Thickness(0, 0, 6, 0),
                Child = AppTheme.Icon(IconTrash, 13, AppTheme.Brush("#F87171"), false)
            });
            removeStack.Children.Add(removeBtnText);

            removeBtn = new Button
            {
                Style = (Style)FindResource("DangerButton"),
                Padding = new Thickness(10, 6, 10, 6),
                Content = removeStack
            };
            removeBtn.Click += delegate { RemoveSelectedMod(); };
            rightActions.Children.Add(removeBtn);
            topRow.Children.Add(rightActions);

            var pills = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            modePillText = new TextBlock { Text = "已入库 Mod", FontSize = 11.5, FontWeight = FontWeights.SemiBold };
            modePill = new Border
            {
                CornerRadius = new CornerRadius(11),
                BorderThickness = new Thickness(1),
                Padding = new Thickness(10, 3, 10, 3),
                Margin = new Thickness(0, 0, 8, 0),
                Child = modePillText
            };
            pills.Children.Add(modePill);

            hookPillText = new TextBlock { Text = "模型挂载", FontSize = 11.5, FontWeight = FontWeights.Medium };
            hookPill = new Border
            {
                CornerRadius = new CornerRadius(11),
                BorderThickness = new Thickness(1),
                Padding = new Thickness(10, 3, 10, 3),
                Margin = new Thickness(0, 0, 8, 0),
                Child = hookPillText
            };
            pills.Children.Add(hookPill);

            dynPill = new Border
            {
                CornerRadius = new CornerRadius(11),
                BorderThickness = new Thickness(1),
                Background = AppTheme.Brush("#122B20"),
                BorderBrush = AppTheme.Brush("#1F5B3E"),
                Padding = new Thickness(10, 3, 10, 3),
                Visibility = Visibility.Collapsed,
                ToolTip = "此 Mod 包含通用动态物理/表情数据（base\\generated\\tew1_dyn.bin）\n游戏内热键：F7 柔和自发光 · F8 明亮自发光 · F9 全亮自发光（再按关闭）· F10 调试受伤表情（表情开关由管理器控制）",
                Child = new TextBlock
                {
                    Text = "动态物理/表情",
                    FontSize = 11.5,
                    FontWeight = FontWeights.Medium,
                    Foreground = AppTheme.Brush("#2EC476")
                }
            };
            pills.Children.Add(dynPill);

            topRow.Children.Add(pills);
            content.Children.Add(topRow);

            // Title & Subtitle
            detailTitle = new TextBlock
            {
                Text = "",
                FontSize = 21,
                FontWeight = FontWeights.Bold,
                Foreground = AppTheme.Brush("#F8FAFC"),
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 0, 0, 4)
            };
            content.Children.Add(detailTitle);

            detailSubtitle = new TextBlock
            {
                Text = "",
                FontSize = 12.5,
                Foreground = AppTheme.Brush("#94A3B8"),
                Margin = new Thickness(0, 0, 0, 11)
            };
            content.Children.Add(detailSubtitle);

            // Missing warning banner (hidden normally)
            missingBanner = new Border
            {
                Background = AppTheme.Brush("#2A161B"),
                BorderBrush = AppTheme.Brush("#7A2835"),
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(9),
                Padding = new Thickness(12, 8, 12, 8),
                Margin = new Thickness(0, 0, 0, 10),
                Visibility = Visibility.Collapsed,
                Child = new TextBlock
                {
                    Text = "找不到此目录中的 base\\generated 资源文件夹，可能已被移动或删除。",
                    FontSize = 12.5,
                    Foreground = AppTheme.Brush("#FCA5A5"),
                    TextWrapping = TextWrapping.Wrap
                }
            };
            content.Children.Add(missingBanner);

            // 3 Metric Cards
            var metrics = new Grid { Margin = new Thickness(0, 0, 0, 10) };
            metrics.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            metrics.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(10) });
            metrics.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            metrics.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(10) });
            metrics.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

            statModelsText = new TextBlock { FontSize = 20, FontWeight = FontWeights.Bold, Foreground = AppTheme.Brush("#F8FAFC") };
            statTexturesText = new TextBlock { FontSize = 20, FontWeight = FontWeights.Bold, Foreground = AppTheme.Brush("#4DA3FF") };
            statSizeText = new TextBlock { FontSize = 20, FontWeight = FontWeights.Bold, Foreground = AppTheme.Brush("#E2E8F0") };
            statFilesSubText = new TextBlock { FontSize = 11, Foreground = AppTheme.Brush("#64748B"), Margin = new Thickness(0, 2, 0, 0) };

            statCard1Title = new TextBlock { Text = "模型文件", FontSize = 11.5, Foreground = AppTheme.Brush("#94A3B8"), Margin = new Thickness(0, 0, 0, 4) };
            statCard1Sub = new TextBlock { Text = ".bmd6model", FontSize = 11, Foreground = AppTheme.Brush("#64748B"), Margin = new Thickness(0, 2, 0, 0) };
            var card1 = BuildMetricCardCustom(statCard1Title, statModelsText, statCard1Sub);
            Grid.SetColumn(card1, 0);
            metrics.Children.Add(card1);

            statCard2Title = new TextBlock { Text = "贴图文件", FontSize = 11.5, Foreground = AppTheme.Brush("#94A3B8"), Margin = new Thickness(0, 0, 0, 4) };
            statCard2Sub = new TextBlock { Text = ".bimage", FontSize = 11, Foreground = AppTheme.Brush("#64748B"), Margin = new Thickness(0, 2, 0, 0) };
            var card2 = BuildMetricCardCustom(statCard2Title, statTexturesText, statCard2Sub);
            Grid.SetColumn(card2, 2);
            metrics.Children.Add(card2);

            var card3 = BuildMetricCard("资源规模", statSizeText, statFilesSubText);
            Grid.SetColumn(card3, 4);
            metrics.Children.Add(card3);

            content.Children.Add(metrics);

            activeAddonsBannerText = new TextBlock
            {
                Text = "",
                FontSize = 12,
                Foreground = AppTheme.Brush("#6EE7B7"),
                TextWrapping = TextWrapping.Wrap
            };
            activeAddonsBanner = new Border
            {
                Background = AppTheme.Brush("#10261D"),
                BorderBrush = AppTheme.Brush("#1E563D"),
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(9),
                Padding = new Thickness(12, 8, 12, 8),
                Margin = new Thickness(0, 0, 0, 10),
                Visibility = Visibility.Collapsed,
                Child = activeAddonsBannerText
            };
            content.Children.Add(activeAddonsBanner);

            // Mount details card
            var infoCard = new Border
            {
                Background = AppTheme.Brush("#1A212E"),
                BorderBrush = AppTheme.Brush("#252F42"),
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(10),
                Padding = new Thickness(14, 10, 14, 10),
                Margin = new Thickness(0, 0, 0, 10)
            };
            var infoStack = new StackPanel();

            var pathHeader = new DockPanel { Margin = new Thickness(0, 0, 0, 3) };
            var copyPathBtn = new Button
            {
                Style = (Style)FindResource("GhostButton"),
                Padding = new Thickness(7, 3, 7, 3),
                Content = IconLabel(IconCopy, 12, "#94A3B8", "复制路径", "#94A3B8")
            };
            copyPathBtn.Click += delegate
            {
                ModEntry sel = SelectedEntry();
                if (sel != null)
                {
                    try
                    {
                        Clipboard.SetText(sel.Overlay);
                        SetStatus("已复制挂载路径到剪贴板。", "#4DA3FF");
                    }
                    catch { }
                }
            };
            DockPanel.SetDock(copyPathBtn, Dock.Right);
            pathHeader.Children.Add(copyPathBtn);
            pathHeader.Children.Add(new TextBlock
            {
                Text = "挂载根目录",
                FontSize = 11.5,
                FontWeight = FontWeights.SemiBold,
                Foreground = AppTheme.Brush("#94A3B8"),
                VerticalAlignment = VerticalAlignment.Center
            });
            infoStack.Children.Add(pathHeader);

            detailPathText = new TextBlock
            {
                Text = "",
                FontSize = 12,
                Foreground = AppTheme.Brush("#CBD5E1"),
                TextTrimming = TextTrimming.CharacterEllipsis,
                Margin = new Thickness(0, 0, 0, 8)
            };
            infoStack.Children.Add(detailPathText);

            infoStack.Children.Add(new Border
            {
                Height = 1,
                Background = AppTheme.Brush("#252F42"),
                Margin = new Thickness(0, 0, 0, 8)
            });

            infoStack.Children.Add(new TextBlock
            {
                Text = "挂载说明",
                FontSize = 11.5,
                FontWeight = FontWeights.SemiBold,
                Foreground = AppTheme.Brush("#94A3B8"),
                Margin = new Thickness(0, 0, 0, 4)
            });

            detailMechanismText = new TextBlock
            {
                Text = "",
                FontSize = 12,
                LineHeight = 18,
                Foreground = AppTheme.Brush("#94A3B8"),
                TextWrapping = TextWrapping.Wrap
            };
            infoStack.Children.Add(detailMechanismText);

            infoCard.Child = infoStack;
            content.Children.Add(infoCard);

            // Generic Dynamic Physics & Facial Morphs Card (active when Mod contains base/generated/tew1_dyn.bin)
            extCard = new Border
            {
                Background = AppTheme.Brush("#1A212E"),
                BorderBrush = AppTheme.Brush("#252F42"),
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(10),
                Padding = new Thickness(14, 10, 14, 10),
                Margin = new Thickness(0, 0, 0, 10)
            };
            var extStack = new StackPanel();
            var extHeader = new DockPanel { Margin = new Thickness(0, 0, 0, 8) };
            extStatusPillText = new TextBlock
            {
                Text = "未包含扩展包",
                FontSize = 10.5,
                FontWeight = FontWeights.Medium
            };
            extStatusPill = new Border
            {
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(9),
                Padding = new Thickness(8, 1.5, 8, 1.5),
                Child = extStatusPillText
            };
            DockPanel.SetDock(extStatusPill, Dock.Right);
            extHeader.Children.Add(extStatusPill);
            extHeader.Children.Add(new TextBlock
            {
                Text = "动态物理与表情扩展（tew1_dyn.bin）",
                FontSize = 12,
                FontWeight = FontWeights.SemiBold,
                Foreground = AppTheme.Brush("#E2E8F0"),
                VerticalAlignment = VerticalAlignment.Center
            });
            extStack.Children.Add(extHeader);

            var toggleRow = new WrapPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 0, 6) };
            hairPhysicsToggle = new CheckBox
            {
                Style = (Style)FindResource("ModernToggle"),
                Content = "头发物理",
                IsChecked = library.EnableHairPhysics,
                Margin = new Thickness(0, 0, 22, 2),
                ToolTip = "启用 Mod 内置的实时头发物理与骨骼碰撞模拟"
            };
            hairPhysicsToggle.Checked += delegate { library.EnableHairPhysics = true; };
            hairPhysicsToggle.Unchecked += delegate { library.EnableHairPhysics = false; };
            toggleRow.Children.Add(hairPhysicsToggle);

            independentFaceToggle = new CheckBox
            {
                Style = (Style)FindResource("ModernToggle"),
                Content = "独立表情（眨眼 / 受击 / 死亡）",
                IsChecked = library.EnableIndependentFace,
                Margin = new Thickness(0, 0, 0, 2),
                ToolTip = "启用 Mod 内置的眨眼、受击、死亡表情（嘴部保持原版骨骼映射）"
            };
            independentFaceToggle.Checked += delegate { library.EnableIndependentFace = true; };
            independentFaceToggle.Unchecked += delegate { library.EnableIndependentFace = false; };
            toggleRow.Children.Add(independentFaceToggle);
            extStack.Children.Add(toggleRow);

            extStack.Children.Add(new TextBlock
            {
                Text = "游戏内热键：F7 柔和自发光 · F8 明亮自发光 · F9 全亮自发光（再按关闭）· F10 调试受伤表情（Shift/Ctrl+F10 定格受伤/死亡；表情开关由上方勾选控制）",
                FontSize = 11,
                Foreground = AppTheme.Brush("#64748B"),
                TextWrapping = TextWrapping.Wrap
            });
            extCard.Child = extStack;
            content.Children.Add(extCard);

            // Collapsible Advanced Launch Arguments
            var advWrap = new Border
            {
                Background = AppTheme.Brush("#171D28"),
                BorderBrush = AppTheme.Brush("#232C3D"),
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(10)
            };
            var advStack = new StackPanel();

            var advHeader = new DockPanel { Margin = new Thickness(12, 8, 10, 8) };
            advancedChevron = AppTheme.Icon(IconChevronDown, 13, AppTheme.Brush("#94A3B8"), false);
            var chevHost = new Border { Child = advancedChevron, VerticalAlignment = VerticalAlignment.Center };
            DockPanel.SetDock(chevHost, Dock.Right);
            advHeader.Children.Add(chevHost);
            advHeader.Children.Add(new TextBlock
            {
                Text = "高级启动参数（可选）",
                FontSize = 12,
                FontWeight = FontWeights.Medium,
                Foreground = AppTheme.Brush("#94A3B8"),
                VerticalAlignment = VerticalAlignment.Center
            });

            advancedToggleBtn = new Button
            {
                Background = Brushes.Transparent,
                BorderThickness = new Thickness(0),
                HorizontalContentAlignment = HorizontalAlignment.Stretch,
                Padding = new Thickness(0),
                Cursor = Cursors.Hand,
                FocusVisualStyle = null,
                Content = advHeader
            };
            advancedToggleBtn.Template = CreateTransparentButtonTemplate();
            advancedToggleBtn.Click += delegate
            {
                advancedOpen = !advancedOpen;
                advancedBody.Visibility = advancedOpen ? Visibility.Visible : Visibility.Collapsed;
                chevHost.Child = AppTheme.Icon(advancedOpen ? IconChevronUp : IconChevronDown, 13, AppTheme.Brush("#94A3B8"), false);
            };
            advStack.Children.Add(advancedToggleBtn);

            advancedBody = new Border
            {
                BorderBrush = AppTheme.Brush("#232C3D"),
                BorderThickness = new Thickness(0, 1, 0, 0),
                Padding = new Thickness(12, 10, 12, 12),
                Visibility = Visibility.Collapsed
            };
            var advInner = new StackPanel();
            extraArgsBox = new TextBox
            {
                Style = (Style)FindResource("DarkTextBox"),
                FontSize = 12,
                Text = library.ExtraLaunchArgs,
                Margin = new Thickness(0, 0, 0, 8),
                ToolTip = "附加到 EvilWithin.exe 的额外引擎参数"
            };
            extraArgsBox.LostFocus += delegate { library.ExtraLaunchArgs = extraArgsBox.Text.Trim(); };
            advInner.Children.Add(extraArgsBox);

            var chipPanel = new WrapPanel { Orientation = Orientation.Horizontal };
            chipPanel.Children.Add(CreateArgChip("跳过开场动画", "+com_skipIntroVideo 1"));
            chipPanel.Children.Add(CreateArgChip("解锁 60 帧", "+r_swapInterval 0"));
            chipPanel.Children.Add(CreateArgChip("启用控制台", "+com_allowconsole 1"));
            advInner.Children.Add(chipPanel);

            advancedBody.Child = advInner;
            advStack.Children.Add(advancedBody);
            advWrap.Child = advStack;
            content.Children.Add(advWrap);

            scroll.Content = content;
            Grid.SetRow(scroll, 0);
            grid.Children.Add(scroll);

            // Pinned Bottom Launch Dock
            var dock = new Border
            {
                BorderBrush = AppTheme.Brush("#232C3D"),
                BorderThickness = new Thickness(0, 1, 0, 0),
                Background = AppTheme.Brush("#121720"),
                CornerRadius = new CornerRadius(0, 0, 12, 12),
                Padding = new Thickness(20, 14, 20, 14)
            };

            var dockGrid = new Grid();
            dockGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            dockGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(10) });
            dockGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(126) });

            launchModBtnText = new TextBlock
            {
                Text = "启动游戏",
                FontSize = 14.5,
                FontWeight = FontWeights.SemiBold,
                VerticalAlignment = VerticalAlignment.Center
            };
            launchModIconWrap = new Border
            {
                Margin = new Thickness(0, 0, 8, 0),
                Child = AppTheme.Icon(IconPlay, 14, Brushes.White, true)
            };
            var launchContent = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            launchContent.Children.Add(launchModIconWrap);
            launchContent.Children.Add(launchModBtnText);

            launchModBtn = new Button
            {
                Style = (Style)FindResource("PrimaryButton"),
                Height = 46,
                Content = launchContent
            };
            launchModBtn.Click += delegate { OnPrimaryDockButtonClick(); };
            Grid.SetColumn(launchModBtn, 0);
            dockGrid.Children.Add(launchModBtn);

            launchVanillaBtn = new Button
            {
                Style = (Style)FindResource("SecondaryButton"),
                Height = 46,
                Content = "原版启动",
                ToolTip = "不挂载任何 Mod，直接启动原版 EvilWithin.exe"
            };
            launchVanillaBtn.Click += delegate { OnSecondaryDockButtonClick(); };
            Grid.SetColumn(launchVanillaBtn, 2);
            dockGrid.Children.Add(launchVanillaBtn);

            dock.Child = dockGrid;
            Grid.SetRow(dock, 1);
            grid.Children.Add(dock);

            return grid;
        }

        private Grid BuildWelcomeView()
        {
            var grid = new Grid();
            grid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

            var scroll = new ScrollViewer
            {
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                Padding = new Thickness(24, 18, 24, 14)
            };

            var stack = new StackPanel
            {
                VerticalAlignment = VerticalAlignment.Center
            };

            var iconCircle = new Border
            {
                Width = 44,
                Height = 44,
                CornerRadius = new CornerRadius(12),
                Background = AppTheme.Brush("#2A161B"),
                BorderBrush = AppTheme.Brush("#702430"),
                BorderThickness = new Thickness(1),
                HorizontalAlignment = HorizontalAlignment.Left,
                Margin = new Thickness(0, 0, 0, 12),
                Child = AppTheme.Icon(IconSpark, 21, AppTheme.Brush("#EB4656"), false)
            };
            stack.Children.Add(iconCircle);

            stack.Children.Add(new TextBlock
            {
                Text = "一体化 Mod 管理与加载工作台",
                FontSize = 19,
                FontWeight = FontWeights.Bold,
                Foreground = AppTheme.Brush("#F8FAFC"),
                Margin = new Thickness(0, 0, 0, 5)
            });

            stack.Children.Add(new TextBlock
            {
                Text = "将 Mod 管理器与原生加载器合二为一，无需额外 Python 运行库，不修改游戏原始归档。",
                FontSize = 12.5,
                LineHeight = 19,
                Foreground = AppTheme.Brush("#94A3B8"),
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 0, 0, 16)
            });

            stack.Children.Add(BuildStepCard("1", "配置游戏目录", "在上方选择含 EvilWithin.exe 的目录，自动校验受支持的 Windows x64 构建。"));
            stack.Children.Add(BuildStepCard("2", "导入 ZIP 或直挂目录", "拖入 .zip 压缩包永久入库，或选择已解压的 base/generated 目录进行零拷贝实时直挂。"));
            stack.Children.Add(BuildStepCard("3", "一键挂载启动", "在左侧选中目标后点击启动，原生加载器自动启用松散模型与贴图挂载。"));

            scroll.Content = stack;
            Grid.SetRow(scroll, 0);
            grid.Children.Add(scroll);

            var footer = new Border
            {
                BorderBrush = AppTheme.Brush("#232C3D"),
                BorderThickness = new Thickness(0, 1, 0, 0),
                Background = AppTheme.Brush("#121720"),
                CornerRadius = new CornerRadius(0, 0, 12, 12),
                Padding = new Thickness(20, 14, 20, 14)
            };
            var footerRow = new DockPanel();
            welcomeVanillaBtn = new Button
            {
                Style = (Style)FindResource("SecondaryButton"),
                Height = 40,
                MinWidth = 120,
                Content = "原版启动游戏"
            };
            welcomeVanillaBtn.Click += delegate { StartVanillaGame(); };
            DockPanel.SetDock(welcomeVanillaBtn, Dock.Right);
            footerRow.Children.Add(welcomeVanillaBtn);

            footerRow.Children.Add(new TextBlock
            {
                Text = "提示：切换 Mod 前请先关闭正在运行的游戏窗口。",
                FontSize = 12,
                Foreground = AppTheme.Brush("#64748B"),
                VerticalAlignment = VerticalAlignment.Center
            });

            footer.Child = footerRow;
            Grid.SetRow(footer, 1);
            grid.Children.Add(footer);

            return grid;
        }

        private UIElement BuildStatusBar()
        {
            var bar = new Border
            {
                Background = AppTheme.Brush("#0F131B"),
                BorderBrush = AppTheme.Brush("#1E2636"),
                BorderThickness = new Thickness(0, 1, 0, 0),
                Padding = new Thickness(18, 0, 18, 0)
            };

            var dock = new DockPanel();

            var rightHint = new TextBlock
            {
                Text = "绿色便携模式 · 数据存放在程序同级 Data 目录",
                FontSize = 11.5,
                Foreground = AppTheme.Brush("#64748B"),
                VerticalAlignment = VerticalAlignment.Center,
                ToolTip = "Mod 库与配置目录：" + library.RootDirectory
            };
            DockPanel.SetDock(rightHint, Dock.Right);
            dock.Children.Add(rightHint);

            var left = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            statusDot = new Ellipse
            {
                Width = 7,
                Height = 7,
                Fill = AppTheme.Brush("#2EC476"),
                Margin = new Thickness(0, 0, 8, 0),
                VerticalAlignment = VerticalAlignment.Center
            };
            statusText = new TextBlock
            {
                Text = "已就绪。",
                FontSize = 12,
                Foreground = AppTheme.Brush("#94A3B8"),
                TextTrimming = TextTrimming.CharacterEllipsis,
                VerticalAlignment = VerticalAlignment.Center
            };
            left.Children.Add(statusDot);
            left.Children.Add(statusText);
            dock.Children.Add(left);

            bar.Child = dock;
            return bar;
        }

        private Border BuildDragOverlay()
        {
            var overlay = new Border
            {
                Background = new SolidColorBrush(Color.FromArgb(215, 13, 16, 22)),
                Visibility = Visibility.Collapsed,
                IsHitTestVisible = false,
                Padding = new Thickness(32)
            };

            var frame = new Border
            {
                Background = AppTheme.Brush("#181F2C"),
                BorderBrush = AppTheme.Brush("#DC3545"),
                BorderThickness = new Thickness(2),
                CornerRadius = new CornerRadius(16),
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
                Padding = new Thickness(48, 36, 48, 36)
            };

            var stack = new StackPanel { HorizontalAlignment = HorizontalAlignment.Center };
            stack.Children.Add(new Border
            {
                Width = 56,
                Height = 56,
                CornerRadius = new CornerRadius(16),
                Background = AppTheme.Brush("#2A161B"),
                Margin = new Thickness(0, 0, 0, 14),
                Child = AppTheme.Icon(IconUpload, 26, AppTheme.Brush("#EB4656"), false)
            });

            dragOverlayTitle = new TextBlock
            {
                Text = "松开鼠标以添加 Mod",
                FontSize = 18,
                FontWeight = FontWeights.Bold,
                Foreground = AppTheme.Brush("#F8FAFC"),
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(0, 0, 0, 6)
            };
            stack.Children.Add(dragOverlayTitle);

            dragOverlaySub = new TextBlock
            {
                Text = "自动识别 .zip 压缩包入库或直挂含 base/generated 的文件夹",
                FontSize = 12.5,
                Foreground = AppTheme.Brush("#94A3B8"),
                HorizontalAlignment = HorizontalAlignment.Center
            };
            stack.Children.Add(dragOverlaySub);

            frame.Child = stack;
            overlay.Child = frame;
            return overlay;
        }

        private Border BuildMetricCard(string label, TextBlock valueBlock, TextBlock subBlock)
        {
            var stack = new StackPanel();
            stack.Children.Add(new TextBlock
            {
                Text = label,
                FontSize = 11.5,
                Foreground = AppTheme.Brush("#94A3B8"),
                Margin = new Thickness(0, 0, 0, 4)
            });
            stack.Children.Add(valueBlock);
            stack.Children.Add(subBlock);

            return new Border
            {
                Background = AppTheme.Brush("#1A212E"),
                BorderBrush = AppTheme.Brush("#252F42"),
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(10),
                Padding = new Thickness(13, 9, 13, 9),
                Child = stack
            };
        }

        private Border BuildMetricCardCustom(TextBlock titleBlock, TextBlock valueBlock, TextBlock subBlock)
        {
            var stack = new StackPanel();
            stack.Children.Add(titleBlock);
            stack.Children.Add(valueBlock);
            stack.Children.Add(subBlock);

            return new Border
            {
                Background = AppTheme.Brush("#1A212E"),
                BorderBrush = AppTheme.Brush("#252F42"),
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(10),
                Padding = new Thickness(13, 9, 13, 9),
                Child = stack
            };
        }

        private Border BuildStepCard(string num, string title, string desc)
        {
            var dock = new DockPanel();
            var numBadge = new Border
            {
                Width = 26,
                Height = 26,
                CornerRadius = new CornerRadius(8),
                Background = AppTheme.Brush("#1E2738"),
                BorderBrush = AppTheme.Brush("#2F3D57"),
                BorderThickness = new Thickness(1),
                Margin = new Thickness(0, 1, 12, 0),
                VerticalAlignment = VerticalAlignment.Top,
                Child = new TextBlock
                {
                    Text = num,
                    FontSize = 12,
                    FontWeight = FontWeights.Bold,
                    Foreground = AppTheme.Brush("#E2E8F0"),
                    HorizontalAlignment = HorizontalAlignment.Center,
                    VerticalAlignment = VerticalAlignment.Center
                }
            };
            DockPanel.SetDock(numBadge, Dock.Left);
            dock.Children.Add(numBadge);

            var textStack = new StackPanel();
            textStack.Children.Add(new TextBlock
            {
                Text = title,
                FontSize = 13,
                FontWeight = FontWeights.SemiBold,
                Foreground = AppTheme.Brush("#F1F5F9"),
                Margin = new Thickness(0, 0, 0, 2)
            });
            textStack.Children.Add(new TextBlock
            {
                Text = desc,
                FontSize = 12,
                Foreground = AppTheme.Brush("#94A3B8"),
                TextWrapping = TextWrapping.Wrap,
                LineHeight = 17.5
            });
            dock.Children.Add(textStack);

            return new Border
            {
                Background = AppTheme.Brush("#1A212E"),
                BorderBrush = AppTheme.Brush("#252F42"),
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(10),
                Padding = new Thickness(13, 9, 13, 9),
                Margin = new Thickness(0, 0, 0, 8),
                Child = dock
            };
        }

        private Button CreateArgChip(string label, string flag)
        {
            var chip = new Button
            {
                Style = (Style)FindResource("ChipButton"),
                Content = "+ " + label,
                Margin = new Thickness(0, 0, 6, 4),
                ToolTip = flag
            };
            chip.Click += delegate
            {
                string current = (extraArgsBox.Text ?? "").Trim();
                if (current.IndexOf(flag, StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    string updated = current.Replace(flag, "").Replace("  ", " ").Trim();
                    extraArgsBox.Text = updated;
                }
                else
                {
                    extraArgsBox.Text = String.IsNullOrEmpty(current) ? flag : current + " " + flag;
                }
                library.ExtraLaunchArgs = extraArgsBox.Text.Trim();
            };
            return chip;
        }

        private static StackPanel IconLabel(string pathData, double iconSize, string iconHex, string text, string textHex)
        {
            var panel = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            panel.Children.Add(new Border
            {
                Margin = new Thickness(0, 0, 7, 0),
                Child = AppTheme.Icon(pathData, iconSize, AppTheme.Brush(iconHex), false)
            });
            panel.Children.Add(new TextBlock
            {
                Text = text,
                Foreground = AppTheme.Brush(textHex),
                VerticalAlignment = VerticalAlignment.Center
            });
            return panel;
        }

        private static ControlTemplate CreateTransparentButtonTemplate()
        {
            var template = new ControlTemplate(typeof(Button));
            var presenter = new FrameworkElementFactory(typeof(ContentPresenter));
            template.VisualTree = presenter;
            return template;
        }

        private UIElement CreateModListItemContent(ModEntry entry)
        {
            bool isAddon = entry.IsFunctionalAddon;
            bool addonEnabled = isAddon && library.IsAddonEnabled(entry.Id);

            var outer = new Grid { Margin = new Thickness(0) };
            outer.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(4) });
            outer.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

            string stripeHex;
            if (entry.FolderMissing) stripeHex = "#EF4444";
            else if (isAddon) stripeHex = addonEnabled ? "#2EC476" : "#475569";
            else stripeHex = entry.IsLinkedFolder ? "#E8A838" : "#DC3545";

            var stripe = new Border
            {
                Background = AppTheme.Brush(stripeHex),
                CornerRadius = new CornerRadius(10, 0, 0, 10),
                Opacity = isAddon && !addonEnabled ? 0.55 : 0.90
            };
            Grid.SetColumn(stripe, 0);
            outer.Children.Add(stripe);

            var body = new StackPanel { Margin = new Thickness(11, 10, 12, 10) };

            var topRow = new DockPanel { Margin = new Thickness(0, 0, 0, 5) };
            if (isAddon)
            {
                var toggle = new CheckBox
                {
                    Style = (Style)FindResource("ModernToggle"),
                    IsChecked = addonEnabled,
                    Content = addonEnabled ? "已启用" : "已关闭",
                    FontSize = 11,
                    Foreground = AppTheme.Brush(addonEnabled ? "#6EE7B7" : "#64748B"),
                    Margin = new Thickness(8, 0, 0, 0),
                    VerticalAlignment = VerticalAlignment.Center,
                    ToolTip = "启用后，点击任意模型 Mod 启动游戏时都会自动叠加此功能性 Mod"
                };
                toggle.Click += delegate (object s, RoutedEventArgs ev)
                {
                    ev.Handled = true;
                    if (!isBusy) ToggleAddon(entry, toggle.IsChecked == true);
                };
                DockPanel.SetDock(toggle, Dock.Right);
                topRow.Children.Add(toggle);
            }
            else if (entry.IsLinkedFolder)
            {
                var linkBadge = new Border
                {
                    Background = AppTheme.Brush("#292113"),
                    BorderBrush = AppTheme.Brush("#664C1E"),
                    BorderThickness = new Thickness(1),
                    CornerRadius = new CornerRadius(6),
                    Padding = new Thickness(6, 1, 6, 1),
                    Margin = new Thickness(8, 0, 0, 0),
                    VerticalAlignment = VerticalAlignment.Center,
                    Child = new TextBlock
                    {
                        Text = "直挂",
                        FontSize = 10.5,
                        FontWeight = FontWeights.SemiBold,
                        Foreground = AppTheme.Brush("#E8A838")
                    }
                };
                DockPanel.SetDock(linkBadge, Dock.Right);
                topRow.Children.Add(linkBadge);
            }
            else if (!String.IsNullOrWhiteSpace(entry.Version))
            {
                var verBadge = new Border
                {
                    Background = AppTheme.Brush("#1E2636"),
                    CornerRadius = new CornerRadius(6),
                    Padding = new Thickness(6, 1, 6, 1),
                    Margin = new Thickness(8, 0, 0, 0),
                    VerticalAlignment = VerticalAlignment.Center,
                    Child = new TextBlock
                    {
                        Text = entry.Version,
                        FontSize = 10.5,
                        Foreground = AppTheme.Brush("#94A3B8")
                    }
                };
                DockPanel.SetDock(verBadge, Dock.Right);
                topRow.Children.Add(verBadge);
            }

            topRow.Children.Add(new TextBlock
            {
                Text = entry.Name,
                FontSize = 13.5,
                FontWeight = FontWeights.SemiBold,
                Foreground = AppTheme.Brush("#F1F5F9"),
                TextTrimming = TextTrimming.CharacterEllipsis,
                VerticalAlignment = VerticalAlignment.Center
            });
            body.Children.Add(topRow);

            string subLine;
            string subColor;
            if (entry.FolderMissing)
            {
                subLine = "资源目录已不存在";
                subColor = "#F87171";
            }
            else if (isAddon)
            {
                var parts = new List<string>();
                parts.Add(entry.HasSoundFolder && entry.AudioCount > 0 ? "语音/功能" : "功能性 Mod");
                if (entry.AudioCount > 0) parts.Add(entry.AudioCount + " 音频");
                else if (entry.TextureCount > 0) parts.Add(entry.TextureCount + " 贴图");
                else parts.Add(entry.TotalFiles + " 文件");
                parts.Add(entry.SizeText);
                subLine = String.Join("  ·  ", parts);
                subColor = addonEnabled ? "#6EE7B7" : "#8292AA";
            }
            else
            {
                var parts = new List<string>();
                if (entry.ModelCount > 0) parts.Add(entry.ModelCount + " 模型");
                if (entry.TextureCount > 0) parts.Add(entry.TextureCount + " 贴图");
                if (entry.AudioCount > 0) parts.Add(entry.AudioCount + " 音频");
                if (parts.Count == 0) parts.Add(entry.TotalFiles + " 文件");
                parts.Add(entry.SizeText);
                subLine = String.Join("  ·  ", parts);
                subColor = "#8292AA";
            }

            body.Children.Add(new TextBlock
            {
                Text = subLine,
                FontSize = 11.5,
                Foreground = AppTheme.Brush(subColor),
                TextTrimming = TextTrimming.CharacterEllipsis
            });

            Grid.SetColumn(body, 1);
            outer.Children.Add(body);
            return outer;
        }

        private void UpdateMaximizeState()
        {
            if (WindowState == WindowState.Maximized)
            {
                rootGrid.Margin = new Thickness(7);
                maxRestoreBtn.ToolTip = "还原";
            }
            else
            {
                rootGrid.Margin = new Thickness(0);
                maxRestoreBtn.ToolTip = "最大化";
            }
        }

        private async void OnWindowLoaded(object sender, RoutedEventArgs e)
        {
            string savedGame = library.Game;
            if (String.IsNullOrWhiteSpace(savedGame))
            {
                string detected = Library.AutoDetectGameDirectory();
                if (!String.IsNullOrEmpty(detected))
                {
                    library.Game = detected;
                    savedGame = detected;
                }
            }

            RefreshEntries(library.LastSelectedId);
            await ValidateGameAsync(savedGame);

            if (startupPaths.Length > 0)
            {
                await HandleIncomingPathsAsync(startupPaths);
            }
            else
            {
                SetStatus(allEntries.Count == 0
                    ? "还没有 Mod。拖入 .zip 压缩包或点击「直挂目录」开始。"
                    : "已就绪，选择一个 Mod 即可挂载启动。", "#2EC476");
            }
        }

        private async Task ValidateGameAsync(string path)
        {
            if (String.IsNullOrWhiteSpace(path))
            {
                gameStatus = new GameValidationResult { State = GameCheckState.NotConfigured, NormalizedPath = "", Message = "尚未设置游戏目录" };
                UpdateGameBarVisuals();
                return;
            }

            gamePathText.Text = path;
            gamePathText.ToolTip = path;
            gamePathText.Foreground = AppTheme.Brush("#CBD5E1");
            SetGameBadge("校验中…", "#4DA3FF", "#142338", "#264974", "正在验证 EvilWithin.exe SHA-256 签名…");

            GameValidationResult result = await Task.Run(() => NativeLoader.InspectGameDirectory(path));
            gameStatus = result;
            UpdateGameBarVisuals();
            UpdateActionStates();
        }

        private void UpdateGameBarVisuals()
        {
            if (gameStatus == null || gameStatus.State == GameCheckState.NotConfigured)
            {
                gamePathText.Text = "尚未选择包含 EvilWithin.exe 的游戏目录";
                gamePathText.ToolTip = null;
                gamePathText.Foreground = AppTheme.Brush("#64748B");
                SetGameBadge("未配置", "#E8A838", "#292113", "#664C1E", "请选择包含 EvilWithin.exe 的游戏目录");
            }
            else if (gameStatus.State == GameCheckState.Ready)
            {
                gamePathText.Text = gameStatus.NormalizedPath;
                gamePathText.ToolTip = gameStatus.NormalizedPath;
                gamePathText.Foreground = AppTheme.Brush("#E2E8F0");
                SetGameBadge("已就绪", "#2EC476", "#122B20", "#1F5B3E", gameStatus.Message + "\nSHA-256: " + gameStatus.Sha256);
            }
            else if (gameStatus.State == GameCheckState.UnsupportedBuild)
            {
                gamePathText.Text = gameStatus.NormalizedPath;
                gamePathText.ToolTip = gameStatus.NormalizedPath;
                gamePathText.Foreground = AppTheme.Brush("#F8FAFC");
                SetGameBadge("版本不匹配", "#F87171", "#2A161B", "#702430", gameStatus.Message + "\n当前 SHA-256: " + gameStatus.Sha256);
            }
            else
            {
                gamePathText.Text = gameStatus.NormalizedPath;
                gamePathText.ToolTip = gameStatus.NormalizedPath;
                gamePathText.Foreground = AppTheme.Brush("#FCA5A5");
                SetGameBadge("目录无效", "#F87171", "#2A161B", "#702430", gameStatus.Message);
            }
        }

        private void SetGameBadge(string text, string fgHex, string bgHex, string borderHex, string tooltip)
        {
            gameBadgeText.Text = text;
            gameBadgeText.Foreground = AppTheme.Brush(fgHex);
            gameBadgeDot.Fill = AppTheme.Brush(fgHex);
            gameBadgeBorder.Background = AppTheme.Brush(bgHex);
            gameBadgeBorder.BorderBrush = AppTheme.Brush(borderHex);
            gameBadgeBorder.ToolTip = tooltip;
        }

        private void RefreshEntries(string selectId)
        {
            allEntries = library.GetAllEntries();
            countBadgeText.Text = allEntries.Count.ToString();
            ApplyFilter(selectId);
        }

        private void ApplyFilter(string selectId)
        {
            string query = (searchBox.Text ?? "").Trim();
            List<ModEntry> filtered = (String.IsNullOrEmpty(query)
                ? allEntries
                : allEntries.Where(m =>
                    (m.Name != null && m.Name.IndexOf(query, StringComparison.OrdinalIgnoreCase) >= 0) ||
                    (m.Overlay != null && m.Overlay.IndexOf(query, StringComparison.OrdinalIgnoreCase) >= 0) ||
                    (m.Version != null && m.Version.IndexOf(query, StringComparison.OrdinalIgnoreCase) >= 0)))
                .OrderBy(m => m.IsFunctionalAddon ? 1 : 0)
                .ToList();

            modListBox.Items.Clear();
            int targetIndex = -1;
            for (int i = 0; i < filtered.Count; i++)
            {
                ModEntry entry = filtered[i];
                var item = new ListBoxItem
                {
                    Tag = entry,
                    Content = CreateModListItemContent(entry)
                };
                modListBox.Items.Add(item);
                if (!String.IsNullOrEmpty(selectId) && String.Equals(entry.Id, selectId, StringComparison.OrdinalIgnoreCase))
                    targetIndex = i;
            }

            if (filtered.Count == 0)
            {
                emptyStateCard.Visibility = Visibility.Visible;
                if (allEntries.Count == 0)
                {
                    emptyTitleText.Text = "还没有导入任何 Mod";
                    emptySubtitleText.Text = "将 .zip 压缩包或含 base/generated 的\n文件夹直接拖入窗口即可添加";
                }
                else
                {
                    emptyTitleText.Text = "没有找到匹配的 Mod";
                    emptySubtitleText.Text = "尝试清空搜索关键词查看全部已添加项目";
                }
            }
            else
            {
                emptyStateCard.Visibility = Visibility.Collapsed;
                modListBox.SelectedIndex = targetIndex >= 0 ? targetIndex : 0;
            }

            OnSelectionChanged();
        }

        private ModEntry SelectedEntry()
        {
            var item = modListBox.SelectedItem as ListBoxItem;
            return item != null ? item.Tag as ModEntry : null;
        }

        private void OnSelectionChanged()
        {
            ModEntry entry = SelectedEntry();
            if (entry == null)
            {
                detailPanel.Visibility = Visibility.Collapsed;
                welcomePanel.Visibility = Visibility.Visible;
                UpdateActionStates();
                return;
            }

            library.LastSelectedId = entry.Id;
            welcomePanel.Visibility = Visibility.Collapsed;
            detailPanel.Visibility = Visibility.Visible;

            bool isAddon = entry.IsFunctionalAddon;
            bool addonEnabled = isAddon && library.IsAddonEnabled(entry.Id);
            List<ModEntry> enabledAddons = library.GetEnabledAddons(allEntries);

            if (isAddon)
            {
                modePillText.Text = addonEnabled ? "功能性 Mod · 已启用" : "功能性 Mod · 已关闭";
                modePillText.Foreground = AppTheme.Brush(addonEnabled ? "#2EC476" : "#94A3B8");
                modePill.Background = AppTheme.Brush(addonEnabled ? "#122B20" : "#1B2332");
                modePill.BorderBrush = AppTheme.Brush(addonEnabled ? "#1F5B3E" : "#2C374C");
                removeBtnText.Text = entry.IsLinkedFolder ? "取消直挂" : "移除 Mod";
                removeBtn.ToolTip = entry.IsLinkedFolder ? "仅从列表移除链接，不会删除硬盘上的原文件夹" : "从管理器本地库中删除此 Mod 副本";
                detailMechanismText.Text = "语音、补丁等功能性 Mod 可随时单独开启或关闭。开启后，点击任意模型 Mod 的「启动游戏」都会自动合并叠加生效；也可直接点击右下角「仅功能启动」配合原版角色使用。";
            }
            else if (entry.IsLinkedFolder)
            {
                modePillText.Text = "直挂模型 Mod";
                modePillText.Foreground = AppTheme.Brush("#E8A838");
                modePill.Background = AppTheme.Brush("#292113");
                modePill.BorderBrush = AppTheme.Brush("#664C1E");
                removeBtnText.Text = "取消直挂";
                removeBtn.ToolTip = "仅从列表移除链接，不会删除硬盘上的原文件夹";
                detailMechanismText.Text = "零拷贝实时挂载本地目录（适合未打包 Mod 或模型制作调试）。修改目录内文件后重启游戏即可生效，并自动叠加所有已启用的功能性 Mod。";
            }
            else
            {
                modePillText.Text = "模型 Mod";
                modePillText.Foreground = AppTheme.Brush("#F87171");
                modePill.Background = AppTheme.Brush("#2A161B");
                modePill.BorderBrush = AppTheme.Brush("#702430");
                removeBtnText.Text = "移除 Mod";
                removeBtn.ToolTip = "从管理器本地库中删除此 Mod 副本";
                detailMechanismText.Text = "通过内置原生加载器启用外部松散模型与贴图挂载，并自动叠加左侧已启用的语音/功能性 Mod，原版游戏归档零改动。";
            }

            var mountParts = new List<string>();
            if (entry.ModelCount > 0) mountParts.Add("模型");
            if (entry.HasTexturesFolder) mountParts.Add("贴图");
            if (entry.HasSoundFolder) mountParts.Add("语音");
            if (mountParts.Count == 0) mountParts.Add("资源");

            if (entry.HasTexturesFolder || entry.HasSoundFolder)
            {
                hookPillText.Text = String.Join(" + ", mountParts) + "挂载";
                hookPillText.Foreground = AppTheme.Brush("#4DA3FF");
                hookPill.Background = AppTheme.Brush("#142338");
                hookPill.BorderBrush = AppTheme.Brush("#264974");
            }
            else
            {
                hookPillText.Text = "仅模型挂载";
                hookPillText.Foreground = AppTheme.Brush("#94A3B8");
                hookPill.Background = AppTheme.Brush("#1B2332");
                hookPill.BorderBrush = AppTheme.Brush("#2C374C");
            }

            detailTitle.Text = entry.Name;
            var metaParts = new List<string>();
            if (!String.IsNullOrWhiteSpace(entry.Version)) metaParts.Add("版本 " + entry.Version);
            metaParts.Add("添加于 " + entry.AddedAt.ToString("yyyy-MM-dd HH:mm"));
            if (entry.AudioCount > 0) metaParts.Add(entry.AudioCount + " 个音频文件");
            if (entry.DeclCount > 0) metaParts.Add(entry.DeclCount + " 个声明文件");
            detailSubtitle.Text = String.Join("  ·  ", metaParts);

            missingBanner.Visibility = entry.FolderMissing ? Visibility.Visible : Visibility.Collapsed;

            if (isAddon)
            {
                statCard1Title.Text = "音频文件";
                statCard1Sub.Text = ".wav 松散语音";
                statModelsText.Text = entry.AudioCount.ToString();
                statCard2Title.Text = entry.TextureCount > 0 ? "贴图文件" : "声明文件";
                statCard2Sub.Text = entry.TextureCount > 0 ? ".bimage" : ".decl";
                statTexturesText.Text = (entry.TextureCount > 0 ? entry.TextureCount : entry.DeclCount).ToString();
            }
            else
            {
                statCard1Title.Text = "模型文件";
                statCard1Sub.Text = ".bmd6model";
                statModelsText.Text = entry.ModelCount.ToString();
                statCard2Title.Text = "贴图文件";
                statCard2Sub.Text = ".bimage";
                statTexturesText.Text = entry.TextureCount.ToString();
            }
            statSizeText.Text = entry.SizeText;
            statFilesSubText.Text = "共 " + entry.TotalFiles + " 个资源文件";

            if (!isAddon && enabledAddons.Count > 0)
            {
                string names = String.Join("、", enabledAddons.Select(a => a.Name));
                activeAddonsBannerText.Text = String.Format("启动游戏时将自动叠加 {0} 项已启用的功能性 Mod：{1}", enabledAddons.Count, names);
                activeAddonsBanner.Visibility = Visibility.Visible;
            }
            else
            {
                activeAddonsBanner.Visibility = Visibility.Collapsed;
            }

            detailPathText.Text = entry.Overlay;
            detailPathText.ToolTip = entry.Overlay;

            bool hasDll = NativeLoader.HasRuntimeDllAvailable();
            bool extReady = hasDll && entry.HasRuntimePack;
            dynPill.Visibility = extReady ? Visibility.Visible : Visibility.Collapsed;
            extCard.Visibility = (hasDll && !isAddon) ? Visibility.Visible : Visibility.Collapsed;

            hairPhysicsToggle.IsEnabled = extReady;
            independentFaceToggle.IsEnabled = extReady;
            extCard.BorderBrush = AppTheme.Brush(extReady ? "#2C3B54" : "#252F42");
            if (extReady)
            {
                extStatusPillText.Text = "当前 Mod 已内置";
                extStatusPillText.Foreground = AppTheme.Brush("#2EC476");
                extStatusPill.Background = AppTheme.Brush("#122B20");
                extStatusPill.BorderBrush = AppTheme.Brush("#1F5B3E");
            }
            else
            {
                extStatusPillText.Text = "当前 Mod 未包含";
                extStatusPillText.Foreground = AppTheme.Brush("#94A3B8");
                extStatusPill.Background = AppTheme.Brush("#1B2332");
                extStatusPill.BorderBrush = AppTheme.Brush("#2C374C");
            }

            UpdateActionStates();
        }

        private void ToggleAddon(ModEntry addon, bool enable)
        {
            if (addon == null || !addon.IsFunctionalAddon) return;
            library.SetAddonEnabled(addon.Id, enable);
            string currentSelectedId = SelectedEntry() != null ? SelectedEntry().Id : addon.Id;
            ApplyFilter(currentSelectedId);
            SetStatus(
                enable
                    ? "已启用功能性 Mod「" + addon.Name + "」，启动模型 Mod 时将自动叠加生效。"
                    : "已关闭功能性 Mod「" + addon.Name + "」。",
                enable ? "#2EC476" : "#94A3B8");
        }

        private void OnPrimaryDockButtonClick()
        {
            ModEntry sel = SelectedEntry();
            if (sel == null || isBusy) return;
            if (sel.IsFunctionalAddon)
            {
                ToggleAddon(sel, !library.IsAddonEnabled(sel.Id));
            }
            else
            {
                StartSelectedMod();
            }
        }

        private void OnSecondaryDockButtonClick()
        {
            ModEntry sel = SelectedEntry();
            if (isBusy) return;
            if (sel != null && sel.IsFunctionalAddon)
            {
                List<ModEntry> enabledAddons = library.GetEnabledAddons(allEntries);
                if (enabledAddons.Count > 0)
                {
                    StartEnabledAddonsOnly();
                    return;
                }
            }
            StartVanillaGame();
        }

        private void SetBusy(bool busy, string statusMessage)
        {
            isBusy = busy;
            Cursor = busy ? Cursors.Wait : Cursors.Arrow;
            if (!String.IsNullOrEmpty(statusMessage))
                SetStatus(statusMessage, busy ? "#4DA3FF" : "#2EC476");
            UpdateActionStates();
        }

        private void UpdateActionStates()
        {
            ModEntry sel = SelectedEntry();
            bool hasValidGame = gameStatus != null && gameStatus.State != GameCheckState.NotConfigured && gameStatus.State != GameCheckState.MissingFiles;
            bool canAct = !isBusy && sel != null && !sel.FolderMissing;
            List<ModEntry> enabledAddons = library.GetEnabledAddons(allEntries);

            detectGameBtn.IsEnabled = !isBusy;
            chooseGameBtn.IsEnabled = !isBusy;
            importZipBtn.IsEnabled = !isBusy;
            linkFolderBtn.IsEnabled = !isBusy;
            refreshBtn.IsEnabled = !isBusy;
            modListBox.IsEnabled = !isBusy;
            openFolderBtn.IsEnabled = !isBusy && sel != null && Directory.Exists(sel.Overlay);
            removeBtn.IsEnabled = !isBusy && sel != null;
            launchModBtn.IsEnabled = canAct;
            launchVanillaBtn.IsEnabled = !isBusy && hasValidGame;
            welcomeVanillaBtn.IsEnabled = !isBusy && hasValidGame;

            if (sel != null)
            {
                if (sel.IsFunctionalAddon)
                {
                    bool enabled = library.IsAddonEnabled(sel.Id);
                    launchModIconWrap.Visibility = Visibility.Collapsed;
                    if (enabled)
                    {
                        launchModBtn.Style = (Style)FindResource("SecondaryButton");
                        launchModBtnText.Text = "已启用 · 点击关闭此功能 Mod";
                        launchModBtnText.Foreground = AppTheme.Brush("#F1F5F9");
                    }
                    else
                    {
                        launchModBtn.Style = (Style)FindResource("PrimaryButton");
                        launchModBtnText.Text = "启用此功能性 Mod";
                        launchModBtnText.Foreground = Brushes.White;
                    }

                    if (enabledAddons.Count > 0)
                    {
                        launchVanillaBtn.Content = "仅功能启动";
                        launchVanillaBtn.ToolTip = "不替换模型，仅以原版角色 + 已启用的 " + enabledAddons.Count + " 项功能性 Mod 启动游戏";
                    }
                    else
                    {
                        launchVanillaBtn.Content = "原版启动";
                        launchVanillaBtn.ToolTip = "不挂载任何 Mod，直接启动原版 EvilWithin.exe";
                    }
                }
                else
                {
                    launchModBtn.Style = (Style)FindResource("PrimaryButton");
                    launchModIconWrap.Visibility = Visibility.Visible;
                    launchModBtnText.Foreground = Brushes.White;
                    if (isBusy)
                    {
                        launchModBtnText.Text = "正在挂载并启动游戏…";
                    }
                    else if (enabledAddons.Count > 0)
                    {
                        launchModBtnText.Text = String.Format("启动游戏（+{0} 项功能 Mod）", enabledAddons.Count);
                    }
                    else
                    {
                        launchModBtnText.Text = sel.IsLinkedFolder ? "直挂启动游戏" : "启动游戏";
                    }

                    launchVanillaBtn.Content = "原版启动";
                    launchVanillaBtn.ToolTip = "不挂载任何 Mod，直接启动原版 EvilWithin.exe";
                }
            }
        }

        private void SetStatus(string message, string dotHex)
        {
            statusText.Text = message;
            statusText.ToolTip = message;
            statusDot.Fill = AppTheme.Brush(dotHex);
        }

        private IntPtr GetHwnd()
        {
            return new WindowInteropHelper(this).Handle;
        }

        private async void AutoDetectGame(bool notifyUser)
        {
            string found = Library.AutoDetectGameDirectory();
            if (found != null)
            {
                library.Game = found;
                await ValidateGameAsync(found);
                if (notifyUser) SetStatus("已自动定位游戏目录：" + found, "#2EC476");
            }
            else if (notifyUser)
            {
                SetStatus("未能自动找到 EvilWithin.exe，请手动选择游戏目录。", "#E8A838");
                ModernDialog.Show(this, "未检测到游戏目录",
                    "未在常见 Steam/本地目录中找到 EvilWithin.exe。\n请点击「选择目录」手动定位游戏安装文件夹。",
                    DialogKind.Info, "我知道了");
            }
        }

        private async void ChooseGameDirectory()
        {
            try
            {
                string initial = Directory.Exists(library.Game) ? library.Game : null;
                string selected = FolderPicker.PickFolder(GetHwnd(), "选择包含 EvilWithin.exe 的游戏目录", initial);
                if (String.IsNullOrWhiteSpace(selected)) return;

                string validated = Library.ValidateGame(selected);
                library.Game = validated;
                await ValidateGameAsync(validated);
                SetStatus("游戏目录已保存：" + validated, "#2EC476");
            }
            catch (Exception ex)
            {
                ShowError("游戏目录无效", ex.Message);
            }
        }

        private async void ChooseZipFiles()
        {
            var dialog = new OpenFileDialog
            {
                Title = "选择一个或多个 Mod ZIP 压缩包",
                Filter = "Mod 压缩包 (*.zip)|*.zip",
                Multiselect = true
            };
            if (dialog.ShowDialog(this) == true && dialog.FileNames.Length > 0)
            {
                await HandleIncomingPathsAsync(dialog.FileNames);
            }
        }

        private async void ChooseDirectFolder()
        {
            try
            {
                string selected = FolderPicker.PickFolder(GetHwnd(), "选择包含 base\\generated 的已解压 Mod 目录", null);
                if (String.IsNullOrWhiteSpace(selected)) return;
                await HandleIncomingPathsAsync(new[] { selected });
            }
            catch (Exception ex)
            {
                ShowError("无法直挂目录", ex.Message);
            }
        }

        private void OnWindowDragOver(object sender, DragEventArgs e)
        {
            if (isBusy || e.Data == null || !e.Data.GetDataPresent(DataFormats.FileDrop))
            {
                e.Effects = DragDropEffects.None;
                dragOverlay.Visibility = Visibility.Collapsed;
                return;
            }

            string[] paths = e.Data.GetData(DataFormats.FileDrop) as string[];
            if (paths == null || paths.Length == 0)
            {
                e.Effects = DragDropEffects.None;
                dragOverlay.Visibility = Visibility.Collapsed;
                return;
            }

            int zipCount = paths.Count(p => File.Exists(p) && String.Equals(System.IO.Path.GetExtension(p), ".zip", StringComparison.OrdinalIgnoreCase));
            int dirCount = paths.Count(p => Directory.Exists(p));

            if (zipCount == 0 && dirCount == 0)
            {
                e.Effects = DragDropEffects.None;
                dragOverlay.Visibility = Visibility.Collapsed;
                return;
            }

            e.Effects = DragDropEffects.Copy;
            e.Handled = true;

            if (zipCount > 0 && dirCount > 0)
            {
                dragOverlayTitle.Text = String.Format("松开以导入 {0} 个 ZIP 并直挂 {1} 个目录", zipCount, dirCount);
                dragOverlaySub.Text = "ZIP 压缩包将导入管理器库，文件夹将以零拷贝方式直挂";
            }
            else if (zipCount > 0)
            {
                dragOverlayTitle.Text = zipCount == 1 ? "松开以导入 Mod ZIP" : String.Format("松开以批量导入 {0} 个 Mod ZIP", zipCount);
                dragOverlaySub.Text = "自动校验 base/generated 结构与中文路径编码";
            }
            else
            {
                dragOverlayTitle.Text = dirCount == 1 ? "松开以直挂 Mod 目录" : String.Format("松开以直挂 {0} 个 Mod 目录", dirCount);
                dragOverlaySub.Text = "零拷贝挂载含 base/generated 的已解压文件夹";
            }

            dragOverlay.Visibility = Visibility.Visible;
        }

        private void OnWindowDragLeave(object sender, DragEventArgs e)
        {
            Point pt = e.GetPosition(this);
            if (pt.X <= 0 || pt.Y <= 0 || pt.X >= ActualWidth || pt.Y >= ActualHeight)
                dragOverlay.Visibility = Visibility.Collapsed;
        }

        private async void OnWindowDrop(object sender, DragEventArgs e)
        {
            dragOverlay.Visibility = Visibility.Collapsed;
            if (isBusy || e.Data == null || !e.Data.GetDataPresent(DataFormats.FileDrop)) return;
            string[] paths = e.Data.GetData(DataFormats.FileDrop) as string[];
            if (paths != null && paths.Length > 0)
            {
                e.Handled = true;
                await HandleIncomingPathsAsync(paths);
            }
        }

        private async Task HandleIncomingPathsAsync(string[] paths)
        {
            if (isBusy || paths == null || paths.Length == 0) return;

            var validInputs = paths.Where(p =>
                (File.Exists(p) && String.Equals(System.IO.Path.GetExtension(p), ".zip", StringComparison.OrdinalIgnoreCase)) ||
                Directory.Exists(p)).ToArray();

            if (validInputs.Length == 0) return;

            SetBusy(true, "正在处理拖入的 Mod 资源…");
            var failures = new List<string>();
            ModEntry lastAdded = null;
            int importedCount = 0;
            int linkedCount = 0;

            try
            {
                foreach (string path in validInputs)
                {
                    try
                    {
                        if (Directory.Exists(path))
                        {
                            lastAdded = await Task.Run(() => library.LinkFolder(path));
                            linkedCount++;
                        }
                        else
                        {
                            lastAdded = await Task.Run(() => library.ImportZip(path));
                            importedCount++;
                        }
                    }
                    catch (Exception ex)
                    {
                        failures.Add(System.IO.Path.GetFileName(path) + "：\n" + ex.Message);
                    }
                }

                RefreshEntries(lastAdded != null ? lastAdded.Id : null);

                if (lastAdded != null)
                {
                    if (importedCount > 0 && linkedCount > 0)
                        SetStatus(String.Format("已导入 {0} 个 ZIP 并直挂 {1} 个目录。", importedCount, linkedCount), "#2EC476");
                    else if (linkedCount > 0)
                        SetStatus("已直挂目录：" + lastAdded.Name, "#E8A838");
                    else
                        SetStatus("已导入 Mod：" + lastAdded.Name, "#2EC476");
                }
                else
                {
                    SetStatus("导入或直挂失败。", "#F87171");
                }

                if (failures.Count > 0)
                {
                    ModernDialog.Show(this, "部分项目未能添加", String.Join("\n\n", failures), DialogKind.Warning, "知道了");
                }
            }
            finally
            {
                SetBusy(false, null);
            }
        }

        private async void StartSelectedMod()
        {
            ModEntry entry = SelectedEntry();
            if (entry == null || isBusy) return;

            if (entry.FolderMissing)
            {
                ShowError("目录不存在", "找不到该 Mod 的资源目录，请重新添加。");
                return;
            }

            if (String.IsNullOrWhiteSpace(library.Game))
            {
                ChooseGameDirectory();
                if (String.IsNullOrWhiteSpace(library.Game)) return;
            }

            string gameDir = library.Game;
            string extraArgs = (extraArgsBox.Text ?? "").Trim();
            library.ExtraLaunchArgs = extraArgs;
            bool useHair = hairPhysicsToggle != null && hairPhysicsToggle.IsChecked == true;
            bool useFace = independentFaceToggle != null && independentFaceToggle.IsChecked == true;
            List<ModEntry> enabledAddons = library.GetEnabledAddons(allEntries);

            string desc = enabledAddons.Count > 0
                ? String.Format("「{0}」+ {1} 项功能 Mod", entry.Name, enabledAddons.Count)
                : "「" + entry.Name + "」";

            SetBusy(true, "正在准备并挂载" + desc + "…");
            try
            {
                string result = await Task.Run(() =>
                {
                    string launchOverlay = library.PrepareLaunchOverlay(entry, enabledAddons);
                    return NativeLoader.LaunchWithOverlay(gameDir, launchOverlay, null, null, extraArgs, 20000, useHair, useFace);
                });
                SetStatus("挂载成功！" + desc + "已随游戏启动。", "#2EC476");
                statusText.ToolTip = result;
            }
            catch (Exception ex)
            {
                ShowError("启动失败", ex.Message);
            }
            finally
            {
                SetBusy(false, null);
            }
        }

        private async void StartEnabledAddonsOnly()
        {
            if (isBusy) return;
            List<ModEntry> enabledAddons = library.GetEnabledAddons(allEntries);
            if (enabledAddons.Count == 0)
            {
                StartVanillaGame();
                return;
            }

            if (String.IsNullOrWhiteSpace(library.Game))
            {
                ChooseGameDirectory();
                if (String.IsNullOrWhiteSpace(library.Game)) return;
            }

            string gameDir = library.Game;
            string extraArgs = extraArgsBox != null ? (extraArgsBox.Text ?? "").Trim() : library.ExtraLaunchArgs;
            library.ExtraLaunchArgs = extraArgs;

            SetBusy(true, String.Format("正在以原版模型叠加 {0} 项功能性 Mod 启动游戏…", enabledAddons.Count));
            try
            {
                string result = await Task.Run(() =>
                {
                    string launchOverlay = library.PrepareLaunchOverlay(null, enabledAddons);
                    return NativeLoader.LaunchWithOverlay(gameDir, launchOverlay, null, null, extraArgs, 20000, false, false);
                });
                SetStatus(String.Format("已挂载 {0} 项功能性 Mod 并启动游戏。", enabledAddons.Count), "#2EC476");
                statusText.ToolTip = result;
            }
            catch (Exception ex)
            {
                ShowError("启动失败", ex.Message);
            }
            finally
            {
                SetBusy(false, null);
            }
        }

        private async void StartVanillaGame()
        {
            if (isBusy) return;
            if (String.IsNullOrWhiteSpace(library.Game))
            {
                ChooseGameDirectory();
                if (String.IsNullOrWhiteSpace(library.Game)) return;
            }

            string gameDir = library.Game;
            string extraArgs = extraArgsBox != null ? (extraArgsBox.Text ?? "").Trim() : library.ExtraLaunchArgs;

            SetBusy(true, "正在启动原版《恶灵附身》…");
            try
            {
                int pid = await Task.Run(() => NativeLoader.LaunchVanilla(gameDir, extraArgs));
                SetStatus("原版游戏已启动（PID " + pid + "）。", "#2EC476");
            }
            catch (Exception ex)
            {
                ShowError("原版启动失败", ex.Message);
            }
            finally
            {
                SetBusy(false, null);
            }
        }

        private void OpenSelectedFolder()
        {
            ModEntry entry = SelectedEntry();
            if (entry == null) return;
            try
            {
                if (Directory.Exists(entry.Overlay))
                    Process.Start("explorer.exe", "\"" + entry.Overlay + "\"");
                else
                    ShowError("目录不存在", "无法打开：" + entry.Overlay);
            }
            catch (Exception ex)
            {
                ShowError("无法打开目录", ex.Message);
            }
        }

        private void RemoveSelectedMod()
        {
            ModEntry entry = SelectedEntry();
            if (entry == null || isBusy) return;

            string title = entry.IsLinkedFolder ? "取消直挂目录" : "移除已入库 Mod";
            string prompt = entry.IsLinkedFolder
                ? "确定要从列表中取消直挂「" + entry.Name + "」吗？\n\n此操作仅移除快捷记录，不会删除硬盘上的任何原始文件。"
                : "确定要从管理器本地库中移除「" + entry.Name + "」吗？\n\n移除后如需再次使用，可重新拖入原始 ZIP 文件。";
            string confirm = entry.IsLinkedFolder ? "取消直挂" : "确认移除";

            if (!ModernDialog.Show(this, title, prompt, DialogKind.ConfirmDanger, confirm, "取消"))
                return;

            try
            {
                library.RemoveMod(entry);
                RefreshEntries(null);
                SetStatus((entry.IsLinkedFolder ? "已取消直挂：" : "已移除 Mod：") + entry.Name, "#94A3B8");
            }
            catch (Exception ex)
            {
                ShowError("移除失败", ex.Message);
            }
        }

        private void ShowError(string title, string message)
        {
            SetStatus(title + "：" + message.Replace("\r", " ").Replace("\n", " "), "#F87171");
            ModernDialog.Show(this, title, message, DialogKind.Warning, "知道了");
        }
    }
}
