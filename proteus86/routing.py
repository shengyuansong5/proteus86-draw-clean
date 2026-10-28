"""Orthogonal A* routing on a compressed visibility grid. Standard library only."""
import heapq
import itertools
import struct
from bisect import bisect_left, bisect_right
from dataclasses import dataclass


class RoutingError(ValueError):
    pass


@dataclass(frozen=True)
class Rectangle:
    left: int
    bottom: int
    right: int
    top: int
    owner: str = ""

    def blocks(self, a, b):
        if a[1] == b[1]:
            return self.bottom < a[1] < self.top and max(min(a[0], b[0]), self.left) < min(max(a[0], b[0]), self.right)
        if a[0] == b[0]:
            return self.left < a[0] < self.right and max(min(a[1], b[1]), self.bottom) < min(max(a[1], b[1]), self.top)
        raise ValueError('Nonorthogonal routing segment')


def clean(points):
    result = []
    for point in map(tuple, points):
        if result and point == result[-1]:
            continue
        while len(result) > 1:
            a, b = result[-2:]
            if (a[0] == b[0] == point[0] and (b[1] - a[1]) * (point[1] - b[1]) > 0
                    or a[1] == b[1] == point[1] and (b[0] - a[0]) * (point[0] - b[0]) > 0):
                result.pop()
            else:
                break
        result.append(point)
    return result


def collinear_overlap(a, b, c, d):
    horizontal = a[1] == b[1] == c[1] == d[1] and max(min(a[0], b[0]), min(c[0], d[0])) < min(max(a[0], b[0]), max(c[0], d[0]))
    vertical = a[0] == b[0] == c[0] == d[0] and max(min(a[1], b[1]), min(c[1], d[1])) < min(max(a[1], b[1]), max(c[1], d[1]))
    return horizontal or vertical


def _interval_index(intervals):
    """Merge occupied intervals; keep strict edge-touch behavior for queries."""
    starts, ends = [], []
    for low, high in sorted(intervals):
        if low >= high:
            continue
        if ends and low <= ends[-1]:
            ends[-1] = max(ends[-1], high)
        else:
            starts.append(low)
            ends.append(high)
    return starts, ends


def _intersects(index, low, high):
    if index is None or low >= high:
        return False
    starts, ends = index
    position = bisect_right(ends, low)
    return position < len(starts) and starts[position] < high


class Router:
    def __init__(self, rectangles=(), *, lead=254000, bend_penalty=254000, max_nodes=500000):
        if type(lead) is not int or lead <= 0:
            raise ValueError('Routing lead must be a positive native integer')
        if type(bend_penalty) is not int or bend_penalty < 0:
            raise ValueError('Routing bend penalty must be a nonnegative native integer')
        if type(max_nodes) is not int or max_nodes <= 0:
            raise ValueError('Routing search limit must be a positive integer')
        self.rectangles = list(rectangles)
        self.lead = lead
        self.bend_penalty = bend_penalty
        self.max_nodes = max_nodes
        self.segments = []
        self.pin_segments = {}
        self._horizontal_rects, self._vertical_rects = {}, {}

    @classmethod
    def from_parts(cls, parts, templates, options):
        clearance = options.get('clearance', 127000)
        if type(clearance) is not int or clearance < 0:
            raise ValueError('Routing clearance must be a nonnegative native integer')
        rectangles = []
        for part in parts:
            template = part.get('template') or templates[part['device']]
            bounds = template.get('body_bounds')
            if bounds:
                left, bottom, right, top = bounds
                if left == right:
                    left -= 127000; right += 127000
                if bottom == top:
                    bottom -= 127000; top += 127000
                rectangles.append(Rectangle(part['x'] + left - clearance, part['y'] + bottom - clearance,
                                            part['x'] + right + clearance, part['y'] + top + clearance, part['ref']))
            if options.get('avoid_labels', False) and 'text_tails' in template:
                for index, text in enumerate((part['ref'], part['value'])):
                    x, y = struct.unpack_from('<ii', template['text_tails'][index])
                    x += part['x'] - template['x']; y += part['y'] - template['y']
                    width = max(254000, len(text) * (170000 if index == 0 else 140000))
                    rectangles.append(Rectangle(x - 63500, y - 63500, x + width + 63500, y + 320000, part['ref'] + ':text'))
            if options.get('avoid_labels', False):
                for text, position in template.get('terminal_labels', []):
                    x, y = position
                    width = max(127000, len(text) * 140000)
                    rectangles.append(Rectangle(part['x'] + x - 63500, part['y'] + y - 63500,
                                                part['x'] + x + width + 63500, part['y'] + y + 320000,
                                                part['ref'] + ':text'))
        for bounds in options.get('obstacles', []):
            if len(bounds) != 4 or any(type(v) is not int for v in bounds) or not bounds[0] < bounds[2] or not bounds[1] < bounds[3]:
                raise ValueError('Routing obstacles must be [left,bottom,right,top] native rectangles')
            rectangles.append(Rectangle(*bounds))
        router = cls(rectangles, lead=options.get('lead', 254000),
                     bend_penalty=options.get('bend_penalty', 254000), max_nodes=options.get('max_nodes', 500000))
        for part in parts:
            template = part.get('template') or templates[part['device']]
            for name, offset in template['pin_offsets'].items():
                a = (part['x'] + offset[0], part['y'] + offset[1])
                b = tuple(a[i] + template['pin_directions'][name][i] * router.lead for i in (0, 1))
                router.pin_segments[(part['ref'], name)] = (a, b)
        return router

    def reserve(self, points):
        self.segments.extend((tuple(a), tuple(b)) for a, b in zip(points, points[1:]))

    def _prepare(self, allowed):
        # Obstacles and reserved wires are fixed during one search. Both A*
        # directions can ask about the same undirected edge many times.
        self._edge_blocked = {}
        rectangles = tuple(self.rectangles)
        if rectangles != getattr(self, '_rectangles_snapshot', None):
            self._horizontal_rects.clear()
            self._vertical_rects.clear()
            self._rectangles_snapshot = rectangles
        self._horizontal_wires, self._vertical_wires = {}, {}
        self._horizontal_pins, self._vertical_pins = {}, {}
        for mapping_h, mapping_v, segments in (
                (self._horizontal_wires, self._vertical_wires, self.segments),
                (self._horizontal_pins, self._vertical_pins, [segment for key, segment in self.pin_segments.items() if key not in allowed])):
            for a, b in segments:
                if a[1] == b[1]:
                    mapping_h.setdefault(a[1], []).append((min(a[0], b[0]), max(a[0], b[0])))
                else:
                    mapping_v.setdefault(a[0], []).append((min(a[1], b[1]), max(a[1], b[1])))
        self._wire_ys, self._wire_xs = sorted(self._horizontal_wires), sorted(self._vertical_wires)
        self._pin_ys, self._pin_xs = sorted(self._horizontal_pins), sorted(self._vertical_pins)
        self._horizontal_blockers = {key: _interval_index(self._horizontal_wires.get(key, []) + self._horizontal_pins.get(key, []))
                                     for key in self._horizontal_wires.keys() | self._horizontal_pins.keys()}
        self._vertical_blockers = {key: _interval_index(self._vertical_wires.get(key, []) + self._vertical_pins.get(key, []))
                                   for key in self._vertical_wires.keys() | self._vertical_pins.keys()}

    @staticmethod
    def _crosses(mapping, coordinates, low, high, perpendicular):
        if not coordinates:
            return 0
        return sum(1 for coordinate in coordinates[bisect_left(coordinates, low):bisect_right(coordinates, high)]
                   for first, last in mapping[coordinate] if first < perpendicular < last)

    @staticmethod
    def _has_crossing(mapping, coordinates, low, high, perpendicular):
        for i in range(bisect_left(coordinates, low), bisect_right(coordinates, high)):
            for first, last in mapping[coordinates[i]]:
                if first < perpendicular < last:
                    return True
        return False

    def _blocked(self, a, b):
        key = (a, b) if a <= b else (b, a)
        if key not in self._edge_blocked:
            self._edge_blocked[key] = self._blocked_uncached(a, b)
        return self._edge_blocked[key]

    def _blocked_uncached(self, a, b):
        horizontal = a[1] == b[1]
        constant, first, last = (a[1], min(a[0], b[0]), max(a[0], b[0])) if horizontal else (a[0], min(a[1], b[1]), max(a[1], b[1]))
        cache = self._horizontal_rects if horizontal else self._vertical_rects
        if constant not in cache:
            cache[constant] = _interval_index((rect.left, rect.right) if horizontal else (rect.bottom, rect.top)
                                              for rect in self.rectangles
                                              if (rect.bottom < constant < rect.top if horizontal else rect.left < constant < rect.right))
        if _intersects(cache[constant], first, last):
            return True
        blockers = self._horizontal_blockers if horizontal else self._vertical_blockers
        if _intersects(blockers.get(constant), first, last):
            return True
        # Other pins need an escape corridor even before their nets are routed.
        cross_pins, coordinates = (self._vertical_pins, self._pin_xs) if horizontal else (self._horizontal_pins, self._pin_ys)
        return self._has_crossing(cross_pins, coordinates, first, last, constant)

    def _direct_path(self, a, b, start, end, first_direction, second_direction):
        """Accept only clear Manhattan paths with a provably minimal bend cost.

        Crossing penalties, pin escape corridors and forced leads still apply.
        Congested paths and candidates needing extra bends use the full search.
        """
        candidates = ([start, end],) if start[0] == end[0] or start[1] == end[1] else (
            [start, (end[0], start[1]), end], [start, (start[0], end[1]), end])
        forced = [(a, start)] + ([(end, b)] if second_direction else [])
        for candidate in candidates:
            middle = clean(candidate)
            if len(middle) > 1:
                if sum((middle[1][i] - start[i]) * first_direction[i] for i in (0, 1)) < 0:
                    continue
                if second_direction and sum((middle[-2][i] - end[i]) * second_direction[i] for i in (0, 1)) < 0:
                    continue
            axis = 0 if first_direction[0] else 1
            bends, valid = 0, True
            for c, d in zip(middle, middle[1:]):
                new_axis = 0 if c[1] == d[1] else 1
                bends += new_axis != axis
                axis = new_axis
                # At most one bend attains the unobstructed lower bound. A
                # two-bend elbow could lose to another route when penalized.
                if bends > 1 or self._blocked(c, d) or any(collinear_overlap(c, d, p, q) for p, q in forced):
                    valid = False
                    break
                if any(pin not in (start, end) and
                       (c[1] == d[1] == pin[1] and min(c[0], d[0]) <= pin[0] <= max(c[0], d[0]) or
                        c[0] == d[0] == pin[0] and min(c[1], d[1]) <= pin[1] <= max(c[1], d[1]))
                       for pin in (a, b)):
                    valid = False
                    break
                mapping, coordinates = ((self._vertical_wires, self._wire_xs) if new_axis == 0 else
                                        (self._horizontal_wires, self._wire_ys))
                low, high = sorted((c[new_axis], d[new_axis]))
                if self._crosses(mapping, coordinates, low, high, c[1 - new_axis]):
                    valid = False
                    break
            if valid:
                result = clean([a] + middle + [b])
                if len(set(result)) == len(result):
                    return result
        return None

    def check_escapes(self, endpoints):
        """Reject an already blocked fresh net before routing other nets.

        Adding more reserved wires cannot clear a blocked body or pin corridor.
        The encoder calls this only for nets without retained/manual geometry.
        """
        self._prepare({endpoint['key'] for endpoint in endpoints})
        for endpoint in endpoints:
            tip = endpoint['location']
            lead = tuple(tip[i] + endpoint['direction'][i] * self.lead for i in (0, 1))
            if self._blocked(tip, lead):
                raise RoutingError(f"{endpoint['key']}: Pin escape is obstructed; adjust placement or routing clearance")

    def route(self, a, b, first_direction, second_direction=None, *, endpoint_keys=()):
        self._prepare(set(endpoint_keys))
        a, b = tuple(a), tuple(b)
        start = tuple(a[i] + first_direction[i] * self.lead for i in (0, 1))
        end = tuple(b[i] + second_direction[i] * self.lead for i in (0, 1)) if second_direction else b
        if a == b or self._blocked(a, start) or second_direction and self._blocked(end, b):
            raise RoutingError('Pin escape is obstructed; adjust placement or routing clearance')
        xs, ys = {a[0], b[0], start[0], end[0]}, {a[1], b[1], start[1], end[1]}
        for rect in self.rectangles:
            xs.update((rect.left, rect.right)); ys.update((rect.bottom, rect.top))
        for c, d in self.segments:
            xs.update((c[0], d[0], c[0] - self.lead, c[0] + self.lead, d[0] - self.lead, d[0] + self.lead))
            ys.update((c[1], d[1], c[1] - self.lead, c[1] + self.lead, d[1] - self.lead, d[1] + self.lead))
        for c, d in self.pin_segments.values():
            xs.update((c[0], d[0])); ys.update((c[1], d[1]))
        xs.update((min(xs) - self.lead * 2, max(xs) + self.lead * 2))
        ys.update((min(ys) - self.lead * 2, max(ys) + self.lead * 2))
        xs, ys = sorted(xs), sorted(ys)
        if len(xs) * len(ys) * 3 > self.max_nodes:
            raise RoutingError('Routing visibility grid is too large; split the circuit or raise max_nodes')
        direct = self._direct_path(a, b, start, end, first_direction, second_direction)
        if direct is not None:
            return direct
        source = (xs.index(start[0]), ys.index(start[1]), 0 if first_direction[0] else 1)
        target = (xs.index(end[0]), ys.index(end[1]))
        queue, costs, parents, serial = [], {source: 0}, {}, itertools.count()
        def remaining(point, axis):
            dx, dy = abs(point[0] - end[0]), abs(point[1] - end[1])
            # Every remaining axis change must pay at least one bend. This
            # lower bound ignores obstacles and the final forced lead, so it
            # cannot overestimate; it is consistent across neighboring edges.
            turn = bool(dx and dy or dx and axis != 0 or dy and axis != 1)
            return dx + dy + turn * self.bend_penalty
        initial = remaining(start, source[2])
        heapq.heappush(queue, (initial, initial, next(serial), source))
        found = None
        closed = set()
        neighbors = {}
        forced = [(a, start)] + ([(end, b)] if second_direction else [])
        while queue:
            _, _, _, node = heapq.heappop(queue)
            if node in closed:
                continue
            closed.add(node)
            ix, iy, axis = node
            if (ix, iy) == target:
                found = node; break
            point = (xs[ix], ys[iy])
            if (ix, iy) not in neighbors:
                edges = []
                for nx, ny, new_axis in ((ix - 1, iy, 0), (ix + 1, iy, 0), (ix, iy - 1, 1), (ix, iy + 1, 1)):
                    if not 0 <= nx < len(xs) or not 0 <= ny < len(ys):
                        continue
                    following = (xs[nx], ys[ny])
                    if self._blocked(point, following):
                        continue
                    if following in (a, b) and following not in (start, end):
                        continue
                    if any(collinear_overlap(point, following, c, d) for c, d in forced):
                        continue
                    if (nx, ny) == target and second_direction and sum((point[i] - following[i]) * second_direction[i] for i in (0, 1)) < 0:
                        continue
                    crossings = (self._crosses(self._horizontal_wires, self._wire_ys, min(point[1], following[1]), max(point[1], following[1]), point[0])
                                 if new_axis == 1 else self._crosses(self._vertical_wires, self._wire_xs, min(point[0], following[0]), max(point[0], following[0]), point[1]))
                    distance = abs(following[0] - point[0]) + abs(following[1] - point[1])
                    edges.append((nx, ny, new_axis, following, distance + crossings * self.lead * 4))
                neighbors[(ix, iy)] = edges
            for nx, ny, new_axis, following, edge_cost in neighbors[(ix, iy)]:
                # The forced pin lead must not immediately reverse direction.
                if node == source and sum((following[i] - point[i]) * first_direction[i] for i in (0, 1)) < 0:
                    continue
                cost = costs[node] + edge_cost + (self.bend_penalty if new_axis != axis else 0)
                neighbor = (nx, ny, new_axis)
                if cost < costs.get(neighbor, float('inf')):
                    costs[neighbor], parents[neighbor] = cost, node
                    heuristic = remaining(following, new_axis)
                    # Equal-cost states nearer the goal avoid exploring a
                    # whole flat Manhattan frontier before taking a clear exit.
                    heapq.heappush(queue, (cost + heuristic, heuristic, next(serial), neighbor))
        if found is None:
            raise RoutingError('No orthogonal route avoids the component bodies and reserved wires')
        path, current = [], found
        while True:
            path.append((xs[current[0]], ys[current[1]]))
            if current == source:
                break
            current = parents[current]
        result = clean([a] + list(reversed(path)) + [b])
        if len(set(result)) != len(result):
            raise RoutingError('Route contains a loop')
        return result

    def route_net(self, endpoints):
        """Connect arbitrary pin exits through a bounded-degree native bus tree."""
        original = list(self.segments)
        keys = [endpoint['key'] for endpoint in endpoints]
        points = [endpoint['location'] for endpoint in endpoints]
        left = min([point[0] for point in points] + [r.left for r in self.rectangles]) - self.lead * 3
        right = max([point[0] for point in points] + [r.right for r in self.rectangles]) + self.lead * 3
        bottom = min([point[1] for point in points] + [r.bottom for r in self.rectangles]) - self.lead * 3
        top = max([point[1] for point in points] + [r.top for r in self.rectangles]) + self.lead * 3
        failures = []
        # Short terminal branches commonly meet at their forced pin leads.
        # Prefer that real junction before constructing a more distant bus.
        if len(endpoints) <= 4:
            leads = [tuple(endpoint['location'][i] + endpoint['direction'][i] * self.lead for i in (0, 1)) for endpoint in endpoints]
            candidates = sorted(set(leads), key=lambda point: (-leads.count(point), sum(abs(point[i] - p[i]) for p in points for i in (0, 1))))
            candidates.append(tuple(sorted(p[i] for p in points)[len(points) // 2] for i in (0, 1)))
            for junction in candidates:
                if junction in points:
                    continue
                self.segments = list(original)
                paths = {}
                try:
                    for endpoint in endpoints:
                        path = self.route(endpoint['location'], junction, endpoint['direction'], endpoint_keys=keys)
                        paths[endpoint['key']] = path
                        self.reserve(path)
                    return {'junctions': [junction], 'paths': paths, 'links': [], 'labels': {}}
                except RoutingError as error:
                    failures.append(str(error))
        for axis, line, normal in ((0, bottom, (0, 1)), (0, top, (0, -1)), (1, left, (1, 0)), (1, right, (-1, 0))):
            self.segments = list(original)
            ordered = sorted(endpoints, key=lambda endpoint: (endpoint['location'][axis], endpoint['key']))
            positions, by_key, previous = [], {}, None
            for endpoint in ordered:
                coordinate = endpoint['location'][axis]
                if previous is not None:
                    coordinate = max(coordinate, previous + self.lead)
                point = (coordinate, line) if axis == 0 else (line, coordinate)
                positions.append(point); by_key[endpoint['key']] = point; previous = coordinate
            links = [{'first': a, 'second': b, 'points': [a, b]} for a, b in zip(positions, positions[1:])]
            for link in links:
                self.reserve(link['points'])
            paths = {}
            try:
                for endpoint in ordered:
                    path = self.route(endpoint['location'], by_key[endpoint['key']], endpoint['direction'], normal, endpoint_keys=keys)
                    paths[endpoint['key']] = path
                    self.reserve(path)
                return {'junctions': positions, 'paths': paths, 'links': links, 'labels': {}}
            except RoutingError as error:
                failures.append(str(error))
        self.segments = original
        raise RoutingError('No bus tree fits the placement: ' + '; '.join(failures))
