"""Read and write the TEW1 PC BMD6 skeletal model layout."""

from dataclasses import dataclass
from struct import pack, pack_into, unpack_from
import re

import numpy as np


MAGIC = b'\x1a\x36MM'


def string_at(data, offset):
    size, = unpack_from('<I', data, offset)
    if not 1 <= size <= 512 or offset + size + 4 > len(data):
        raise ValueError(f'Invalid length-prefixed string at {offset:#x}.')
    end = offset + size + 4
    return data[offset + 4:end].decode('ascii'), end


def string(value):
    encoded = value.encode('ascii')
    return pack('<I', len(encoded)) + encoded


@dataclass
class Skeleton:
    names: list
    parents: tuple
    remap: bytes
    inverse: np.ndarray
    end: int

    @property
    def joints(self):
        return {
            name: -np.linalg.solve(matrix[:, :3], matrix[:, 3])
            for name, matrix in zip(self.names, self.inverse)
        }


def skeleton(data):
    names_start = data.index(b'\x06\0\0\0origin')
    names = []
    cursor = names_start
    while cursor < len(data):
        try:
            name, end = string_at(data, cursor)
        except (UnicodeDecodeError, ValueError):
            break
        if not re.fullmatch(r'[A-Za-z0-9_]+', name):
            break
        names.append(name)
        cursor = end
    count = len(names)
    padded = (count + 7) & ~7
    transforms = 93
    parent_offset = transforms + padded * 40
    parents = unpack_from(f'>{padded}H', data, parent_offset)
    if parents[0] != 0xFFFF or any(parent != 0xFFFF and parent >= i for i, parent in enumerate(parents)):
        raise ValueError('Invalid skeleton parent table.')
    if any(parent != 0xFFFF for parent in parents[count:]):
        raise ValueError('Unexpected skeleton padding.')
    quats = np.frombuffer(data, dtype='>f4', count=padded * 4, offset=transforms).reshape(-1, 4)
    if not np.allclose(np.linalg.norm(quats[:count], axis=1), 1.0, atol=0.01):
        raise ValueError('Invalid skeleton quaternion table.')
    for start in range(cursor, min(cursor + 1024, len(data) - padded + 1)):
        remap = data[start:start + padded]
        if sorted(remap) == list(range(padded)):
            break
    else:
        raise ValueError('Missing skeleton remap table.')
    inverse = np.frombuffer(data, dtype='>f4', count=padded * 12, offset=start + padded).reshape(-1, 3, 4)
    return Skeleton(names, parents[:count], remap[:count], inverse[:count].astype(float), start + padded * 49)


@dataclass
class Surface:
    name: str
    material: str
    vertices: bytes
    indices: np.ndarray
    flags: bytes
    trailer: bytes

    @property
    def count(self):
        return len(self.vertices) // 32

    @property
    def positions(self):
        return np.ndarray((self.count, 3), dtype='>f4', buffer=self.vertices, strides=(32, 4))

    def encode(self):
        if not 3 <= self.count <= 65535 or not 1 <= len(self.indices) <= 65535:
            raise ValueError(f'Out-of-range vertex or triangle count for {self.name}.')
        if np.min(self.indices) < 0 or np.max(self.indices) >= self.count:
            raise ValueError(f'Out-of-range triangle index for {self.name}.')
        lower = self.positions.min(axis=0)
        upper = self.positions.max(axis=0)
        header = b'\x01\x00\x00' + pack('>H', self.count) + self.flags
        header += pack('>H6f', len(self.indices), *lower, *upper)
        return string(self.name) + string(self.material) + header + self.vertices + self.indices.astype('>u2').tobytes() + self.trailer


@dataclass
class Model:
    prefix: bytes
    skeleton: Skeleton
    surfaces: list
    material_ranges: list


def read_model(data):
    if data[:4] != MAGIC or data[-4:] != MAGIC:
        raise ValueError('Invalid BMD6 file signature.')
    skel = skeleton(data)
    count, = unpack_from('>I', data, skel.end + 24)
    cursor = skel.end + 28
    surfaces = []
    for _ in range(count):
        name, cursor = string_at(data, cursor)
        material, cursor = string_at(data, cursor)
        if data[cursor:cursor + 3] != b'\x01\0\0':
            raise ValueError(f'Unknown mesh encoding on {name}.')
        vertices, flags, triangles = unpack_from('>H2sH', data, cursor + 3)
        start = cursor + 33
        end = start + vertices * 32
        trailer = end + triangles * 6
        indices = np.frombuffer(data, dtype='>u2', count=triangles * 3, offset=end).reshape(-1, 3)
        if max(indices.reshape(-1), default=-1) >= vertices:
            raise ValueError(f'Invalid triangle indices on {name}.')
        surfaces.append(Surface(name, material, data[start:end], indices, flags, data[trailer:trailer + 11]))
        cursor = trailer + 11
    range_count, = unpack_from('>I', data, cursor)
    cursor += 4
    ranges = []
    for _ in range(range_count):
        material, cursor = string_at(data, cursor)
        index, lower, upper = unpack_from('>3I', data, cursor)
        ranges.append((material, index, lower, upper))
        cursor += 12
    if cursor != len(data) - 4:
        raise ValueError('Unexpected bytes after the material range table.')
    return Model(data[:skel.end], skel, surfaces, ranges)


def write_model(model, surfaces):
    positions = np.concatenate([surface.positions for surface in surfaces])
    bounds = pack('>6fI', *positions.min(axis=0), *positions.max(axis=0), len(surfaces))
    ranges = bytearray(pack('>I', len(surfaces)))
    for index, surface in enumerate(surfaces):
        ranges.extend(string(surface.material) + pack('>3I', index, 0, surface.count - 1))
    return model.prefix + bounds + b''.join(surface.encode() for surface in surfaces) + bytes(ranges) + MAGIC


def append_test_bone(model, name, parent, position):
    """Add one child while retaining the retail skeleton's table capacities."""
    stock = bytearray(model.prefix)
    skel = model.skeleton
    index = len(skel.names)
    padded = (index + 7) & ~7
    if index == padded or parent not in skel.names:
        raise ValueError('This model lacks a usable padding slot or parent.')
    parent_index = skel.names.index(parent)
    transforms = 93
    parent_offset = transforms + 40 * padded
    id_offset = parent_offset + 2 * padded
    remap_offset = skel.end - padded * 49
    inverse_offset = remap_offset + padded
    cursor = stock.index(b'\x06\0\0\0origin')
    for _ in skel.names:
        _, cursor = string_at(stock, cursor)
    count_offset = 47
    if unpack_from('>H', stock, count_offset)[0] != index:
        raise ValueError('Unexpected skeleton header count.')
    # The new joint uses its parent's world orientation and identity local rotation.
    inv_parent = skel.inverse[parent_index]
    local = inv_parent[:, :3] @ position + inv_parent[:, 3]
    inverse_translation = -(inv_parent[:, :3] @ position)
    pack_into('>H', stock, count_offset, index + 1)
    pack_into('>4f', stock, transforms + index * 16, 0.0, 0.0, 0.0, 1.0)
    pack_into('>3f', stock, transforms + padded * 28 + index * 12, *local)
    pack_into('>H', stock, parent_offset + index * 2, parent_index)
    ids = unpack_from(f'>{index}H', stock, id_offset)
    unused_id = max(ids) + 1
    if unused_id >= 0xFFFF:
        raise ValueError('No unused model-local joint ID.')
    pack_into('>H', stock, id_offset + index * 2, unused_id)
    matrix = np.column_stack((inv_parent[:, :3], inverse_translation))
    pack_into('>12f', stock, inverse_offset + index * 48, *matrix.reshape(-1))
    stock[cursor:cursor] = string(name)
    added = skeleton(bytes(stock))
    if added.names[-1] != name or not np.allclose(added.joints[name], position, atol=0.001):
        raise ValueError('Custom joint readback did not match.')
    return Model(bytes(stock), added, model.surfaces, model.material_ranges)
