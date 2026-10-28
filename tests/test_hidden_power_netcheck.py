"""Design power-port normalization stays independent of observed wiring."""
from pathlib import Path
import tempfile
import unittest

from proteus86 import Circuit
from proteus86.inspection import netcheck


class HiddenPowerNetcheckTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def fixture(self, *, second_mcu=False, supply_name='VCC'):
        c = Circuit()
        with c.batch():
            c.add_mm('AT89C51RD2', 'U1', 'AT89C51RD2', 0, 0)
            if second_mcu:
                c.add_mm('AT89C51RD2', 'U2', 'AT89C51RD2', 100, 0)
            c.add_mm('RESISTOR', 'R1', '10k', -60, -90)
            c.add_mm('RESISTOR', 'R2', '10k', -100, -90)
            c.add_terminal('power', supply_name, pin='R1.1')
            c.add_terminal('ground', 'GND', pin='R1.2')
        return c

    def save(self, circuit, name='circuit'):
        return circuit.save(self.directory / (name + '.pdsprj'))

    def expected(self):
        return [['R1.1', 'VCC'], ['R1.2', 'GND']]

    def test_legacy_named_power_design_includes_declared_hidden_pins(self):
        source = self.save(self.fixture())
        result = netcheck(source, self.expected())
        self.assertTrue(result['passed'], result)
        self.assertEqual(result['expected_nets'], 2)
        self.assertTrue(netcheck(source, [
            ['R1.1', 'U1.40', 'VCC'], ['R1.2', 'U1.20', 'GND']])['passed'])

    def test_named_power_design_expands_all_declared_mcus_without_extra_terminals(self):
        c = self.fixture(second_mcu=True)
        source = self.save(c)
        self.assertFalse(any(t.get('pin', ('',))[0].startswith('U') for t in c.terminals()))
        self.assertTrue(netcheck(source, self.expected())['passed'])
        self.assertTrue(netcheck(source, [
            ['R1.1', 'U1.40', 'U2.40'], ['R1.2', 'U1.20', 'U2.20']])['passed'])

    def test_explicit_and_named_power_groups_merge_by_declared_global_identity(self):
        c = self.fixture(second_mcu=True)
        c.add_terminal('power', 'VCC', pin='R2.1')
        source = self.save(c)
        result = netcheck(source, [
            ['U1.40', 'R1.1'], ['U2.40', 'R2.1'], ['VCC'], ['R1.2', 'GND']])
        self.assertTrue(result['passed'], result)
        self.assertEqual(result['expected_nets'], 2)

    def test_wrong_observed_terminal_anchor_does_not_rewrite_design_expectations(self):
        c = self.fixture()
        supply = next(t for t in c.terminals() if t['name'] == 'VCC')
        c.delete_terminal(supply['id'])
        c.add_terminal('power', 'VCC', pin='R2.1')
        result = netcheck(self.save(c), self.expected())
        self.assertFalse(result['passed'])
        self.assertTrue(any(('R1', '1') in error['expected'] for error in result['errors']))

    def test_extra_wire_or_extra_same_name_terminal_is_not_absorbed_into_expected_net(self):
        for use_terminal in (False, True):
            with self.subTest(extra_terminal=use_terminal):
                c = self.fixture()
                if use_terminal:
                    c.add_terminal('power', 'VCC', pin='R2.1')
                else:
                    c.connect('R1.1', 'R2.1')
                result = netcheck(self.save(c, 'extra-' + str(use_terminal)), self.expected())
                self.assertFalse(result['passed'])
                self.assertTrue(any(('R2', '1') in group
                                    for error in result['errors']
                                    for group in error['actual_connected_groups']))
                self.assertTrue(all(('R2', '1') not in error['expected'] for error in result['errors']))

    def test_power_ground_short_remains_an_exact_partition_failure(self):
        c = self.fixture(second_mcu=True)
        c.connect('R1.1', 'R1.2')
        result = netcheck(self.save(c), self.expected())
        self.assertFalse(result['passed'])
        self.assertEqual(len(result['errors']), 2)
        self.assertTrue(all(('U1', 'VCC') in error['actual_connected_groups'][0]
                            and ('U1', 'GND') in error['actual_connected_groups'][0]
                            for error in result['errors']))

    def test_unrelated_port_name_does_not_guess_a_hidden_power_alias(self):
        source = self.save(self.fixture(supply_name='AUX'))
        self.assertTrue(netcheck(source, [['R1.1', 'AUX'], ['R1.2', 'GND']])['passed'])
        result = netcheck(source, [['R1.1', 'U1.40', 'AUX'], ['R1.2', 'GND']])
        self.assertFalse(result['passed'])

    def test_expected_missing_named_power_terminal_still_fails(self):
        c = self.fixture()
        supply = next(t for t in c.terminals() if t['name'] == 'VCC')
        c.delete_terminal(supply['id'])
        with self.assertRaisesRegex(ValueError, 'Expected terminal is missing or detached: VCC'):
            netcheck(self.save(c), self.expected())


if __name__ == '__main__':
    unittest.main()
