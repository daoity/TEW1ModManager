"""Build local loose BMD6 models that hide Sebastian in Chapter 1."""

import argparse
import hashlib
from pathlib import Path
import re
from struct import unpack, unpack_from
import tempfile
import zlib


CHAPTER = 'an_emergency_call.tangoresource'
MODELS = {
    'pl0000_ng': (31, '1ac4beb5b2d2aed2ea06bf117906eac5ce17aca5783c19db796e834f0b63e385'),
    'pl0001_ng': (8, 'c9a64878b494b52076edf6d2157f0d614b4987a617e48e12279569c832b24200'),
    'pl0006': (8, 'ab216fe96aad9125ee9aefbaf9d018c89befab81798990c41970e910703f0013'),
    'pl0007': (1, '5d538e2ee6c9899b107fcc10f2dec3e88404f87b43073fd84d4c949f875229b0'),
    'pl0010_ng': (9, '0f86898566c3863c523f1450a7eae8d82ef155f511645d4bef59d20b89f98eae'),
    'pl0011_ng': (9, '16fa5f3fc0282fbc31b850aa772c42ad3ecbcab0e244b46f251102a34f5a04e5'),
    'pl0020_ng': (15, '44e22cfcd8df61e6d94f96a9ad171520641cd23dd6df4a07a776972a6ab28f12'),
}
MATERIAL_SECTION = re.compile(rb'[\x20-\x7e]{4,151}\x01\x00\x00')


def stock_resource(archive, asset):
    with archive.open('rb') as file:
        if file.read(4) != bytes.fromhex('23 94 AB CD'):
            raise ValueError('Unexpected Tango archive header.')
        for _ in range(unpack('>I', file.read(4))[0]):
            for _ in range(2):
                file.seek(unpack('<I', file.read(4))[0], 1)
            file.seek(4, 1)
        file.seek(unpack('>I', file.read(4))[0])
        entry_count, _, _, groups, aliases = unpack('>5I', file.read(20))
        file.seek(2 * (groups + aliases), 1)
        strings_size, strings_count = unpack('>2I', file.read(8))
        strings = file.read(strings_size).split(b'\0')[:strings_count]
        name = strings.index(asset.encode('ascii'))
        index = file.read(entry_count * 16)
        matches = [(offset, packed, size) for key, offset, packed, size in unpack_rows(index) if key == name]
        if len(matches) != 1:
            raise ValueError(f'Expected one copy of {asset}, found {len(matches)}.')
        offset, packed, size = matches[0]
        file.seek(offset)
        data = file.read(packed)
    if size != packed:
        inflater = zlib.decompressobj(-15)
        data = inflater.decompress(data) + inflater.flush()
    if len(data) != size or data[:4] != b'\x1a\x36MM':
        raise ValueError('The stock BMD6 payload did not pass readback.')
    return data


def unpack_rows(data):
    for offset in range(0, len(data), 16):
        yield unpack_from('>4I', data, offset)


def hide_model(original, expected_sections):
    model = bytearray(original)
    ranges = []
    for match in MATERIAL_SECTION.finditer(original):
        offset = match.end() - 3
        if match.start() < 4 or unpack_from('<I', original, match.start() - 4)[0] != offset - match.start():
            continue
        vertices = unpack_from('>H', original, offset + 3)[0]
        triangles = unpack_from('>H', original, offset + 7)[0]
        start = offset + 33 + vertices * 32
        end = start + triangles * 6
        if vertices < 3 or triangles < 1 or end > len(original):
            raise ValueError('Invalid skin surface.')
        if max(unpack_from(f'>{3 * triangles}H', original, start)) >= vertices:
            raise ValueError('Unexpected skin triangle indices.')
        # A degenerate triangle has zero area. The original vertices, weights and sections stay valid.
        model[start:end] = bytes(end - start)
        ranges.append((start, end))
    if len(ranges) != expected_sections:
        raise ValueError(f'Expected {expected_sections} skin sections, found {len(ranges)}.')
    return bytes(model), ranges


def build(game, overlay):
    archive = game / 'base' / CHAPTER
    prepared = []
    for name, (sections, expected_hash) in MODELS.items():
        character = name.split('_', 1)[0]
        asset = f'generated/nextgen/characters/pl/{character}/model/{name}.bmd6model'
        stock = stock_resource(archive, asset)
        if hashlib.sha256(stock).hexdigest() != expected_hash:
            raise ValueError(f'{asset} does not match the Chapter 1 stock resource.')
        model, ranges = hide_model(stock, sections)
        destination = overlay / 'base' / asset
        if not destination.resolve().is_relative_to(overlay):
            raise ValueError('The destination resolves outside the requested overlay folder.')
        if destination.exists() and destination.read_bytes() != model:
            raise ValueError(f'A different model already exists at {destination}.')
        prepared.append((destination, model, ranges))
    for destination, model, ranges in prepared:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as file:
                temporary = Path(file.name)
                try:
                    file.write(model)
                except OSError:
                    file.close()
                    temporary.unlink(missing_ok=True)
                    raise
            try:
                temporary.rename(destination)
            finally:
                temporary.unlink(missing_ok=True)
        readback = destination.read_bytes()
        if readback != model:
            raise ValueError(f'Model readback differs at {destination}.')
        print(f'{destination.name} | {len(ranges)} surfaces | {hashlib.sha256(readback).hexdigest()}')
    return sum(len(model) for _, model, _ in prepared)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--overlay', type=Path, required=True)
    args = parser.parse_args()
    game = args.game.resolve()
    overlay = args.overlay.resolve()
    if game == overlay or overlay.is_relative_to(game) or game.is_relative_to(overlay):
        parser.error('Select an overlay directory separate from the game directory.')
    try:
        total = build(game, overlay)
    except (OSError, ValueError, zlib.error) as error:
        parser.exit(1, f'Demo build failed: {error}\n')
    print(f'{total} bytes in the generated local overlay at {overlay}')


if __name__ == '__main__':
    main()
