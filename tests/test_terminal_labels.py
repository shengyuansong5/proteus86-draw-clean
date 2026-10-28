"""Public terminal text anchors preserve symbols, nets, styles and rollback."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from proteus86 import Circuit
from proteus86._codec.net_objects import decode_net_objects
from proteus86.inspection import netcheck
from proteus86.routing import RoutingError


class TerminalLabelTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        no_native = patch('subprocess.Popen', side_effect=AssertionError('Terminal text edit launched software'))
        no_native.start()
        self.addCleanup(no_native.stop)

    def circuit(self):
        c = Circuit()
        with c.batch():
            c.add_mm('RES', 'R1', '10k', 0, 0, library='DEVICE')
            c.add_mm('RES', 'R2', '22k', 40, 0, library='DEVICE', rotation=90)
            c.connect('R1.2', 'R2.1')
            first = c.add_terminal('label', 'IN', 'R1.1')
            second = c.add_terminal('label', 'OUT', 'R2.2')
            standalone = c.add_terminal('label', 'SPARE', position=(6500000, 2000000), rotation=90)
        return c, (first, second, standalone)

    def test_default_getter_matches_saved_encoder_for_rotated_pins_and_standalone(self):
        c, identities = self.circuit()
        before = c.terminals()
        positions = [c.terminal_label_position(identity) for identity in identities]
        self.assertTrue(all(isinstance(point, tuple) and all(type(v) is int for v in point) for point in positions))
        self.assertEqual(c.terminals(), before)  # A getter never materializes label metadata.
        saved = Circuit.open(c.save(self.directory / 'defaults.pdsprj'))
        self.assertEqual([saved.terminal_label_position(identity) for identity in identities], positions)
        self.assertEqual([t['label']['position'] for t in saved.terminals()], positions)

    def test_saved_edit_changes_text_anchor_only_and_preserves_source_and_topology(self):
        c, (identity, _, _) = self.circuit()
        source = c.save(self.directory / 'source.pdsprj')
        source_hash = hashlib.sha256(source.read_bytes()).digest()
        edited = Circuit.open(source)
        parts, nets = edited.components(), edited.nets()
        terminal_before = edited.terminals()[0]
        wires_before = [wire['points'] for wire in decode_net_objects(source)['wires']]
        point = [1500000, 2500000]
        self.assertIs(edited.set_terminal_label_position(identity, point), edited)
        point[0] = 99  # Input arrays are not retained by reference.
        self.assertEqual(edited.terminal_label_position(identity), (1500000, 2500000))
        target = edited.save(self.directory / 'edited.pdsprj')
        reopened = Circuit.open(target)
        self.assertEqual(reopened.terminal_label_position(identity), (1500000, 2500000))
        self.assertEqual(reopened.components(), parts)
        self.assertEqual(reopened.nets(), nets)
        self.assertEqual([wire['points'] for wire in decode_net_objects(target)['wires']], wires_before)
        terminal_after = reopened.terminals()[0]
        for key in ('id', 'name', 'kind', 'pin', 'position', 'rotation', 'rotation_raw', 'points'):
            self.assertEqual(terminal_after[key], terminal_before[key], key)
        self.assertTrue(netcheck(target, [['R1.2', 'R2.1'], ['R1.1'], ['R2.2']])['passed'])
        self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), source_hash)

    def test_custom_stored_font_tail_survives_move_reset_and_reopen(self):
        c, (identity, _, _) = self.circuit()
        c = Circuit.open(c.save(self.directory / 'style-base.pdsprj'))
        # Build a nondefault-font fixture in the supported decoded metadata.
        # Normal save validates the unchanged terminal role/style structure.
        label = c._terminals[0]['label']
        tail = bytes.fromhex(label['tail_hex'])
        self.assertIn(b'Default Font\0', tail)
        label['tail_hex'] = tail.replace(b'Default Font\0', b'Courier New\0').hex()
        styled_path = c.save(self.directory / 'custom-font.pdsprj')
        c = Circuit.open(styled_path)
        default = c.terminal_label_position(identity)
        original_style = bytes.fromhex(c.terminals()[0]['label']['tail_hex'])[8:]
        self.assertIn(b'Courier New\0', original_style)
        c.set_terminal_label_position(identity, (-2000000, 2000000))
        moved = Circuit.open(c.save(self.directory / 'styled-moved.pdsprj'))
        self.assertEqual(bytes.fromhex(moved.terminals()[0]['label']['tail_hex'])[8:], original_style)
        moved.set_terminal_label_position(identity, None)
        self.assertEqual(moved.terminal_label_position(identity), default)
        reset = Circuit.open(moved.save(self.directory / 'styled-reset.pdsprj'))
        self.assertEqual(reset.terminal_label_position(identity), default)
        self.assertEqual(bytes.fromhex(reset.terminals()[0]['label']['tail_hex'])[8:], original_style)

    def test_reset_uses_current_glyph_orientation_after_an_explicit_rotation(self):
        c, (identity, _, standalone) = self.circuit()
        default = c.terminal_label_position(standalone)
        c.set_terminal_label_position(standalone, (1500000, 2500000))
        c.set_terminal_label_position(standalone, None)
        self.assertEqual(c.terminal_label_position(standalone), default)
        c.update_terminal(standalone, rotation=180)
        rotated_default = c.terminal_label_position(standalone)
        self.assertNotEqual(rotated_default, default)
        c.set_terminal_label_position(standalone, (6000000, 4000000))
        c.set_terminal_label_position(standalone, None)
        self.assertEqual(c.terminal_label_position(standalone), rotated_default)

    def test_invalid_coordinates_and_unknown_ids_leave_all_requests_unchanged(self):
        c, (identity, _, _) = self.circuit()
        before = copy.deepcopy((c.terminals(), c.connections(), c.components()))
        for position in ((True, 1), (1, False), (1.0, 2), (float('nan'), 0),
                         (0, float('inf')), (2**31, 0), (-2**31 - 1, 0),
                         (1,), (1, 2, 3), '12', {'x': 1, 'y': 2}):
            with self.subTest(position=position), self.assertRaisesRegex(ValueError, 'signed int32'):
                c.set_terminal_label_position(identity, position)
        for bad_id in ('T404', '', None, True, 1):
            with self.subTest(identity=bad_id):
                with self.assertRaisesRegex(ValueError, 'terminal ID'):
                    c.terminal_label_position(bad_id)
                with self.assertRaisesRegex(ValueError, 'terminal ID'):
                    c.set_terminal_label_position(bad_id, None)
        self.assertEqual((c.terminals(), c.connections(), c.components()), before)

    def test_signed_int32_boundary_coordinates_are_accepted_without_coercion(self):
        c, (_, _, identity) = self.circuit()
        c.set_terminal_label_position(identity, (-2**31, 2**31 - 1))
        self.assertEqual(c.terminal_label_position(identity), (-2**31, 2**31 - 1))

    def test_real_pin_escape_failure_rolls_back_caption_edit(self):
        c, (identity, _, _) = self.circuit()
        before = copy.deepcopy((c.terminals(), c.connections(), c.nets()))
        obstructed = next(pin for pin in c.pins('R2') if pin['number'] == '1')['position']
        with self.assertRaises(RoutingError):
            c.set_terminal_label_position(identity, obstructed)
        self.assertEqual((c.terminals(), c.connections(), c.nets()), before)
        self.assertEqual(c._batch_depth, 0)
        Circuit.open(c.save(self.directory / 'after-failed-label.pdsprj'))

    def test_nested_batch_interruption_restores_all_labels_and_original_exception(self):
        c, (first, second, _) = self.circuit()
        before = copy.deepcopy((c.terminals(), c.connections(), c.nets()))
        interruption = KeyboardInterrupt('cancel label group')
        with self.assertRaises(KeyboardInterrupt) as caught:
            with c.batch():
                c.set_terminal_label_position(first, (-2000000, 2500000))
                with c.batch():
                    c.set_terminal_label_position(second, (4000000, 2500000))
                    raise interruption
        self.assertIs(caught.exception, interruption)
        self.assertEqual((c.terminals(), c.connections(), c.nets()), before)
        self.assertEqual(c._batch_depth, 0)

    def test_final_validation_interruption_restores_stored_style_and_anchor(self):
        c, (identity, _, _) = self.circuit()
        c = Circuit.open(c.save(self.directory / 'before-validation.pdsprj'))
        before = c.terminals()
        interruption = KeyboardInterrupt('interrupted label validation')
        with patch.object(c, '_validate', side_effect=interruption):
            with self.assertRaises(KeyboardInterrupt) as caught:
                c.set_terminal_label_position(identity, (-2000000, 2500000))
        self.assertIs(caught.exception, interruption)
        self.assertEqual(c.terminals(), before)
        self.assertEqual(c._batch_depth, 0)


if __name__ == '__main__':
    unittest.main()
