import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proteus86 import Circuit, from_design, parse_design, route_file, mm
from proteus86.geometry import wiringcheck
from proteus86.inspection import netcheck
from proteus86._codec.net_objects import decode_net_objects
from proteus86.installation import ROOT
from proteus86.routing import Router, collinear_overlap


class ComplexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.output = Path(cls.directory.name)
        cls.cases = {}
        with patch('subprocess.Popen', side_effect=AssertionError('Complex file generation launched a GUI')):
            for name in ('mcu_complex', 'controller_complex'):
                text = (ROOT / 'proteus86/examples' / (name + '.txt')).read_text()
                c = from_design(text)
                path = c.save(cls.output / (name + '.pdsprj'))
                cls.cases[name] = (path, parse_design(text))

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_complex_topology_and_geometry_roundtrip_without_gui(self):
        for name, count in (('mcu_complex', 25), ('controller_complex', 42)):
            with self.subTest(name=name):
                path, design = self.cases[name]
                self.assertEqual(len(Circuit.open(path).components()), count)
                self.assertTrue(netcheck(path, design['nets'])['passed'])
                report = wiringcheck(path)
                self.assertTrue(report['passed'], report)
                self.assertTrue(all(2 <= len(node['wires']) <= 4 for node in decode_net_objects(path)['junctions']))

    def test_repeated_channels_remain_in_ordered_columns(self):
        c = Circuit.open(self.cases['controller_complex'][0])
        parts = {part['ref']: part['position'] for part in c.components()}
        for prefix, count in (('R', 8), ('D', 8), ('RL', 6), ('DL', 6)):
            positions = [parts[prefix + str(i)] for i in range(1, count + 1)]
            self.assertEqual(len({p['x'] for p in positions}), 1)
            self.assertEqual([p['y'] for p in positions], sorted([p['y'] for p in positions], reverse=True))

    def test_saved_complex_file_can_reroute_without_modifying_source_or_placement(self):
        source, design = self.cases['mcu_complex']
        digest = hashlib.sha256(source.read_bytes()).digest()
        before = Circuit.open(source).components()
        result = route_file(source, self.output / 'rerouted.pdsprj', design['nets'])
        self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), digest)
        self.assertEqual(Circuit.open(result).components(), before)
        self.assertTrue(netcheck(result, design['nets'])['passed'])
        self.assertTrue(wiringcheck(result)['passed'])

    def test_cosmetic_warning_does_not_reject_a_valid_saved_circuit(self):
        c = Circuit()
        with c.batch():
            c.add_mm('RESISTOR', 'R1', '1k', 0, 0)
            c.add_mm('RESISTOR', 'R2', '1k', 25.4, 0)
            c.update('R1', label_offsets={'reference': (mm(31.75), 0)})
        path = c.save(self.output / 'cosmetic_overlap.pdsprj')
        report = wiringcheck(path)
        self.assertTrue(report['passed'])
        self.assertTrue(any(item['kind'] == 'label_over_estimated_symbol' for item in report['warnings']))
        self.assertEqual(Circuit.open(path).nets(), c.nets())

    def test_route_cache_is_invalidated_when_routing_constraints_change(self):
        c = Circuit()
        with c.batch():
            c.add_mm('RESISTOR', 'R1', '1k', 0, 0)
            c.add_mm('CAPACITOR', 'C1', '1u', 25.4, 0)
            c.connect('R1.2', 'C1.2')
        source = c.save(self.output / 'cache_source.pdsprj')
        original = source.read_bytes()
        c.routing_options['obstacles'] = [[mm(12.7), mm(-1), mm(15.24), mm(1)]]
        destination = self.output / 'cache_invalid.pdsprj'
        with self.assertRaises(ValueError):
            c.save(destination)
        self.assertFalse(destination.exists())
        self.assertEqual(source.read_bytes(), original)

    def test_whole_translation_preserves_every_wire_and_net(self):
        source, _ = self.cases['mcu_complex']
        c = Circuit.open(source)
        before = decode_net_objects(source)
        nets = c.nets()
        c.translate_mm(10.16, -7.62)
        path = c.save(self.output / 'translated.pdsprj')
        after = decode_net_objects(path)
        def paths(items, dx=0, dy=0):
            result = []
            for wire in items['wires']:
                points = tuple((x + dx, y + dy) for x, y in wire['points'])
                result.append(min(points, points[::-1]))
            return sorted(result)
        self.assertEqual(paths(before, mm(10.16), mm(-7.62)), paths(after))
        self.assertEqual(Circuit.open(path).nets(), nets)

    def test_fitting_detects_and_repairs_off_sheet_diagram(self):
        c = Circuit()
        with c.batch():
            c.add_mm('RESISTOR', 'R1', '1k', 300, -200)
            c.add_mm('CAPACITOR', 'C1', '1u', 330, -200)
            c.connect('R1.2', 'C1.2')
        path = c.save(self.output / 'outside.pdsprj')
        self.assertFalse(wiringcheck(path)['passed'])
        original = path.read_bytes()
        c.fit_sheet()
        fixed = c.save(self.output / 'inside.pdsprj')
        self.assertTrue(wiringcheck(fixed)['passed'])
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(Circuit.open(path).nets(), Circuit.open(fixed).nets())

    def test_fitting_fresh_routes_preserves_requests_labels_and_skips_astar(self):
        c = Circuit()
        with c.batch():
            for i in range(3):
                c.add_mm('RESISTOR', 'R' + str(i + 1), '1k', 300 + i * 25.4, 0)
            c.add_terminal('power', 'TEMP', 'R1.1')
            c.add_terminal('input', 'UNUSED', position=(mm(300), mm(30)))
        c.delete_terminal('T1')
        with c.batch():
            c.connect_net('R1.2', 'R2.2', 'R3.2')
            c.add_terminal('power', 'VCC', 'R3.2')
            c.label_wire('R1.2', 'R2.2', 'BUS')
        original = c.save(self.output / 'fresh-fit-source.pdsprj')
        before = decode_net_objects(original)
        requests = [(x['first'], x['second']) for x in c.connections()]
        terminals = [(t['id'], t['pin']) for t in c.terminals()]
        with patch.object(Router, 'route', side_effect=AssertionError('Page fitting reran A*')):
            c.fit_sheet()
            fitted = c.save(self.output / 'fresh-fit-result.pdsprj')
        self.assertEqual(requests, [(x['first'], x['second']) for x in c.connections()])
        self.assertEqual(terminals, [(t['id'], t['pin']) for t in c.terminals()])
        self.assertTrue(netcheck(fitted, [['R1.2', 'R2.2', 'R3.2', 'VCC']])['passed'])
        after = decode_net_objects(fitted)
        self.assertEqual([label['text'] for wire in after['wires'] for label in wire['labels']], ['BUS'])
        dx, dy = c.sheet_report['translation']
        def paths(data, dx=0, dy=0):
            return sorted(min(tuple((x+dx,y+dy) for x,y in w['points']),
                              tuple((x+dx,y+dy) for x,y in w['points'][::-1])) for w in data['wires'])
        self.assertEqual(paths(before, dx, dy), paths(after))

    def test_adding_named_terminal_does_not_steal_existing_connection(self):
        c = Circuit()
        with c.batch():
            c.add_mm('RESISTOR', 'R1', '1k', 0, 0)
            c.add_mm('RESISTOR', 'R2', '1k', 50.8, 0)
            c.add_terminal('power', 'VCC', 'R1.1')
        source = c.save(self.output / 'one_port.pdsprj')
        target = route_file(source, self.output / 'two_ports.pdsprj', ['R2.1,VCC'])
        self.assertTrue(netcheck(target, [['R1.1', 'R2.1', 'VCC']])['passed'])
        self.assertEqual(len(Circuit.open(target).terminals()), 2)

    def test_future_pin_escape_is_not_consumed_by_an_earlier_wire(self):
        router = Router(lead=2)
        router.pin_segments[('UNUSED', '1')] = ((20, 0), (24, 0))
        path = router.route((0, 0), (40, 0), (1, 0), (-1, 0))
        self.assertFalse(any(collinear_overlap(a, b, (20, 0), (24, 0)) for a, b in zip(path, path[1:])))

    def test_search_edge_cache_does_not_ignore_newly_reserved_wires(self):
        router = Router(lead=2)
        first = router.route((0, 0), (40, 0), (1, 0), (-1, 0))
        router.reserve([(10, 0), (30, 0)])
        second = router.route((0, 0), (40, 0), (1, 0), (-1, 0))
        self.assertEqual(first, [(0, 0), (40, 0)])
        self.assertFalse(any(collinear_overlap(a, b, (10, 0), (30, 0)) for a, b in zip(second, second[1:])))

    def test_repeated_edit_save_reopen_preserves_complex_firmware_and_nets(self):
        source, design = self.cases['controller_complex']
        original = source.read_bytes()
        current = source
        for cycle in range(3):
            c = Circuit.open(current)
            with c.batch():
                c.update('RL1', value=str(680 + 10 * cycle))
                c.set_properties('U1', PROGRAM=r'firmware\blink8051.hex', CLOCK='12MHz')
            current = c.save(self.output / ('cycle-' + str(cycle) + '.pdsprj'))
            reopened = Circuit.open(current)
            parts = {p['ref']: p for p in reopened.components()}
            self.assertEqual(parts['U1']['properties']['PROGRAM'], r'firmware\blink8051.hex')
            self.assertEqual(parts['RL1']['value'], str(680 + 10 * cycle))
            self.assertTrue(netcheck(current, design['nets'])['passed'])
        self.assertEqual(source.read_bytes(), original)

    def test_tidy_complex_labels_preserves_all_device_and_wire_positions(self):
        source,design = self.cases['mcu_complex']
        c = Circuit.open(source)
        parts,nets = c.components(),c.nets()
        before = decode_net_objects(source)
        c.tidy_labels()
        self.assertTrue(any(item['ref']=='X1' for item in c.label_report['moved']))
        result=c.save(self.output/'tidy.pdsprj')
        after=decode_net_objects(result)
        self.assertEqual(Circuit.open(result).components(),parts)
        self.assertEqual(Circuit.open(result).nets(),nets)
        self.assertEqual(sorted(w['points'] for w in before['wires']),sorted(w['points'] for w in after['wires']))
        self.assertTrue(netcheck(result,design['nets'])['passed'])
        self.assertFalse(wiringcheck(result)['warnings'])

    def test_property_visibility_preserves_firmware_and_other_model_properties(self):
        c=Circuit.open(self.cases['mcu_complex'][0])
        with c.batch():
            c.set_properties('U1',PROGRAM=r'firmware\blink8051.hex',CLOCK='12MHz')
            c.set_property_visibility('U1',PROGRAM=False,CLOCK=False)
        p=c.save(self.output/'hidden-model.pdsprj')
        c=Circuit.open(p)
        part=c._parts[c._index('U1')]
        hidden=c._template(part)['properties']
        self.assertIn(r'{PROGRAM=firmware\blink8051.hex}',hidden)
        self.assertIn('{CLOCK=12MHz}',hidden)
        c.set_property_visibility('U1',PROGRAM=True)
        visible=c._template(c._parts[c._index('U1')])['properties']
        self.assertIn('\nPROGRAM=firmware\\blink8051.hex\n',visible)
        self.assertIn('{CLOCK=12MHz}',visible)
        self.assertEqual(next(p for p in c.components() if p['ref']=='U1')['properties']['PROGRAM'],r'firmware\blink8051.hex')
        before=c.components()
        with self.assertRaises(ValueError):
            c.set_property_visibility('U1',UNKNOWN_PROPERTY=False)
        self.assertEqual(before,c.components())

    def test_hidden_property_can_be_removed_before_saving(self):
        c=Circuit.open(self.cases['mcu_complex'][0])
        with c.batch():
            c.set_properties('U1',PROGRAM='blink.hex')
            c.set_property_visibility('U1',PROGRAM=False)
        c.set_properties('U1',PROGRAM=None)
        p=c.save(self.output/'removed-hidden.pdsprj')
        properties=next(p for p in Circuit.open(p).components() if p['ref']=='U1')['properties']
        self.assertNotIn('PROGRAM',properties)
