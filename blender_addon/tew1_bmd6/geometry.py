"""Prepare periodic source UVs and projection-compatible TEW vertex frames."""

import numpy as np


EPSILON = 1e-8


def clip_polygon(polygon, source_uv, axis, boundary, lower):
    output = []
    if not polygon:
        return output
    previous = polygon[-1]
    previous_value = float(previous @ source_uv[:, axis]) - boundary
    for current in polygon:
        value = float(current @ source_uv[:, axis]) - boundary
        previous_inside = previous_value >= -EPSILON if lower else previous_value <= EPSILON
        inside = value >= -EPSILON if lower else value <= EPSILON
        if inside != previous_inside:
            proportion = previous_value / (previous_value - value)
            output.append(previous + (current - previous) * proportion)
        if inside:
            output.append(current)
        previous, previous_value = current, value
    return output


def periodic_uv(positions, normals, uv, skin, triangles, merge_skin):
    """Keep the PMX Repeat sampler result inside TEW's local texture tile."""
    points, directions, coordinates, weights = [], [], [], []
    result = []
    vertices = {}
    identity = np.eye(3)
    crossed = 0
    for face in triangles:
        source_uv = uv[face]
        minimum = np.floor(source_uv.min(axis=0) + EPSILON).astype(int)
        maximum = np.maximum(minimum, np.floor(source_uv.max(axis=0) - EPSILON).astype(int))
        crossed += bool(np.any(maximum != minimum))
        if np.any(maximum - minimum > 8):
            raise ValueError('A triangle spans more than eight repeating UV tiles.')
        for u in range(minimum[0], maximum[0] + 1):
            for v in range(minimum[1], maximum[1] + 1):
                tile = np.array((u, v))
                polygon = list(identity)
                if np.any(maximum != minimum):
                    for axis, limit in enumerate(tile):
                        polygon = clip_polygon(polygon, source_uv, axis, limit, True)
                        polygon = clip_polygon(polygon, source_uv, axis, limit + 1, False)
                if len(polygon) < 3:
                    continue
                output = []
                for coefficient in polygon:
                    source = tuple(sorted((int(index), round(float(fraction), 9))
                                          for index, fraction in zip(face, coefficient) if fraction > EPSILON))
                    key = (u, v, source)
                    index = vertices.get(key)
                    if index is None:
                        index = len(points)
                        vertices[key] = index
                        points.append(coefficient @ positions[face])
                        directions.append(coefficient @ normals[face])
                        coordinates.append(np.clip(coefficient @ source_uv - tile, 0, 1))
                        weights.append(skin[source[0][0]] if len(source) == 1 else merge_skin(skin[face], coefficient))
                    if not output or output[-1] != index:
                        output.append(index)
                if len(output) > 2 and output[-1] == output[0]:
                    output.pop()
                result.extend((output[0], output[i], output[i + 1]) for i in range(1, len(output) - 1)
                              if output[0] not in (output[i], output[i + 1]))
    return tuple(map(np.asarray, (points, directions, coordinates, weights, result))), crossed


def rebuild_corner_normals(points, source_normals, faces, skin):
    """Smooth connected skinned surfaces while keeping hair creases and boundaries."""
    import bpy

    # Match positions at the precision written to BMD6. Different skin weights
    # can pull coincident vertices apart as soon as the character moves.
    keys = np.column_stack((points.astype('f4'), skin))
    _, distinct, welded = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    order = [0, 2, 1]
    blender_faces = welded[faces[:, order]]
    coordinates = points[distinct].astype('f4')
    p = coordinates[blender_faces]
    face_normals = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    lengths = np.linalg.norm(face_normals, axis=1)
    face_normals /= np.maximum(lengths[:, None], EPSILON)

    mesh = bpy.data.meshes.new('BMD6 hair normal reconstruction')
    try:
        mesh.from_pydata(coordinates.tolist(), [], blender_faces.tolist(), shade_flat=False)
        corner_edges = np.empty(faces.size, dtype='i4')
        mesh.loops.foreach_get('edge_index', corner_edges)
        counts = np.bincount(corner_edges, minlength=len(mesh.edges))
        paired = np.flatnonzero(counts == 2)
        pairs = np.argsort(corner_edges, kind='stable')[(np.cumsum(counts) - 2)[paired, None] + [0, 1]]
        starts = blender_faces.ravel()
        ends = np.roll(blender_faces, -1, axis=1).ravel()
        first, second = pairs.T
        opposite = (starts[first] == ends[second]) & (ends[first] == starts[second])
        adjoining = face_normals[pairs // 3]
        direction = (adjoining[:, 0] * adjoining[:, 1]).sum(axis=1)
        sharp = np.ones(len(mesh.edges), dtype=bool)
        sharp[paired] = ~opposite | (direction < np.cos(np.deg2rad(50)))
        mesh.attributes.new('sharp_edge', 'BOOLEAN', 'EDGE').data.foreach_set('value', sharp)
        mesh.update()

        normals = np.empty((faces.size, 3), dtype='f4')
        mesh.corner_normals.foreach_get('vector', normals.ravel())
        normals = normals.reshape(-1, 3, 3)[:, order].reshape(-1, 3)
        invalid = ~np.isfinite(normals).all(axis=1) | (np.linalg.norm(normals, axis=1) < EPSILON)
        normals[invalid] = source_normals[faces.ravel()[invalid]]
        return normals
    finally:
        bpy.data.meshes.remove(mesh)


def mikk_corner_frames(points, normals, uv, faces):
    """Calculate MikkTSpace in Blender and return frames in BMD6 corner order."""
    import bpy

    # Blender expects the opposite front-face winding to the BMD6 stream.
    order = [0, 2, 1]
    blender_faces = faces[:, order]
    mesh = bpy.data.meshes.new('BMD6 tangent calculation')
    try:
        mesh.from_pydata(points.tolist(), [], blender_faces.tolist(), shade_flat=False)
        actual = np.empty(blender_faces.size, dtype='i4')
        mesh.loops.foreach_get('vertex_index', actual)
        if not np.array_equal(actual, blender_faces.ravel()):
            raise ValueError('Blender changed face corners during tangent calculation.')
        mesh.normals_split_custom_set_from_vertices(normals.tolist())
        layer = mesh.uv_layers.new(name='BMD6 UV')
        layer.uv.foreach_set('vector', uv[actual].astype('f4').ravel())
        mesh.calc_tangents(uvmap=layer.name)
        tangent = np.empty((len(actual), 3), dtype='f4')
        sign = np.empty(len(actual), dtype='f4')
        mesh.loops.foreach_get('tangent', tangent.ravel())
        mesh.loops.foreach_get('bitangent_sign', sign)
        return tangent.reshape(-1, 3, 3)[:, order].reshape(-1, 3), sign.reshape(-1, 3)[:, order].ravel()
    finally:
        bpy.data.meshes.remove(mesh)


def uv_directions(points, uv, faces):
    edges = points[faces][:, 1:] - points[faces][:, :1]
    texture_edges = uv[faces][:, 1:] - uv[faces][:, :1]
    u, v = np.moveaxis(texture_edges, 1, 0)
    determinant = u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]
    divisor = np.where(np.abs(determinant) > EPSILON, determinant, np.inf)[:, None]
    du = (edges[:, 0] * v[:, 1:] - edges[:, 1] * u[:, 1:]) / divisor
    dv = (edges[:, 1] * u[:, :1] - edges[:, 0] * v[:, :1]) / divisor
    return du.repeat(3, axis=0), dv.repeat(3, axis=0)
