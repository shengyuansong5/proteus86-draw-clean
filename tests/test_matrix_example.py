"""Independent matrix/display example checks; these do not execute firmware."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from examples.draw_matrix_display import DIGIT_PROBES, KEYS, SEGMENT_PROBES, expected_nets, generate
from proteus86 import Circuit, firmware_info, prepare_run
from proteus86.inspection import netcheck
from proteus86.routing import clean


class MatrixExampleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_complete_design_and_optional_probes_preserve_original_partitions(self):
        with patch('subprocess.Popen', side_effect=AssertionError('File example tried to launch software')):
            ordinary = generate(self.directory / 'ordinary')
            instrumented = generate(self.directory / 'instrumented', probes=True)
        self.assertEqual((ordinary['parts'], instrumented['parts']), (32, 48))
        self.assertTrue(ordinary['netcheck']['passed'])
        self.assertTrue(instrumented['netcheck']['passed'])
        self.assertTrue(ordinary['geometry']['passed'])
        self.assertTrue(instrumented['geometry']['passed'])
        c = Circuit.open(ordinary['project'])
        p = Circuit.open(instrumented['project'])
        probes = set(SEGMENT_PROBES + DIGIT_PROBES)
        baseline = sorted(sorted(net) for net in c.nets())
        observed = sorted(sorted(pin for pin in net if pin[0] not in probes) for net in p.nets())
        self.assertEqual(baseline, [net for net in observed if net])
        self.assertFalse(ordinary['simulation_executed'])
        self.assertFalse(instrumented['native_verified'])
        design = json.loads((Path(instrumented['project']).parent / 'design.json').read_text(encoding='utf-8'))
        self.assertEqual(design['initial_display'], '01234567')
        self.assertEqual(design['keys'], list(KEYS))
        self.assertFalse(design['segment_active_low'])
        self.assertTrue(design['digit_active_low'])

    def test_clock_and_decoupling_use_explicit_capacitor_models(self):
        result = generate(self.directory / 'explicit-capacitors')
        parts = {part['ref']: part for part in Circuit.open(result['project']).components()}
        for ref, value in [('CX1', '22p'), ('CX2', '22p'), ('CD1', '100n')]:
            with self.subTest(ref=ref):
                part = parts[ref]
                self.assertEqual(part['device'], 'CAP')
                self.assertEqual(part['value'], value)
                self.assertEqual(part['properties']['PRIMITIVE'], 'ANALOGUE,CAPACITOR')
        self.assertEqual(result['parts'], 32)
        self.assertEqual(result['firmware']['sha256'], firmware_info(
            Path(__file__).resolve().parents[1] / 'examples/matrix_display.hex')['sha256'])
        self.assertTrue(netcheck(result['project'], expected_nets())['passed'])

    def test_hidden_mcu_power_pins_keep_global_nets_without_extra_terminal_stubs(self):
        result = generate(self.directory / 'native-hidden-power', probes=True)
        circuit = Circuit.open(result['project'])
        terminal_pins = {tuple(terminal['pin']) for terminal in circuit.terminals() if terminal.get('pin')}
        self.assertNotIn(('U1', 'VCC'), terminal_pins)
        self.assertNotIn(('U1', 'GND'), terminal_pins)
        self.assertNotIn(('U1', '40'), terminal_pins)
        self.assertNotIn(('U1', '20'), terminal_pins)
        self.assertTrue(netcheck(result['project'], expected_nets(probes=True))['passed'])
        nets = [set(net) for net in circuit.nets()]
        self.assertTrue(any({('U1', 'VCC'), ('U1', '$EA$'), ('CD1', '2')} <= net for net in nets))
        self.assertTrue(any({('U1', 'GND'), ('CD1', '1'), ('RR1', '1')} <= net for net in nets))
        self.assertEqual((result['parts'], len(expected_nets(probes=True))), (48, 29))

    def test_missing_matrix_column_connection_is_not_mistaken_for_complete(self):
        result = generate(self.directory / 'complete')
        c = Circuit.open(result['project'])
        terminal = next(t for t in c.terminals() if t.get('pin') == ('K4', '1') and t['name'] == 'C0')
        c.delete_terminal(terminal['id'])
        missing = c.save(self.directory / 'missing-column.pdsprj')
        check = netcheck(missing, expected_nets())
        self.assertFalse(check['passed'])
        self.assertTrue(any(('K4', '1') in error['expected'] for error in check['errors']))

    def test_moving_whole_bundle_retains_firmware_and_does_not_change_sources(self):
        result = generate(self.directory / 'source')
        source = Path(result['project'])
        original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        moved = self.directory / 'portable copy'
        shutil.copytree(source.parent, moved)
        project = moved / source.name
        properties = next(p['properties'] for p in Circuit.open(project).components() if p['ref'] == 'U1')
        program = properties['PROGRAM']
        self.assertTrue(program.isascii())
        self.assertFalse(Path(program).is_absolute())
        self.assertEqual(hashlib.sha256((moved / program).read_bytes()).hexdigest(), result['firmware']['sha256'])
        self.assertTrue(netcheck(project, expected_nets())['passed'])
        with patch('subprocess.Popen', side_effect=AssertionError('Packaging started an application')):
            bundle = prepare_run(project, self.directory / 'run copy')
        self.assertEqual(bundle['firmware']['U1']['sha256'], result['firmware']['sha256'])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_hash)
        self.assertEqual(hashlib.sha256(project.read_bytes()).hexdigest(), original_hash)

    def test_invalid_requests_leave_existing_data_and_temp_configuration_intact(self):
        existing = self.directory / 'existing'
        existing.mkdir()
        marker = existing / 'keep.txt'
        marker.write_text('keep', encoding='utf-8')
        before_env = (os.environ.get('TEMP'), os.environ.get('TMP'), tempfile.tempdir)
        with self.assertRaises(FileExistsError):
            generate(existing)
        with self.assertRaises(ValueError):
            generate(self.directory / 'invalid', probes=1)
        with self.assertRaises(FileNotFoundError):
            generate(self.directory / 'absent', firmware=self.directory / 'no.hex')
        self.assertFalse((self.directory / 'invalid').exists())
        self.assertFalse((self.directory / 'absent').exists())
        self.assertEqual(marker.read_text(encoding='utf-8'), 'keep')
        self.assertEqual((os.environ.get('TEMP'), os.environ.get('TMP'), tempfile.tempdir), before_env)
        generated = generate(self.directory / 'valid')
        self.assertTrue(generated['passed'])
        self.assertEqual((os.environ.get('TEMP'), os.environ.get('TMP'), tempfile.tempdir), before_env)

    def test_independent_hex_contains_the_complete_small_example(self):
        source = Path(__file__).resolve().parents[1] / 'examples/matrix_display.hex'
        info = firmware_info(source)
        self.assertEqual(info['format'], 'hex')
        self.assertEqual(info['program_bytes'], 235)
        self.assertEqual(info['address_min'], 0)
        self.assertLess(info['address_max'], 2048)

    def test_custom_firmware_does_not_inherit_unverified_display_expectations(self):
        image = Path(__file__).resolve().parents[1] / 'examples/blink8051.hex'
        result = generate(self.directory / 'custom', firmware=image)
        design = json.loads((Path(result['project']).parent / 'design.json').read_text(encoding='utf-8'))
        self.assertFalse(design['bundled_firmware'])
        self.assertTrue(design['custom_firmware_needs_own_scenarios'])
        self.assertIsNone(design['initial_display'])
        self.assertIsNone(design['accepted_key_display'])
        self.assertIsNone(design['recommended_stable_press_seconds'])
        self.assertEqual(result['firmware']['sha256'], firmware_info(image)['sha256'])

    def test_saved_terminal_stubs_follow_real_pin_exits_without_fanout_or_bends(self):
        with patch('subprocess.Popen', side_effect=AssertionError('Layout check launched native software')):
            result = generate(self.directory / 'straight-stubs', probes=True)
        circuit = Circuit.open(result['project'])
        pin_maps = {part['ref']: {pin['name']: pin for pin in circuit.pins(part['ref'])}
                    for part in circuit.components()}
        terminals = {tuple(terminal['pin']): terminal for terminal in circuit.terminals() if terminal.get('pin')}
        for endpoint, terminal in terminals.items():
            ref, name = endpoint
            pin = pin_maps[ref][name]
            length = 762000
            if ref == 'DS1':
                # Odd numbered signal labels occupy the lower display row.
                length = 1524000 if int(terminal['name'][1:]) % 2 else 1016000
            expected = tuple(pin['position'][axis] + pin['direction'][axis] * length for axis in (0, 1))
            with self.subTest(endpoint=endpoint, terminal=terminal['name']):
                self.assertEqual(tuple(terminal['position']), expected)
                self.assertEqual(clean(terminal['points']), [pin['position'], expected])
        # MCU labels remain in each port's real 2.54 mm row order. They may not
        # escape above/below adjacent pins just to satisfy estimated text boxes.
        pins_by_number = {pin['number']: pin for pin in circuit.pins('U1')}
        for pads in ([str(39 - i) for i in range(8)], [str(21 + i) for i in range(8)],
                     [str(10 + i) for i in range(8)]):
            contacts = [terminals[('U1', pins_by_number[pad]['name'])]['position'] for pad in pads]
            self.assertEqual(len({point[0] for point in contacts}), 1)
            self.assertEqual([abs(a[1] - b[1]) for a, b in zip(contacts, contacts[1:])], [254000] * 7)
        for names in (tuple('ABCDEFGH'), tuple(str(i + 1) for i in range(8))):
            contacts = [terminals[('DS1', name)]['position'] for name in names]
            self.assertEqual(len({point[1] for point in contacts}), 2)
            self.assertEqual([abs(a[0] - b[0]) for a, b in zip(contacts, contacts[1:])], [254000] * 7)
            for parity in (0, 1):
                row = contacts[parity::2]
                self.assertEqual(len({point[1] for point in row}), 1)
                self.assertEqual([abs(a[0] - b[0]) for a, b in zip(row, row[1:])], [508000] * 3)
            self.assertEqual(contacts[0][1] - contacts[1][1], 508000)
            labels = [terminals[('DS1', name)]['label']['position'] for name in names]
            self.assertEqual(labels[0][1] - labels[1][1], 508000)
            for contact, caption in zip(contacts, labels):
                # Center the conservative 2-character text width in its lane.
                # Keeping the old left anchor blocks neighboring long stubs.
                self.assertEqual(caption[0], contact[0] - 140000)

    def test_layout_has_no_wire_overlap_crossing_or_close_parallel_runs_and_keeps_probe_grid(self):
        result = generate(self.directory / 'wire-spacing', probes=True)
        quality = result['wire_quality']
        self.assertTrue(quality['passed'], quality)
        self.assertEqual((quality['overlaps'], quality['crossings'], quality['near_parallel']), ([], [], []))
        self.assertGreaterEqual(quality['straight_wires'], quality['wires'] - 3)
        self.assertTrue(result['geometry']['passed'])
        self.assertTrue(result['netcheck']['passed'])
        parts = {part['ref']: part for part in Circuit.open(result['project']).components()}
        for refs in (SEGMENT_PROBES, DIGIT_PROBES):
            positions = [parts[ref]['position'] for ref in refs]
            self.assertEqual(len({point['y'] for point in positions}), 1)
            self.assertEqual([b['x'] - a['x'] for a, b in zip(positions, positions[1:])], [3048000] * 7)
        self.assertEqual(parts['PS0']['position']['y'] - parts['PD0']['position']['y'], 3048000)

    def test_crystal_captions_clear_actual_encoded_clock_wires(self):
        from proteus86.geometry import geometry
        from proteus86._codec.net_objects import decode_net_objects
        result = generate(self.directory / 'clock-captions')
        circuit = Circuit.open(result['project'])
        decoded = decode_net_objects(result['project'])
        _, labels, _ = geometry(circuit, decoded)
        captions = [box for box in labels if box.owner in ('X1:reference', 'X1:value')]
        self.assertEqual(len(captions), 2)
        segments = [(a, b) for wire in decoded['wires'] for a, b in zip(wire['points'], wire['points'][1:])]
        for caption in captions:
            with self.subTest(caption=caption.owner):
                self.assertFalse(any(caption.blocks(a, b) for a, b in segments))
        self.assertLessEqual(result['wire_quality']['bends'], 7)


if __name__ == '__main__':
    unittest.main()
