using System;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Markup;
using System.Windows.Media;

namespace TEW1
{
    internal static class AppTheme
    {
        private const int DWMWA_USE_IMMERSIVE_DARK_MODE = 20;
        private const int DWMWA_WINDOW_CORNER_PREFERENCE = 33;
        private const int DWMWA_BORDER_COLOR = 34;
        private const int DWMWCP_ROUND = 2;

        [DllImport("dwmapi.dll", PreserveSig = true)]
        private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int attrValue, int attrSize);

        internal static void ApplyModernWindowChrome(Window window)
        {
            window.SourceInitialized += delegate
            {
                try
                {
                    IntPtr hwnd = new WindowInteropHelper(window).Handle;
                    if (hwnd == IntPtr.Zero) return;
                    int dark = 1;
                    DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ref dark, sizeof(int));
                    int round = DWMWCP_ROUND;
                    DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ref round, sizeof(int));
                    // Subtle dark slate border (#2A3446 in COLORREF 0x00BBGGRR)
                    int borderColor = 0x0046342A;
                    DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR, ref borderColor, sizeof(int));
                }
                catch { }
            };
        }

        internal static SolidColorBrush Brush(string hex)
        {
            var b = new SolidColorBrush((Color)ColorConverter.ConvertFromString(hex));
            b.Freeze();
            return b;
        }

        internal static ResourceDictionary CreateResources()
        {
            const string xaml = @"
<ResourceDictionary xmlns='http://schemas.microsoft.com/winfx/2006/xaml/presentation'
                    xmlns:x='http://schemas.microsoft.com/winfx/2006/xaml'>

    <SolidColorBrush x:Key='BgCanvas' Color='#0D1016'/>
    <SolidColorBrush x:Key='BgSurface' Color='#141923'/>
    <SolidColorBrush x:Key='BgCard' Color='#1A212E'/>
    <SolidColorBrush x:Key='BgCardHover' Color='#222B3C'/>
    <SolidColorBrush x:Key='BgInput' Color='#10151E'/>
    <SolidColorBrush x:Key='BorderSubtle' Color='#232C3D'/>
    <SolidColorBrush x:Key='BorderStrong' Color='#334157'/>

    <SolidColorBrush x:Key='TextPrimary' Color='#F1F5F9'/>
    <SolidColorBrush x:Key='TextSecondary' Color='#94A3B8'/>
    <SolidColorBrush x:Key='TextMuted' Color='#64748B'/>

    <SolidColorBrush x:Key='AccentPrimary' Color='#DC3545'/>
    <SolidColorBrush x:Key='AccentHover' Color='#EB4656'/>
    <SolidColorBrush x:Key='AccentPressed' Color='#BE2636'/>
    <SolidColorBrush x:Key='AccentSoft' Color='#2A161B'/>
    <SolidColorBrush x:Key='AccentBorder' Color='#702430'/>

    <SolidColorBrush x:Key='AmberMain' Color='#E8A838'/>
    <SolidColorBrush x:Key='AmberSoft' Color='#292113'/>
    <SolidColorBrush x:Key='AmberBorder' Color='#664C1E'/>

    <SolidColorBrush x:Key='GreenMain' Color='#2EC476'/>
    <SolidColorBrush x:Key='GreenSoft' Color='#122B20'/>
    <SolidColorBrush x:Key='GreenBorder' Color='#1F5B3E'/>

    <SolidColorBrush x:Key='BlueMain' Color='#4DA3FF'/>
    <SolidColorBrush x:Key='BlueSoft' Color='#142338'/>
    <SolidColorBrush x:Key='BlueBorder' Color='#264974'/>

    <!-- Primary Crimson CTA Button -->
    <Style x:Key='PrimaryButton' TargetType='Button'>
        <Setter Property='Background' Value='{StaticResource AccentPrimary}'/>
        <Setter Property='Foreground' Value='#FFFFFF'/>
        <Setter Property='FontWeight' Value='SemiBold'/>
        <Setter Property='FontSize' Value='14'/>
        <Setter Property='Padding' Value='18,10'/>
        <Setter Property='BorderThickness' Value='0'/>
        <Setter Property='Cursor' Value='Hand'/>
        <Setter Property='FocusVisualStyle' Value='{x:Null}'/>
        <Setter Property='Template'>
            <Setter.Value>
                <ControlTemplate TargetType='Button'>
                    <Border x:Name='bd'
                            Background='{TemplateBinding Background}'
                            CornerRadius='9'
                            Padding='{TemplateBinding Padding}'>
                        <ContentPresenter HorizontalAlignment='Center' VerticalAlignment='Center'/>
                    </Border>
                    <ControlTemplate.Triggers>
                        <Trigger Property='IsMouseOver' Value='True'>
                            <Setter TargetName='bd' Property='Background' Value='{StaticResource AccentHover}'/>
                        </Trigger>
                        <Trigger Property='IsPressed' Value='True'>
                            <Setter TargetName='bd' Property='Background' Value='{StaticResource AccentPressed}'/>
                        </Trigger>
                        <Trigger Property='IsEnabled' Value='False'>
                            <Setter TargetName='bd' Property='Background' Value='#252B37'/>
                            <Setter Property='Foreground' Value='#64748B'/>
                            <Setter Property='Cursor' Value='Arrow'/>
                        </Trigger>
                    </ControlTemplate.Triggers>
                </ControlTemplate>
            </Setter.Value>
        </Setter>
    </Style>

    <!-- Secondary Slate Button -->
    <Style x:Key='SecondaryButton' TargetType='Button'>
        <Setter Property='Background' Value='#1C2433'/>
        <Setter Property='Foreground' Value='#E2E8F0'/>
        <Setter Property='BorderBrush' Value='#2D384D'/>
        <Setter Property='BorderThickness' Value='1'/>
        <Setter Property='FontWeight' Value='Medium'/>
        <Setter Property='FontSize' Value='13'/>
        <Setter Property='Padding' Value='14,8'/>
        <Setter Property='Cursor' Value='Hand'/>
        <Setter Property='FocusVisualStyle' Value='{x:Null}'/>
        <Setter Property='Template'>
            <Setter.Value>
                <ControlTemplate TargetType='Button'>
                    <Border x:Name='bd'
                            Background='{TemplateBinding Background}'
                            BorderBrush='{TemplateBinding BorderBrush}'
                            BorderThickness='{TemplateBinding BorderThickness}'
                            CornerRadius='8'
                            Padding='{TemplateBinding Padding}'>
                        <ContentPresenter HorizontalAlignment='Center' VerticalAlignment='Center'/>
                    </Border>
                    <ControlTemplate.Triggers>
                        <Trigger Property='IsMouseOver' Value='True'>
                            <Setter TargetName='bd' Property='Background' Value='#263145'/>
                            <Setter TargetName='bd' Property='BorderBrush' Value='#3D4C68'/>
                        </Trigger>
                        <Trigger Property='IsPressed' Value='True'>
                            <Setter TargetName='bd' Property='Background' Value='#171E2B'/>
                        </Trigger>
                        <Trigger Property='IsEnabled' Value='False'>
                            <Setter TargetName='bd' Property='Opacity' Value='0.45'/>
                            <Setter Property='Cursor' Value='Arrow'/>
                        </Trigger>
                    </ControlTemplate.Triggers>
                </ControlTemplate>
            </Setter.Value>
        </Setter>
    </Style>

    <!-- Ghost Subtle Button -->
    <Style x:Key='GhostButton' TargetType='Button'>
        <Setter Property='Background' Value='Transparent'/>
        <Setter Property='Foreground' Value='#94A3B8'/>
        <Setter Property='BorderThickness' Value='0'/>
        <Setter Property='FontSize' Value='12.5'/>
        <Setter Property='Padding' Value='10,6'/>
        <Setter Property='Cursor' Value='Hand'/>
        <Setter Property='FocusVisualStyle' Value='{x:Null}'/>
        <Setter Property='Template'>
            <Setter.Value>
                <ControlTemplate TargetType='Button'>
                    <Border x:Name='bd'
                            Background='{TemplateBinding Background}'
                            CornerRadius='7'
                            Padding='{TemplateBinding Padding}'>
                        <ContentPresenter HorizontalAlignment='Center' VerticalAlignment='Center'/>
                    </Border>
                    <ControlTemplate.Triggers>
                        <Trigger Property='IsMouseOver' Value='True'>
                            <Setter TargetName='bd' Property='Background' Value='#212A3B'/>
                            <Setter Property='Foreground' Value='#F1F5F9'/>
                        </Trigger>
                        <Trigger Property='IsPressed' Value='True'>
                            <Setter TargetName='bd' Property='Background' Value='#18202D'/>
                        </Trigger>
                        <Trigger Property='IsEnabled' Value='False'>
                            <Setter TargetName='bd' Property='Opacity' Value='0.4'/>
                            <Setter Property='Cursor' Value='Arrow'/>
                        </Trigger>
                    </ControlTemplate.Triggers>
                </ControlTemplate>
            </Setter.Value>
        </Setter>
    </Style>

    <!-- Danger Outline Button -->
    <Style x:Key='DangerButton' TargetType='Button'>
        <Setter Property='Background' Value='#23161B'/>
        <Setter Property='Foreground' Value='#F87171'/>
        <Setter Property='BorderBrush' Value='#5C232C'/>
        <Setter Property='BorderThickness' Value='1'/>
        <Setter Property='FontSize' Value='12.5'/>
        <Setter Property='FontWeight' Value='Medium'/>
        <Setter Property='Padding' Value='12,7'/>
        <Setter Property='Cursor' Value='Hand'/>
        <Setter Property='FocusVisualStyle' Value='{x:Null}'/>
        <Setter Property='Template'>
            <Setter.Value>
                <ControlTemplate TargetType='Button'>
                    <Border x:Name='bd'
                            Background='{TemplateBinding Background}'
                            BorderBrush='{TemplateBinding BorderBrush}'
                            BorderThickness='{TemplateBinding BorderThickness}'
                            CornerRadius='8'
                            Padding='{TemplateBinding Padding}'>
                        <ContentPresenter HorizontalAlignment='Center' VerticalAlignment='Center'/>
                    </Border>
                    <ControlTemplate.Triggers>
                        <Trigger Property='IsMouseOver' Value='True'>
                            <Setter TargetName='bd' Property='Background' Value='#3A1B23'/>
                            <Setter TargetName='bd' Property='BorderBrush' Value='#992B3B'/>
                            <Setter Property='Foreground' Value='#FCA5A5'/>
                        </Trigger>
                        <Trigger Property='IsPressed' Value='True'>
                            <Setter TargetName='bd' Property='Background' Value='#4A1E28'/>
                        </Trigger>
                        <Trigger Property='IsEnabled' Value='False'>
                            <Setter TargetName='bd' Property='Opacity' Value='0.4'/>
                            <Setter Property='Cursor' Value='Arrow'/>
                        </Trigger>
                    </ControlTemplate.Triggers>
                </ControlTemplate>
            </Setter.Value>
        </Setter>
    </Style>

    <!-- Window Caption Button -->
    <Style x:Key='CaptionButton' TargetType='Button'>
        <Setter Property='Background' Value='Transparent'/>
        <Setter Property='Foreground' Value='#94A3B8'/>
        <Setter Property='Width' Value='42'/>
        <Setter Property='Height' Value='34'/>
        <Setter Property='BorderThickness' Value='0'/>
        <Setter Property='FocusVisualStyle' Value='{x:Null}'/>
        <Setter Property='Template'>
            <Setter.Value>
                <ControlTemplate TargetType='Button'>
                    <Border x:Name='bd' Background='{TemplateBinding Background}' CornerRadius='6' Margin='2,4'>
                        <ContentPresenter HorizontalAlignment='Center' VerticalAlignment='Center'/>
                    </Border>
                    <ControlTemplate.Triggers>
                        <Trigger Property='IsMouseOver' Value='True'>
                            <Setter TargetName='bd' Property='Background' Value='#222B3B'/>
                            <Setter Property='Foreground' Value='#F8FAFC'/>
                        </Trigger>
                        <Trigger Property='IsPressed' Value='True'>
                            <Setter TargetName='bd' Property='Background' Value='#2C364A'/>
                        </Trigger>
                    </ControlTemplate.Triggers>
                </ControlTemplate>
            </Setter.Value>
        </Setter>
    </Style>

    <Style x:Key='CloseCaptionButton' TargetType='Button' BasedOn='{StaticResource CaptionButton}'>
        <Setter Property='Template'>
            <Setter.Value>
                <ControlTemplate TargetType='Button'>
                    <Border x:Name='bd' Background='{TemplateBinding Background}' CornerRadius='6' Margin='2,4'>
                        <ContentPresenter HorizontalAlignment='Center' VerticalAlignment='Center'/>
                    </Border>
                    <ControlTemplate.Triggers>
                        <Trigger Property='IsMouseOver' Value='True'>
                            <Setter TargetName='bd' Property='Background' Value='#C92A3A'/>
                            <Setter Property='Foreground' Value='#FFFFFF'/>
                        </Trigger>
                        <Trigger Property='IsPressed' Value='True'>
                            <Setter TargetName='bd' Property='Background' Value='#A61F2D'/>
                        </Trigger>
                    </ControlTemplate.Triggers>
                </ControlTemplate>
            </Setter.Value>
        </Setter>
    </Style>

    <!-- Chip Button for Launch Presets -->
    <Style x:Key='ChipButton' TargetType='Button'>
        <Setter Property='Background' Value='#18202E'/>
        <Setter Property='Foreground' Value='#94A3B8'/>
        <Setter Property='BorderBrush' Value='#283348'/>
        <Setter Property='BorderThickness' Value='1'/>
        <Setter Property='FontSize' Value='11.5'/>
        <Setter Property='Padding' Value='10,4'/>
        <Setter Property='Cursor' Value='Hand'/>
        <Setter Property='FocusVisualStyle' Value='{x:Null}'/>
        <Setter Property='Template'>
            <Setter.Value>
                <ControlTemplate TargetType='Button'>
                    <Border x:Name='bd'
                            Background='{TemplateBinding Background}'
                            BorderBrush='{TemplateBinding BorderBrush}'
                            BorderThickness='{TemplateBinding BorderThickness}'
                            CornerRadius='12'
                            Padding='{TemplateBinding Padding}'>
                        <ContentPresenter HorizontalAlignment='Center' VerticalAlignment='Center'/>
                    </Border>
                    <ControlTemplate.Triggers>
                        <Trigger Property='IsMouseOver' Value='True'>
                            <Setter TargetName='bd' Property='Background' Value='#222D40'/>
                            <Setter TargetName='bd' Property='BorderBrush' Value='#3F506E'/>
                            <Setter Property='Foreground' Value='#E2E8F0'/>
                        </Trigger>
                    </ControlTemplate.Triggers>
                </ControlTemplate>
            </Setter.Value>
        </Setter>
    </Style>

    <!-- Dark TextBox -->
    <Style x:Key='DarkTextBox' TargetType='TextBox'>
        <Setter Property='Background' Value='{StaticResource BgInput}'/>
        <Setter Property='Foreground' Value='{StaticResource TextPrimary}'/>
        <Setter Property='CaretBrush' Value='#F1F5F9'/>
        <Setter Property='SelectionBrush' Value='#DC3545'/>
        <Setter Property='BorderBrush' Value='#263042'/>
        <Setter Property='BorderThickness' Value='1'/>
        <Setter Property='Padding' Value='10,7'/>
        <Setter Property='FontSize' Value='13'/>
        <Setter Property='VerticalContentAlignment' Value='Center'/>
        <Setter Property='Template'>
            <Setter.Value>
                <ControlTemplate TargetType='TextBox'>
                    <Border x:Name='bd'
                            Background='{TemplateBinding Background}'
                            BorderBrush='{TemplateBinding BorderBrush}'
                            BorderThickness='{TemplateBinding BorderThickness}'
                            CornerRadius='8'>
                        <ScrollViewer x:Name='PART_ContentHost' Margin='2,0' VerticalAlignment='Center'/>
                    </Border>
                    <ControlTemplate.Triggers>
                        <Trigger Property='IsKeyboardFocused' Value='True'>
                            <Setter TargetName='bd' Property='BorderBrush' Value='#DC3545'/>
                        </Trigger>
                        <Trigger Property='IsMouseOver' Value='True'>
                            <Setter TargetName='bd' Property='BorderBrush' Value='#3A4A64'/>
                        </Trigger>
                    </ControlTemplate.Triggers>
                </ControlTemplate>
            </Setter.Value>
        </Setter>
    </Style>

    <!-- Modern Pill Toggle Switch (CheckBox) -->
    <Style x:Key='ModernToggle' TargetType='CheckBox'>
        <Setter Property='Foreground' Value='#E2E8F0'/>
        <Setter Property='FontSize' Value='12.5'/>
        <Setter Property='Cursor' Value='Hand'/>
        <Setter Property='FocusVisualStyle' Value='{x:Null}'/>
        <Setter Property='Template'>
            <Setter.Value>
                <ControlTemplate TargetType='CheckBox'>
                    <StackPanel Orientation='Horizontal' VerticalAlignment='Center'>
                        <Border x:Name='track' Width='34' Height='19' CornerRadius='9.5'
                                Background='#263042' BorderBrush='#34425B' BorderThickness='1'
                                Margin='0,0,8,0' VerticalAlignment='Center'>
                            <Ellipse x:Name='knob' Width='13' Height='13' Fill='#94A3B8'
                                     HorizontalAlignment='Left' VerticalAlignment='Center' Margin='2,0'/>
                        </Border>
                        <ContentPresenter VerticalAlignment='Center'/>
                    </StackPanel>
                    <ControlTemplate.Triggers>
                        <Trigger Property='IsChecked' Value='True'>
                            <Setter TargetName='track' Property='Background' Value='#DC3545'/>
                            <Setter TargetName='track' Property='BorderBrush' Value='#EB4656'/>
                            <Setter TargetName='knob' Property='Fill' Value='#FFFFFF'/>
                            <Setter TargetName='knob' Property='HorizontalAlignment' Value='Right'/>
                        </Trigger>
                        <Trigger Property='IsEnabled' Value='False'>
                            <Setter Property='Opacity' Value='0.45'/>
                        </Trigger>
                    </ControlTemplate.Triggers>
                </ControlTemplate>
            </Setter.Value>
        </Setter>
    </Style>

    <!-- Thin Modern ScrollBar -->
    <Style TargetType='ScrollBar'>
        <Setter Property='Width' Value='7'/>
        <Setter Property='MinWidth' Value='7'/>
        <Setter Property='Background' Value='Transparent'/>
        <Setter Property='Template'>
            <Setter.Value>
                <ControlTemplate TargetType='ScrollBar'>
                    <Grid Background='Transparent' Margin='1,2'>
                        <Track x:Name='PART_Track' IsDirectionReversed='True'>
                            <Track.Thumb>
                                <Thumb>
                                    <Thumb.Template>
                                        <ControlTemplate TargetType='Thumb'>
                                            <Border x:Name='thumb' Background='#2D384C' CornerRadius='3.5'/>
                                            <ControlTemplate.Triggers>
                                                <Trigger Property='IsMouseOver' Value='True'>
                                                    <Setter TargetName='thumb' Property='Background' Value='#465672'/>
                                                </Trigger>
                                                <Trigger Property='IsDragging' Value='True'>
                                                    <Setter TargetName='thumb' Property='Background' Value='#64789B'/>
                                                </Trigger>
                                            </ControlTemplate.Triggers>
                                        </ControlTemplate>
                                    </Thumb.Template>
                                </Thumb>
                            </Track.Thumb>
                        </Track>
                    </Grid>
                </ControlTemplate>
            </Setter.Value>
        </Setter>
    </Style>

    <!-- Clean Card ListBoxItem -->
    <Style x:Key='ModCardItemStyle' TargetType='ListBoxItem'>
        <Setter Property='Background' Value='Transparent'/>
        <Setter Property='Padding' Value='0'/>
        <Setter Property='Margin' Value='0,0,0,7'/>
        <Setter Property='HorizontalContentAlignment' Value='Stretch'/>
        <Setter Property='FocusVisualStyle' Value='{x:Null}'/>
        <Setter Property='Template'>
            <Setter.Value>
                <ControlTemplate TargetType='ListBoxItem'>
                    <Border x:Name='card'
                            Background='#181F2C'
                            BorderBrush='#242E40'
                            BorderThickness='1'
                            CornerRadius='10'
                            Cursor='Hand'>
                        <ContentPresenter/>
                    </Border>
                    <ControlTemplate.Triggers>
                        <Trigger Property='IsMouseOver' Value='True'>
                            <Setter TargetName='card' Property='Background' Value='#1F2838'/>
                            <Setter TargetName='card' Property='BorderBrush' Value='#33415A'/>
                        </Trigger>
                        <Trigger Property='IsSelected' Value='True'>
                            <Setter TargetName='card' Property='Background' Value='#241920'/>
                            <Setter TargetName='card' Property='BorderBrush' Value='#9E2D3B'/>
                        </Trigger>
                    </ControlTemplate.Triggers>
                </ControlTemplate>
            </Setter.Value>
        </Setter>
    </Style>

</ResourceDictionary>";
            return (ResourceDictionary)XamlReader.Parse(xaml);
        }

        internal static UIElement Icon(string pathData, double size, Brush strokeOrFill, bool isFilled)
        {
            var path = new System.Windows.Shapes.Path
            {
                Data = Geometry.Parse(pathData),
                Width = size,
                Height = size,
                Stretch = Stretch.Uniform,
                VerticalAlignment = VerticalAlignment.Center,
                HorizontalAlignment = HorizontalAlignment.Center,
                SnapsToDevicePixels = false
            };
            if (isFilled)
            {
                path.Fill = strokeOrFill;
            }
            else
            {
                path.Stroke = strokeOrFill;
                path.StrokeThickness = 1.6;
                path.StrokeStartLineCap = PenLineCap.Round;
                path.StrokeEndLineCap = PenLineCap.Round;
                path.StrokeLineJoin = PenLineJoin.Round;
            }
            return path;
        }
    }
}
