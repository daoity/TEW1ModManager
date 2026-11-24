"""Position-based secondary motion for hair chains in the authoring rig."""

from mathutils import Vector


def collider_point(point, start, end):
    axis = end - start
    if axis.length_squared < 1e-12:
        return start
    t = min(1., max(0., (point - start).dot(axis) / axis.length_squared))
    return start + t * axis


def push_out(point, start, end, radius, fallback):
    nearest = collider_point(point, start, end)
    separation = point - nearest
    if separation.length >= radius:
        return Vector((0., 0., 0.))
    direction = separation if separation.length_squared > 1e-10 else fallback - nearest
    if direction.length_squared < 1e-10:
        direction = (end - start).cross(Vector((1., 0., 0.)))
    if direction.length_squared < 1e-10:
        direction = Vector((0., 1., 0.))
    return nearest + direction.normalized() * radius - point


class HairChain:
    def __init__(self, targets, settings):
        self.positions = [p.copy() for p in targets]
        self.previous = [p.copy() for p in targets]
        self.anchor = [p.copy() for p in targets]
        self.lengths = [(b - a).length for a, b in zip(targets, targets[1:])]
        if min(self.lengths) < 1e-4:
            raise ValueError('A hair chain has a zero-length segment.')
        self.stiffness = settings['stiffness']
        self.damping = settings['damping']
        self.gravity = Vector((0., 0., -settings['gravity']))
        self.radius = settings['radius']

    def advance(self, targets, capsules, dt):
        points = self.positions
        substeps = max(2, round(dt * 240.))
        h = dt / substeps
        retention = (1. - self.damping) ** (h * 60.)
        for step in range(1, substeps + 1):
            anchor = [a.lerp(b, step / substeps) for a, b in zip(self.anchor, targets)]
            points[0] = anchor[0].copy()
            for i in range(1, len(points)):
                velocity = (points[i] - self.previous[i]) * retention
                self.previous[i] = points[i].copy()
                force = (anchor[i] - points[i]) * self.stiffness + self.gravity
                points[i] += velocity + force * (h * h)
            for _ in range(9):
                for i, length in enumerate(self.lengths):
                    delta = points[i + 1] - points[i]
                    if delta.length_squared < 1e-12:
                        continue
                    offset = delta * (1. - length / delta.length)
                    if i:
                        points[i] += .5 * offset
                        points[i + 1] -= .5 * offset
                    else:
                        points[i + 1] -= offset
                for start, end, radius in capsules:
                    limit = radius + self.radius
                    for i in range(1, len(points)):
                        points[i] += push_out(points[i], start, end, limit, anchor[i])
                    # Also test between the joints, where a long bone could otherwise pass through.
                    for i in range(1, len(points)):
                        for t in (.33, .67):
                            p = points[i - 1].lerp(points[i], t)
                            correction = push_out(p, start, end, limit, anchor[i])
                            a = 1. - t if i > 1 else 0.
                            total = a * a + t * t
                            if a:
                                points[i - 1] += correction * (a / total)
                            points[i] += correction * (t / total)
        self.anchor = [p.copy() for p in targets]
        return [p.copy() for p in points]
