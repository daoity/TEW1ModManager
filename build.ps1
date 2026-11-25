param(
    [string]$OutputFolder = (Join-Path $PSScriptRoot 'dist'),
    [string]$Compiler = (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe')
)

$ErrorActionPreference = 'Stop'

$framework = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319'
$wpfDir = Join-Path $framework 'WPF'
if (-not (Test-Path -LiteralPath $Compiler -PathType Leaf)) {
    throw "C# compiler not found: $Compiler"
}

$srcDir = Join-Path $PSScriptRoot 'src'
$output = (New-Item -ItemType Directory -Path $OutputFolder -Force).FullName
$iconPath = Join-Path $srcDir 'app.ico'

# Generate a sharp multi-resolution modern crimson emblem icon (PNG-encoded ICO)
Add-Type -AssemblyName System.Drawing
function New-AppIcon([string]$Path) {
    $sizes = @(16, 32, 48, 256)
    $pngBlobs = @()

    foreach ($sz in $sizes) {
        $bmp = New-Object System.Drawing.Bitmap($sz, $sz, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
        $g.Clear([System.Drawing.Color]::Transparent)

        $pad = [float]([Math]::Max(1, [Math]::Round($sz * 0.06)))
        $rectSize = [float]($sz - $pad * 2)
        $radius = [float]([Math]::Max(2, [Math]::Round($rectSize * 0.24)))

        # Rounded rectangle path
        $gp = New-Object System.Drawing.Drawing2D.GraphicsPath
        $d = $radius * 2
        $gp.AddArc($pad, $pad, $d, $d, 180, 90)
        $gp.AddArc($pad + $rectSize - $d, $pad, $d, $d, 270, 90)
        $gp.AddArc($pad + $rectSize - $d, $pad + $rectSize - $d, $d, $d, 0, 90)
        $gp.AddArc($pad, $pad + $rectSize - $d, $d, $d, 90, 90)
        $gp.CloseFigure()

        $rect = New-Object System.Drawing.RectangleF($pad, $pad, $rectSize, $rectSize)
        $bgBrush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
            $rect,
            [System.Drawing.Color]::FromArgb(255, 224, 58, 75),
            [System.Drawing.Color]::FromArgb(255, 128, 22, 36),
            45.0
        )
        $g.FillPath($bgBrush, $gp)

        # Subtle inner highlight border
        $borderPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(95, 255, 255, 255), [Math]::Max(1.0, $sz / 48.0))
        $g.DrawPath($borderPen, $gp)

        # Bold crisp "EW" lettering
        $fontSize = [float]($sz * 0.34)
        $font = New-Object System.Drawing.Font('Segoe UI', $fontSize, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
        $sf = New-Object System.Drawing.StringFormat
        $sf.Alignment = [System.Drawing.StringAlignment]::Center
        $sf.LineAlignment = [System.Drawing.StringAlignment]::Center
        $textRect = New-Object System.Drawing.RectangleF(0, [float]($sz * 0.02), $sz, $sz)
        $g.DrawString('EW', $font, [System.Drawing.Brushes]::White, $textRect, $sf)

        $ms = New-Object System.IO.MemoryStream
        $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
        $pngBlobs += ,($ms.ToArray())

        $ms.Dispose(); $sf.Dispose(); $font.Dispose(); $borderPen.Dispose(); $bgBrush.Dispose(); $gp.Dispose(); $g.Dispose(); $bmp.Dispose()
    }

    $fs = [System.IO.File]::Create($Path)
    $bw = New-Object System.IO.BinaryWriter($fs)
    try {
        # ICONDIR header
        $bw.Write([uint16]0)
        $bw.Write([uint16]1)
        $bw.Write([uint16]$sizes.Count)

        $offset = 6 + (16 * $sizes.Count)
        for ($i = 0; $i -lt $sizes.Count; $i++) {
            $sz = $sizes[$i]
            $blob = $pngBlobs[$i]
            $bw.Write([byte]($(if ($sz -ge 256) { 0 } else { $sz })))
            $bw.Write([byte]($(if ($sz -ge 256) { 0 } else { $sz })))
            $bw.Write([byte]0)
            $bw.Write([byte]0)
            $bw.Write([uint16]1)
            $bw.Write([uint16]32)
            $bw.Write([uint32]$blob.Length)
            $bw.Write([uint32]$offset)
            $offset += $blob.Length
        }
        foreach ($blob in $pngBlobs) {
            $bw.Write($blob)
        }
    }
    finally {
        $bw.Dispose()
        $fs.Dispose()
    }
}

New-AppIcon -Path $iconPath

$frameworkRefs = @(
    'mscorlib.dll',
    'System.dll',
    'System.Core.dll',
    'System.IO.Compression.dll',
    'System.IO.Compression.FileSystem.dll',
    'System.Xml.dll',
    'System.Xml.Linq.dll',
    'System.Xaml.dll'
)
$wpfRefs = @(
    'WindowsBase.dll',
    'PresentationCore.dll',
    'PresentationFramework.dll'
)

$outExe = Join-Path $output 'TEW1ModManager.exe'
$outPureExe = Join-Path $output 'TEW1ModManager_纯净版.exe'
$baseCompilerArgs = @(
    '/nologo',
    '/noconfig',
    '/target:winexe',
    '/platform:x64',
    '/optimize+',
    '/codepage:65001',
    ('/win32manifest:' + (Join-Path $srcDir 'app.manifest')),
    ('/win32icon:' + $iconPath)
)

foreach ($r in $frameworkRefs) {
    $baseCompilerArgs += '/r:' + (Join-Path $framework $r)
}
foreach ($r in $wpfRefs) {
    $baseCompilerArgs += '/r:' + (Join-Path $wpfDir $r)
}

$sources = @(
    (Join-Path $srcDir 'NativeLoader.cs'),
    (Join-Path $srcDir 'OverlayLibrary.cs'),
    (Join-Path $srcDir 'FolderPicker.cs'),
    (Join-Path $srcDir 'AppTheme.cs'),
    (Join-Path $srcDir 'Dialogs.cs'),
    (Join-Path $srcDir 'TangoExtractor.cs'),
    (Join-Path $srcDir 'MainWindow.cs'),
    (Join-Path $srcDir 'Program.cs')
)

# 1. Build 100% pure loose-asset Manager & Loader (zero embedded runtime DLL)
$pureArgs = $baseCompilerArgs + ('/out:' + $outPureExe)
& $Compiler @pureArgs @sources
if ($LASTEXITCODE -ne 0) {
    throw "Compilation failed for pure EXE with exit code $LASTEXITCODE"
}

# 2. Build clean generic Manager & Loader (with embedded generic tew1_dyn_runtime.dll if present)
$fullArgs = $baseCompilerArgs + ('/out:' + $outExe)
$runtimeCandidates = @(
    (Join-Path $PSScriptRoot 'runtime_src\tew1_dyn_runtime.dll'),
    (Join-Path $output 'tew1_dyn_runtime.dll'),
    (Join-Path $output 'Data\runtime\tew1_dyn_runtime.dll')
)
$runtimeDll = $runtimeCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if ($runtimeDll) {
    $fullArgs += ('/resource:' + $runtimeDll + ',tew1_dyn_runtime.dll')
}
& $Compiler @fullArgs @sources
if ($LASTEXITCODE -ne 0) {
    throw "Compilation failed for main EXE with exit code $LASTEXITCODE"
}

$pureInfo = Get-Item -LiteralPath $outPureExe
$exeInfo = Get-Item -LiteralPath $outExe
Write-Output ("Built: {0} ({1:N0} bytes)" -f $pureInfo.FullName, $pureInfo.Length)
Write-Output ("Built: {0} ({1:N0} bytes)" -f $exeInfo.FullName, $exeInfo.Length)
