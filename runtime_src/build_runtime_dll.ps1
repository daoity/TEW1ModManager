param(
    [string]$OutDir = (Join-Path $PSScriptRoot '..\dist')
)
$ErrorActionPreference = 'Stop'
$out = (New-Item -ItemType Directory -Path $OutDir -Force).FullName
$src = Join-Path $PSScriptRoot 'tew1_haruka_runtime.cpp'
$dll = Join-Path $out 'tew1_haruka_runtime.dll'
$obj = Join-Path $PSScriptRoot 'tew1_haruka_runtime.obj'
$packSrc = Join-Path $PSScriptRoot 'haruka_runtime.bin'
$packDst = Join-Path $out 'haruka_runtime.bin'

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vsRoot = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsRoot) { throw "Visual Studio x64 C++ toolchain not found." }
$vcvars = Join-Path $vsRoot 'VC\Auxiliary\Build\vcvars64.bat'

$bat = Join-Path $env:TEMP 'build_tew1_haruka_runtime.bat'
Set-Content -Path $bat -Encoding ASCII -Value "@echo off`r`ncall `"$vcvars`"`r`ncl /nologo /utf-8 /O2 /LD /EHsc /MT /W3 `"$src`" /Fe:`"$dll`" /Fo:`"$obj`" user32.lib d3d11.lib`r`n"
& cmd.exe /c $bat
if ($LASTEXITCODE -ne 0) { throw "cl.exe compilation failed with exit code $LASTEXITCODE" }

if (Test-Path -LiteralPath $packSrc) {
    Copy-Item -LiteralPath $packSrc -Destination $packDst -Force
}

$info = Get-Item -LiteralPath $dll
Write-Output ("Built: {0} ({1:N0} bytes)" -f $info.FullName, $info.Length)
