"""Correctness boundaries of faster routing and network partitioning."""
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proteus86 import Circuit
from proteus86._codec.component_codec import Circuit as CodecCircuit
from proteus86.inspection import netcheck
from proteus86.routing import Router, Rectangle, RoutingError, collinear_overlap


class FastRoutingTests(unittest.TestCase):
    def test_late_blocked_escape_fails_before_any_other_net_search(self):
        c = Circuit()
        with patch('proteus86.routing.heapq.heappush', side_effect=AssertionError('Routed before preflight')):
            with self.assertRaisesRegex(RoutingError, 'R3.*escape is obstructed'):
                with c.batch():
                    for ref, x, y in [('R1', 0, 0), ('R2', 50.8, 0), ('R3', 0, 60), ('R4', 50.8, 60)]:
                        c.add_mm('RESISTOR', ref, '1k', x, y)
                    c.add_mm('CAPACITOR', 'C_BLOCK1', '100n', 25.4, 5.08)
                    c.connect('R1.2', 'R2.1');c.connect('R3.2', 'R4.1')
                    pin = next(p for p in c.pins('R3') if p['name'] == '2')
                    x, y = [pin['position'][i] + pin['direction'][i] * 127000 for i in (0, 1)]
                    c.routing_options['obstacles'] = [[x - 63500, y - 63500, x + 63500, y + 63500]]
        self.assertEqual(c.components(), [])

    def test_clear_straight_and_elbow_channels_do_not_need_heap_search(self):
        with patch('proteus86.routing.heapq.heappush', side_effect=AssertionError('Unneeded heap search')):
            straight = Router(lead=2).route((0, 0), (40, 0), (1, 0), (-1, 0))
            elbow = Router(lead=2).route((0, 0), (30, 20), (1, 0), (0, -1))
        self.assertEqual(straight, [(0, 0), (40, 0)])
        self.assertEqual(elbow, [(0, 0), (30, 0), (30, 20)])

    def test_fast_channel_still_obeys_visibility_budget(self):
        with self.assertRaisesRegex(RoutingError, 'grid is too large'):
            Router(lead=2, max_nodes=1).route((0, 0), (40, 0), (1, 0), (-1, 0))

    def test_crossing_penalty_keeps_short_detour_available(self):
        router = Router(lead=2, bend_penalty=1)
        router.reserve([(20, -2), (20, 2)])
        path = router.route((0, 0), (40, 0), (1, 0), (-1, 0))
        self.assertTrue(any(abs(y) >= 2 for x, y in path))
        self.assertFalse(any(a[1] == b[1] and min(a[0], b[0]) <= 20 <= max(a[0], b[0]) and -2 < a[1] < 2
                             for a, b in zip(path, path[1:])))

    def test_other_pin_escape_cannot_be_crossed_by_fast_path(self):
        router = Router(lead=2)
        router.pin_segments[('OTHER', '1')] = ((20, -5), (20, 5))
        path = router.route((0, 0), (40, 0), (1, 0), (-1, 0))
        self.assertFalse(any(a[1] == b[1] and min(a[0], b[0]) <= 20 <= max(a[0], b[0]) and -5 < a[1] < 5
                             for a, b in zip(path, path[1:])))

    def test_reservations_and_allowed_pins_refresh_between_searches(self):
        router = Router(lead=2)
        keys = (('A', '1'), ('B', '1'))
        router.pin_segments.update({keys[0]: ((0, 0), (2, 0)), keys[1]: ((40, 0), (38, 0))})
        self.assertEqual(router.route((0, 0), (40, 0), (1, 0), (-1, 0), endpoint_keys=keys), [(0, 0), (40, 0)])
        with self.assertRaisesRegex(RoutingError, 'escape is obstructed'):
            router.route((0, 0), (40, 0), (1, 0), (-1, 0))
        router.reserve([(10, 0), (30, 0)])
        path = router.route((0, 0), (40, 0), (1, 0), (-1, 0), endpoint_keys=keys)
        self.assertFalse(any(collinear_overlap(a, b, (10, 0), (30, 0)) for a, b in zip(path, path[1:])))

    def test_changed_obstacles_invalidate_interval_indices(self):
        router = Router(lead=2)
        router.route((0, 0), (40, 0), (1, 0), (-1, 0))
        blocker = Rectangle(10, -4, 30, 4)
        router.rectangles.append(blocker)
        path = router.route((0, 0), (40, 0), (1, 0), (-1, 0))
        self.assertFalse(any(blocker.blocks(a, b) for a, b in zip(path, path[1:])))

    def test_indexed_edges_match_literal_obstacles_wires_and_pin_corridors(self):
        rng = random.Random(86)
        rectangles = [Rectangle(x, y, x + rng.randint(1, 5), y + rng.randint(1, 5))
                      for x, y in [(rng.randint(-8, 8), rng.randint(-8, 8)) for _ in range(24)]]
        router = Router(rectangles, lead=2)
        router.reserve([(-8, 3), (8, 3)])
        router.pin_segments = {('P', '1'): ((-2, -7), (-2, 7)), ('P', '2'): ((-6, -1), (6, -1))}
        router._prepare(set())
        for _ in range(400):
            first, last = sorted(rng.sample(range(-10, 11), 2));constant = rng.randint(-10, 10)
            for a, b in (((first, constant), (last, constant)), ((constant, first), (constant, last))):
                blocked = any(r.blocks(a, b) for r in rectangles)
                blocked |= any(collinear_overlap(a, b, c, d) for c, d in router.segments + list(router.pin_segments.values()))
                for c, d in router.pin_segments.values():
                    if a[1] == b[1] and c[0] == d[0]:
                        blocked |= min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and min(c[1], d[1]) < a[1] < max(c[1], d[1])
                    elif a[0] == b[0] and c[1] == d[1]:
                        blocked |= min(a[1], b[1]) <= c[1] <= max(a[1], b[1]) and min(c[0], d[0]) < a[0] < max(c[0], d[0])
                self.assertEqual(router._blocked(a, b), bool(blocked), (a, b))


class FastConnectivityTests(unittest.TestCase):
    def test_union_find_matches_codec_partition_and_order_including_named_branches(self):
        c = Circuit()
        with c.batch():
            for i in range(12):
                c.add_mm('CAPACITOR', f'C{i}', '1u', i * 25.4, 0)
        pins = [(f'C{i}', pin) for i in range(12) for pin in ('1', '2')]
        rng = random.Random(814)
        # These are valid endpoint graphs before routing. The old codec is an
        # independent oracle for both logical and physical group ordering.
        for _ in range(40):
            c._connections = [dict(first=a, second=b, points=None,
                                   labels=[{'text': f'N{j % 3}'}] if j % 4 == 0 else [])
                              for j, (a, b) in enumerate(rng.sample([(a, b) for a in pins for b in pins if a != b], 20))]
            c._connections[0]['layout'] = {'labels': {pins[0]: [{'text': 'BRANCH'}]},
                                           'links': [{'labels': [{'text': 'BRIDGE'}]}]}
            c._terminals = [dict(kind='ground', name='', pin=pins[0]),
                            dict(kind='ground', name='', pin=pins[-1]),
                            dict(kind='label', name='BRANCH', pin=pins[5]),
                            dict(kind='label', name='BRIDGE', pin=pins[9])]
            for physical in (True, False):
                self.assertEqual(c.nets(physical=physical), CodecCircuit.nets(c, physical=physical))

    def test_connect_net_joins_existing_groups_once_and_recomputes_after_disconnect(self):
        c = Circuit()
        with c.batch():
            for i in range(1, 5):
                c.add_mm('CAPACITOR', f'C{i}', '1u', (i - 1) * 25.4, 0)
            c.connect('C1.1', 'C2.1');c.connect('C3.1', 'C4.1')
        before = len(c.connections())
        c.connect_net('C1.1', 'C3.1', 'C4.1')
        self.assertEqual(len(c.connections()), before + 1)
        expected = [(f'C{i}', '1') for i in range(1, 5)]
        with tempfile.TemporaryDirectory() as directory:
            path = c.save(Path(directory) / 'joined.pdsprj')
            self.assertTrue(netcheck(path, [expected])['passed'])
            self.assertEqual(Circuit.open(path).nets(), c.nets())
        c.disconnect('C1.1', 'C3.1')
        self.assertEqual(sorted(len(g) for g in c.nets(physical=True) if len(g) > 1), [2, 2])


if __name__ == '__main__':
    unittest.main()
