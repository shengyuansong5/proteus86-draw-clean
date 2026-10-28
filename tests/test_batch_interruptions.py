"""Interrupted bulk edits must leave a reusable, validated circuit."""
import hashlib
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from proteus86 import Circuit
from proteus86.inspection import netcheck


class BatchInterruptionTests(unittest.TestCase):
    def circuit(self):
        circuit = Circuit()
        with circuit.batch():
            circuit.add_mm('RESISTOR', 'R1', '1k', 0, 0)
            circuit.add_mm('RESISTOR', 'R2', '2k', 50.8, 0)
            circuit.connect('R1.2', 'R2.1')
        return circuit

    def test_body_interrupt_restores_saved_topology_and_allows_later_edits(self):
        for interruption in (KeyboardInterrupt('stop'), SystemExit(23)):
            with self.subTest(interruption=type(interruption).__name__):
                c = self.circuit()
                before = c.summary()
                expected = c.nets()
                with tempfile.TemporaryDirectory() as temporary:
                    source = c.save(Path(temporary) / 'source.pdsprj')
                    original_hash = hashlib.sha256(source.read_bytes()).digest()
                    with self.assertRaises(type(interruption)) as caught:
                        with c.batch():
                            c.update('R1', value='47k')
                            c.add_mm('CAPACITOR', 'C1', '100n', 25.4, 25.4)
                            c.connect('R1.1', 'C1.1')
                            raise interruption
                    self.assertIs(caught.exception, interruption)
                    self.assertEqual(c._batch_depth, 0)
                    self.assertEqual(c.summary(), before)
                    restored = c.save(Path(temporary) / 'restored.pdsprj')
                    self.assertEqual(Circuit.open(restored).nets(), expected)
                    self.assertTrue(netcheck(restored, [net for net in expected if len(net) > 1])['passed'])
                    self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), original_hash)
                    with c.batch():
                        c.update('R1', value='22k')
                    self.assertEqual(next(p['value'] for p in c.components() if p['ref'] == 'R1'), '22k')
                    with self.assertRaises(ValueError):
                        c.connect('R1.2', 'R2.999')

    def test_nested_interrupt_propagates_without_leaving_partial_outer_edits(self):
        for interruption in (KeyboardInterrupt(), SystemExit(17), GeneratorExit()):
            with self.subTest(interruption=type(interruption).__name__):
                c = self.circuit()
                before = c.summary()
                with self.assertRaises(type(interruption)) as caught:
                    with c.batch():
                        c.update('R1', value='47k')
                        with c.batch():
                            c.move_mm('R2', 76.2, 12.7)
                            c.disconnect('R1.2', 'R2.1')
                            raise interruption
                self.assertIs(caught.exception, interruption)
                self.assertEqual(c._batch_depth, 0)
                self.assertEqual(c.summary(), before)
                with c.batch():
                    c.update('R2', value='33k')

    def test_final_validation_interrupt_rolls_back_partly_updated_routes(self):
        for interruption in (KeyboardInterrupt(), SystemExit(19)):
            with self.subTest(interruption=type(interruption).__name__):
                c = self.circuit()
                before = c.summary()

                def interrupted_validation(circuit, parts, connections, terminals=None):
                    connections[0]['points'] = [(100, 100), (200, 100)]
                    raise interruption

                with patch.object(Circuit, '_validate', interrupted_validation):
                    with self.assertRaises(type(interruption)) as caught:
                        with c.batch():
                            c.update('R1', value='47k')
                self.assertIs(caught.exception, interruption)
                self.assertEqual(c._batch_depth, 0)
                self.assertEqual(c.summary(), before)
                with c.batch():
                    c.update('R2', value='33k')

    def test_autoroute_interrupt_restores_options_and_previous_geometry(self):
        for interruption in (KeyboardInterrupt(), SystemExit(29)):
            with self.subTest(interruption=type(interruption).__name__):
                c = self.circuit()
                before = c.summary()
                options = copy.deepcopy(c.routing_options)
                with patch.object(Circuit, '_validate', side_effect=interruption):
                    with self.assertRaises(type(interruption)) as caught:
                        c.autoroute(clearance_mm=2.54, lead_mm=5.08)
                self.assertIs(caught.exception, interruption)
                self.assertEqual(c.routing_options, options)
                self.assertEqual(c.summary(), before)
                c.autoroute()

    def test_interrupted_portable_save_restores_automatic_resource_binding(self):
        image = Path(__file__).resolve().parents[1] / 'examples/blink8051.hex'
        for interruption in (KeyboardInterrupt(), SystemExit(31)):
            with self.subTest(interruption=type(interruption).__name__):
                with tempfile.TemporaryDirectory() as temporary:
                    directory = Path(temporary)
                    c = Circuit()
                    c.add_mm('AT89C52', 'U1', 'AT89C52', 0, 0)
                    c.set_properties('U1', PROGRAM='firmware/cancel-save.hex')
                    source = c.save(directory / 'source/circuit.pdsprj', portable=False)
                    firmware = source.parent / 'firmware/cancel-save.hex'
                    firmware.parent.mkdir()
                    firmware.write_bytes(image.read_bytes())
                    c = Circuit.open(source)
                    before = copy.deepcopy(c.components())
                    resources = copy.deepcopy(c._resources)
                    original_hash = hashlib.sha256(source.read_bytes()).digest()
                    target = directory / 'portable/circuit.pdsprj'
                    with patch.object(Circuit, '_save_file', side_effect=interruption):
                        with self.assertRaises(type(interruption)) as caught:
                            c.save(target)
                    self.assertIs(caught.exception, interruption)
                    self.assertEqual(c._batch_depth, 0)
                    self.assertEqual(c.components(), before)
                    self.assertEqual(c._resources, resources)
                    self.assertFalse(target.exists())
                    self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), original_hash)
                    restored = c.save(target)
                    program = Circuit.open(restored).components()[0]['properties']['PROGRAM']
                    self.assertTrue((restored.parent / program).is_file())


if __name__ == '__main__':
    unittest.main()
