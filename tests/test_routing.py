import tempfile
import unittest
from pathlib import Path

from proteus86 import Circuit, mm
from proteus86.routing import Rectangle, Router, RoutingError, collinear_overlap
from proteus86._codec.net_objects import decode_net_objects


class RoutingTests(unittest.TestCase):
    def test_reversed_manual_endpoints_encode_native_order_for_connect_and_set_route(self):
        # Proteus reattaches the end coordinates in component/pin table order
        # on save. The whole path must follow that order, even if the caller
        # supplies the later component first. The decoder alone accepts either
        # orientation, so checking only logical connectivity missed this bug.
        with tempfile.TemporaryDirectory() as directory:
            for method in ('connect', 'set_route'):
                for reverse in (False, True):
                    with self.subTest(method=method, reverse=reverse):
                        c = Circuit()
                        with c.batch():
                            c.add_mm('RESISTOR', 'R1', '1k', 0, 0)
                            c.add_mm('RESISTOR', 'R2', '2k', 50.8, 12.7)
                        first, second = ('R1', '2'), ('R2', '1')
                        a = next(p['position'] for p in c.pins('R1') if p['name'] == '2')
                        b = next(p['position'] for p in c.pins('R2') if p['name'] == '1')
                        canonical = [a, (mm(31.75), a[1]), (mm(31.75), b[1]), b]
                        if method == 'set_route':
                            c.connect(first, second)
                        endpoints, points = (second, first), canonical[::-1] if reverse else canonical
                        if not reverse:
                            endpoints = first, second
                        getattr(c, method)(*endpoints, points=points)
                        path = c.save(Path(directory) / f'{method}-{reverse}.pdsprj')
                        wire = decode_net_objects(path)['wires'][0]
                        self.assertEqual(wire['points'], canonical)
                        expected = c.nets()
                        opened = Circuit.open(path)
                        self.assertEqual(opened.nets(), expected)
                        copy = opened.save(Path(directory) / f'{method}-{reverse}-retained.pdsprj')
                        self.assertEqual(decode_net_objects(copy)['wires'][0]['points'], canonical)

    def test_automatic_route_called_in_reverse_uses_native_coordinate_order(self):
        c = Circuit()
        with c.batch():
            c.add_mm('RESISTOR', 'R1', '1k', 0, 0)
            c.add_mm('RESISTOR', 'R2', '2k', 50.8, 12.7)
            c.connect('R2.1', 'R1.2')
        with tempfile.TemporaryDirectory() as directory:
            path = c.save(Path(directory) / 'reverse-auto.pdsprj')
            points = decode_net_objects(path)['wires'][0]['points']
            self.assertEqual(points[0], next(p['position'] for p in c.pins('R1') if p['name']=='2'))
            self.assertEqual(points[-1], next(p['position'] for p in c.pins('R2') if p['name']=='1'))

    def test_astar_avoids_rectangular_obstacle_and_keeps_pin_exits(self):
        blocker = Rectangle(10, -10, 30, 10)
        path = Router([blocker], lead=2, bend_penalty=2).route((0, 0), (40, 0), (1, 0), (-1, 0))
        self.assertEqual(path[0], (0, 0)); self.assertEqual(path[-1], (40, 0))
        self.assertGreater(path[1][0], 0); self.assertLess(path[-2][0], 40)
        self.assertFalse(any(blocker.blocks(a, b) for a, b in zip(path, path[1:])))
        self.assertTrue(any(abs(y) >= 10 for x, y in path))

    def test_blocked_escape_is_rejected(self):
        with self.assertRaises(RoutingError):
            Router([Rectangle(0, -10, 10, 10)], lead=2).route((0, 0), (40, 0), (1, 0), (-1, 0))

    def test_native_route_really_goes_around_an_unconnected_component(self):
        c = Circuit()
        with c.batch():
            c.add_mm('RESISTOR', 'R1', '1k', 0, 0)
            c.add_mm('RESISTOR', 'R2', '2k', 50.8, 0)
            c.add_mm('CAPACITOR', 'C_BLOCK1', '100n', 25.4, 5.08)
            c.connect('R1.2', 'R2.1')
        with tempfile.TemporaryDirectory() as directory:
            path = c.save(Path(directory) / 'obstacle.pdsprj')
            decoded = decode_net_objects(path)
            box = Rectangle(mm(22.86), mm(-3.81), mm(27.94), mm(3.81))
            self.assertFalse(any(box.blocks(a, b) for wire in decoded['wires'] for a, b in zip(wire['points'], wire['points'][1:])))

    def test_eight_pin_buses_roundtrip_and_use_bounded_degree_junctions(self):
        c = Circuit()
        with c.batch():
            for i in range(8):
                c.add_mm('CAPACITOR', 'C' + str(i + 1), '1u', i * 25.4, 0)
            for pin in ('1', '2'):
                c.connect_net(*['C' + str(i) + '.' + pin for i in range(1, 9)])
        with tempfile.TemporaryDirectory() as directory:
            path = c.save(Path(directory) / 'buses.pdsprj')
            decoded = decode_net_objects(path)
            self.assertEqual([len(net) for net in Circuit.open(path).nets()], [8, 8])
            self.assertTrue(all(2 <= len(node['wires']) <= 4 for node in decoded['junctions']))
            paths = [wire['points'] for wire in decoded['wires']]
            self.assertFalse(any(collinear_overlap(a, b, c, d) for i, p in enumerate(paths)
                                 for q in paths[:i] for a, b in zip(p, p[1:]) for c, d in zip(q, q[1:])))

    def test_failed_batch_restores_every_component_and_connection(self):
        c = Circuit()
        c.add_mm('RESISTOR', 'R1', '1k', 0, 0)
        before = c.summary()
        with self.assertRaises(ValueError):
            with c.batch():
                c.add_mm('CAPACITOR', 'C1', '100n', 25.4, 0)
                c.connect('R1.2', 'C1.999')
        self.assertEqual(before, c.summary())
        self.assertEqual(c._batch_depth, 0)

    def test_named_net_and_true_wire_label_survive_save_and_edit(self):
        c = Circuit()
        with c.batch():
            c.add_mm('RESISTOR', 'R1', '1k', 0, 0)
            c.add_mm('CAPACITOR', 'C1', '1u', 25.4, 0)
            c.connect('R1.2', 'C1.2')
            c.label_wire('R1.2', 'C1.2', 'SENSE')
        with tempfile.TemporaryDirectory() as directory:
            path = c.save(Path(directory) / 'label.pdsprj')
            decoded = decode_net_objects(path)
            self.assertEqual(sum(len(w['labels']) for w in decoded['wires']), 1)
            edited = Circuit.open(path)
            edited.rename('R1', 'R_INPUT1')
            edited.move_mm('C1', 38.1, 0)
            again = edited.save(Path(directory) / 'label_edited.pdsprj')
            self.assertEqual(sum(len(w['labels']) for w in decode_net_objects(again)['wires']), 1)

    def test_rerouting_a_saved_junction_preserves_branch_and_bridge_labels(self):
        c = Circuit()
        with c.batch():
            for i in range(8):
                c.add_mm('CAPACITOR', f'C{i + 1}', '1u', i * 25.4, 0)
            c.connect_net(*[f'C{i}.1' for i in range(1, 9)])
            c.label_wire('C1.1', 'C2.1', 'BRANCH')
        with tempfile.TemporaryDirectory() as directory:
            source = c.save(Path(directory) / 'labelled.pdsprj')
            saved = Circuit.open(source)
            for connection in saved._connections:
                if connection.get('layout'):
                    connection['layout']['links'][0]['labels'] = [
                        {'text': 'BRIDGE', 'auto_position': True, 'position': (0, 0)}]
            source = saved.save(Path(directory) / 'bridge_label.pdsprj')
            edited = Circuit.open(source)
            edited.autoroute()
            again = edited.save(Path(directory) / 'rerouted.pdsprj')
            labels = [label['text'] for wire in decode_net_objects(again)['wires'] for label in wire['labels']]
            self.assertCountEqual(labels, ['BRANCH', 'BRIDGE'])
            self.assertEqual(Circuit.open(source).nets(), Circuit.open(again).nets())

    def test_new_wire_avoids_retained_junction_even_when_encoded_first(self):
        c = Circuit()
        with c.batch():
            c.add_mm('RESISTOR', 'R1', '1k', -25.4, -12.7)
            c.add_mm('RESISTOR', 'R2', '1k', 101.6, -12.7)
            for i in range(4):
                c.add_mm('CAPACITOR', f'C{i + 1}', '1u', i * 25.4, 0)
            c.connect_net(*[f'C{i}.1' for i in range(1, 5)])
        with tempfile.TemporaryDirectory() as directory:
            source = c.save(Path(directory) / 'existing_bus.pdsprj')
            edited = Circuit.open(source)
            edited.connect('R1.2', 'R2.1')
            result = edited.save(Path(directory) / 'new_wire.pdsprj')
            paths = [wire['points'] for wire in decode_net_objects(result)['wires']]
            self.assertFalse(any(collinear_overlap(a, b, c, d) for i, p in enumerate(paths)
                                 for q in paths[:i] for a, b in zip(p, p[1:]) for c, d in zip(q, q[1:])))
