"""Launch the tested Windows build of TEW1 with a loose-asset overlay."""

import argparse
import ctypes as ct
from ctypes import wintypes as wt
import hashlib
from pathlib import Path
import struct
import subprocess
import time


EXE_SHA256 = '8737abc65d2b575cb6acb8c435dd7e2ce1053411a084b87f24e493b68df2c0ab'
LOOSE_RESOURCE_CHECK = 0x787EF
STOCK_CHECK = bytes.fromhex('83 3d d2 11 73 02 00 48 8b d9 74 7d 83 3d ae 62 a8 09 03 7d 74')
PRODUCTION_LIMIT = 18
ENABLED_CHECK = STOCK_CHECK[:PRODUCTION_LIMIT] + b'\x04' + STOCK_CHECK[PRODUCTION_LIMIT + 1:]
LOOSE_CVAR = 0x27A99C8
MODEL_OPEN_CALL = 0x18F67E
IMAGE_OPEN_CALL = 0x1BA9DB
WAVE_OPEN_CALL = 0x3141A1
WAVE_LANG_SUB_CALL = 0x313F52
SOUND_LOAD_CALL = 0x305DB2
SOUND_LOAD_WAV = 0x306040
SOUND_LOAD_GEN = 0x306D00
STOCK_MODEL_OPEN = bytes.fromhex('ff 90 48 01 00 00')
STOCK_WAVE_LANG_SUB = bytes.fromhex('e8 29 4d d6 ff')
PATCH_WAVE_LANG_BYPASS = bytes.fromhex('4c 89 c0 90 90')
STOCK_SOUND_LOAD = bytes.fromhex('e8 49 0f 00 00')
SOUND_LOAD_OVERLAY = bytearray.fromhex(' '.join((
    '48 83 ec 48',
    '48 89 4c 24 30',
    '48 89 54 24 38',
    '48 8b 41 08',
    '48 85 c0',
    '74 31',
    '48 89 44 24 28',
    '48 8d 54 24 20',
    'e8 00 00 00 00',
    '84 c0',
    '74 1e',
    '48 8b 4c 24 30',
    '48 c7 41 68 00 00 00 00',
    'c7 81 c4 00 00 00 01 00 00 00',
    'b0 01',
    '48 83 c4 48',
    'c3',
    '48 8b 4c 24 30',
    '48 8b 54 24 38',
    'e8 00 00 00 00',
    '48 83 c4 48',
    'c3',
)))
# The MD6 reader normally opens through the archive callbacks. Try the native
# filesystem with those callbacks disabled, then retry with the original flags.
MODEL_OPEN_OVERLAY = bytes.fromhex(' '.join((
    '48 83 ec 48',         # Allocate callback home space and save slots.
    '48 89 4c 24 28',      # Save filesystem object.
    '48 89 54 24 30',      # Save model path.
    '48 89 44 24 38',      # Save the filesystem vtable.
    '48 c7 44 24 20 00 00 00 00',
    '45 33 c0 45 33 c9',   # ReadFlag=false, unchanged final flags.
    'ff 90 48 01 00 00',
    '48 85 c0 75 1e',      # A loose file was found. Return it directly.
    '48 8b 4c 24 28',
    '48 8b 54 24 30',
    '48 8b 44 24 38',
    '41 b8 01 00 00 00',   # ReadFlag=true, the original archive path.
    '45 33 c9',
    'ff 90 48 01 00 00',
    '48 83 c4 48 c3',
)))


def kernel_api():
    api = ct.WinDLL('kernel32', use_last_error=True)
    pointer = wt.LPVOID
    dword = wt.DWORD
    handle = wt.HANDLE
    size = ct.c_size_t
    definitions = (
        ('OpenProcess', [dword, wt.BOOL, dword], handle),
        ('CloseHandle', [handle], wt.BOOL),
        ('K32EnumProcessModules', [handle, ct.POINTER(wt.HMODULE), dword, ct.POINTER(dword)], wt.BOOL),
        ('ReadProcessMemory', [handle, pointer, pointer, size, ct.POINTER(size)], wt.BOOL),
        ('WriteProcessMemory', [handle, pointer, pointer, size, ct.POINTER(size)], wt.BOOL),
        ('VirtualProtectEx', [handle, pointer, size, dword, ct.POINTER(dword)], wt.BOOL),
        ('VirtualAllocEx', [handle, pointer, size, dword, dword], pointer),
        ('FlushInstructionCache', [handle, pointer, size], wt.BOOL),
    )
    for name, args, result in definitions:
        function = getattr(api, name)
        function.argtypes = args
        function.restype = result
    return api


class GameProcess:
    def __init__(self, pid):
        self.api = kernel_api()
        # Query information, read/write memory and change this one code page's protection.
        self.handle = self.api.OpenProcess(0x0438, False, pid)
        if not self.handle:
            raise ct.WinError(ct.get_last_error())

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.api.CloseHandle(self.handle)

    def image_base(self):
        first_module = wt.HMODULE()
        required = wt.DWORD()
        ok = self.api.K32EnumProcessModules(
            self.handle, ct.byref(first_module), ct.sizeof(first_module), ct.byref(required)
        )
        return first_module.value if ok else None

    def read(self, address, count):
        data = ct.create_string_buffer(count)
        received = ct.c_size_t()
        if not self.api.ReadProcessMemory(self.handle, address, data, count, ct.byref(received)):
            return b''
        return data.raw[:received.value]

    def write_code_byte(self, address, value):
        self.write_code(address, value)

    def write_code(self, address, value):
        original_protection = wt.DWORD()
        size = len(value)
        if not self.api.VirtualProtectEx(self.handle, address, size, 0x40, ct.byref(original_protection)):
            raise ct.WinError(ct.get_last_error())
        try:
            data = ct.create_string_buffer(value)
            count = ct.c_size_t()
            if not self.api.WriteProcessMemory(self.handle, address, data, size, ct.byref(count)):
                raise ct.WinError(ct.get_last_error())
            if count.value != size or not self.api.FlushInstructionCache(self.handle, address, size):
                raise OSError('The in-memory resource check did not update.')
        finally:
            unused = wt.DWORD()
            if not self.api.VirtualProtectEx(self.handle, address, size, original_protection, ct.byref(unused)):
                raise ct.WinError(ct.get_last_error())

    def install_resource_open(self, base, sites):
        if any(self.read(base + site, len(STOCK_MODEL_OPEN)) != STOCK_MODEL_OPEN for site in sites):
            raise RuntimeError('A resource reader did not match the supported build.')
        for delta in range(0x10000000, 0x70000000, 0x10000):
            address = self.api.VirtualAllocEx(self.handle, base + delta, 4096, 0x3000, 0x20)
            if address:
                break
        else:
            raise RuntimeError('No address was available near the model resource reader.')
        self.write_code(address, MODEL_OPEN_OVERLAY)
        for offset in sites:
            site = base + offset
            instruction = b'\xe8' + struct.pack('<i', address - site - 5) + b'\x90'
            self.write_code(site, instruction)
            if self.read(site, len(instruction)) != instruction:
                raise OSError('A resource reader call did not update.')
        return address

    def install_sound_load(self, base, stub_addr):
        lang_site = base + WAVE_LANG_SUB_CALL
        if self.read(lang_site, len(STOCK_WAVE_LANG_SUB)) != STOCK_WAVE_LANG_SUB:
            raise RuntimeError('Wave language path call site did not match the supported build.')
        self.write_code(lang_site, PATCH_WAVE_LANG_BYPASS)
        if self.read(lang_site, len(PATCH_WAVE_LANG_BYPASS)) != PATCH_WAVE_LANG_BYPASS:
            raise OSError('Wave language bypass did not update.')
        site = base + SOUND_LOAD_CALL
        if self.read(site, len(STOCK_SOUND_LOAD)) != STOCK_SOUND_LOAD:
            raise RuntimeError('Sound loader call site did not match the supported build.')
        stub = bytearray(SOUND_LOAD_OVERLAY)
        struct.pack_into('<i', stub, 0x22, (base + SOUND_LOAD_WAV) - (stub_addr + 0x26))
        struct.pack_into('<i', stub, 0x53, (base + SOUND_LOAD_GEN) - (stub_addr + 0x57))
        self.write_code(stub_addr, bytes(stub))
        patch = b'\xe8' + struct.pack('<i', stub_addr - site - 5)
        self.write_code(site, patch)
        if self.read(site, len(patch)) != patch:
            raise OSError('Sound loader call did not update.')


def enable_overlay(child, has_textures=False, has_sounds=False, timeout=20):
    deadline = time.monotonic() + timeout
    with GameProcess(child.pid) as process:
        while time.monotonic() < deadline and child.poll() is None:
            base = process.image_base()
            if base and process.read(base + LOOSE_RESOURCE_CHECK, len(STOCK_CHECK)) == STOCK_CHECK:
                sites = [MODEL_OPEN_CALL]
                if has_textures:
                    sites.append(IMAGE_OPEN_CALL)
                if has_sounds:
                    sites.append(WAVE_OPEN_CALL)
                allocated = process.install_resource_open(base, sites)
                if has_sounds:
                    process.install_sound_load(base, allocated + 0x100)
                # Declarations may first be resolved while the map is in production-in-game mode.
                limit = b'\x05' if (has_textures or has_sounds) else b'\x04'
                expected = ENABLED_CHECK[:PRODUCTION_LIMIT] + limit + ENABLED_CHECK[PRODUCTION_LIMIT + 1:]
                process.write_code_byte(base + LOOSE_RESOURCE_CHECK + PRODUCTION_LIMIT, limit)
                if process.read(base + LOOSE_RESOURCE_CHECK, len(STOCK_CHECK)) != expected:
                    raise OSError('The game did not retain the expected in-memory resource check.')
                return base
            time.sleep(0.025)
    raise RuntimeError(f'The supported game resource reader did not appear (exit code {child.poll()}).')


def launch(game, overlay, save_root=None, cache_root=None, extra=(), exe_dir=None, startupinfo=None,
           quiet_game=False):
    find_window = ct.WinDLL('user32', use_last_error=True).FindWindowW
    find_window.argtypes = (wt.LPCWSTR, wt.LPCWSTR)
    find_window.restype = wt.HWND
    if any(find_window(name, None) for name in ('The Evil Within', 'The Evil Within WinConsole')):
        raise RuntimeError('The Evil Within already has an open window.')
    game = game.resolve(strict=True)
    overlay = overlay.resolve(strict=True)
    if not (game / 'base' / 'common.tangoresource').is_file():
        raise ValueError(f'Game base archives are missing from {game}.')
    if overlay == game or overlay.is_relative_to(game) or game.is_relative_to(overlay):
        raise ValueError('Select an overlay directory separate from the game directory.')
    if not (overlay / 'base' / 'generated').is_dir() and not (overlay / 'base' / 'sound').is_dir():
        raise ValueError('The overlay must contain a base/generated or base/sound resource directory.')
    exe = ((exe_dir or game) / 'EvilWithin.exe').resolve(strict=True)
    with exe.open('rb') as file:
        build = hashlib.file_digest(file, 'sha256').hexdigest()
    if build != EXE_SHA256:
        raise ValueError(f'Unsupported EvilWithin.exe SHA-256: {build}')
    command = [str(exe), '+set', 'fs_basepath', str(game), '+set', 'fs_installpath', str(overlay)]
    for name, path in (('fs_savepath', save_root), ('fs_cachepath', cache_root)):
        if path is not None:
            path = path.resolve()
            path.mkdir(parents=True, exist_ok=True)
            command.extend(('+set', name, str(path)))
    command.extend(extra)
    command.extend(('+set', 'resource_loadLooseFiles', '1'))
    streams = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) if quiet_game else {}
    child = subprocess.Popen(command, cwd=exe.parent, startupinfo=startupinfo, **streams)
    try:
        base = enable_overlay(
            child,
            (overlay / 'base' / 'generated' / 'textures').is_dir(),
            (overlay / 'base' / 'sound').is_dir(),
        )
    except BaseException:
        if child.poll() is None:
            child.terminate()
            child.wait()
        raise
    return child, base


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--overlay', type=Path, required=True)
    parser.add_argument('--save-root', type=Path)
    parser.add_argument('--cache-root', type=Path)
    parser.add_argument('--quiet-game', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if struct.calcsize('P') != 8 or not hasattr(ct, 'WinDLL'):
        parser.error('Use 64-bit Python 3.11 or newer on Windows.')
    try:
        child, _ = launch(args.game, args.overlay, args.save_root, args.cache_root, quiet_game=args.quiet_game)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f'Launch failed: {error}\n')
    print(f'Loose resources enabled for EvilWithin.exe (PID {child.pid}).')


if __name__ == '__main__':
    main()
