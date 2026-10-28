"""Hidden PP power follows explicit package text; physical wires stay separate."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from proteus86 import Circuit
from proteus86._codec.device_library import definition_groups, describe_definition
from proteus86.inspection import netcheck


class HiddenPowerTests(unittest.TestCase):
    def fixture(self, *, second_mcu=False):
        c = Circuit()
        with c.batch():
            c.add_mm('AT89C51RD2', 'U1', 'AT89C51RD2', 0, 0)
            if second_mcu:
                c.add_mm('AT89C51RD2', 'U2', 'AT89C51RD2', 100, 0)
            c.add_mm('RESISTOR', 'R1', '10k', -60, -90)
            c.add_terminal('power', 'VCC', pin='R1.1')
            c.add_terminal('ground', 'GND', pin='R1.2')
        return c

    def model(self, circuit):
        definition = definition_groups(circuit._dsn)['devices']['AT89C51RD2']
        return describe_definition({'name': 'AT89C51RD2'}, definition['body'])

    def same_net(self, circuit, first, second, *, physical=False):
        return any({first, second} <= set(group) for group in circuit.nets(physical=physical))

    def test_native_declared_pp_pins_join_global_nets_without_terminal_stubs(self):
        c = self.fixture(second_mcu=True)
        self.assertTrue(self.same_net(c, ('U1', 'VCC'), ('R1', '1')))
        self.assertTrue(self.same_net(c, ('U1', 'GND'), ('R1', '2')))
        self.assertTrue(self.same_net(c, ('U1', 'VCC'), ('U2', 'VCC')))
        self.assertFalse(self.same_net(c, ('U1', 'VCC'), ('U1', 'GND')))
        self.assertFalse(self.same_net(c, ('U1', 'VCC'), ('R1', '1'), physical=True))
        self.assertFalse(self.same_net(c, ('U1', 'VCC'), ('U2', 'VCC'), physical=True))
        self.assertFalse(any(t.get('pin', ('',))[0] in {'U1', 'U2'} for t in c.terminals()))
        with tempfile.TemporaryDirectory() as temporary:
            source = c.save(Path(temporary) / 'hidden-power.pdsprj')
            opened = Circuit.open(source)
            self.assertEqual(opened.nets(), c.nets())
            self.assertEqual(opened.nets(physical=True), c.nets(physical=True))
            self.assertTrue(netcheck(source, [
                ['U1.40', 'U2.40', 'R1.1'], ['U1.20', 'U2.20', 'R1.2']])['passed'])

    def test_missing_unknown_or_mismatched_selected_package_does_not_invent_connections(self):
        for value in (None, 'UNKNOWN', 'PLCC44'):
            with self.subTest(package=value):
                c = self.fixture()
                c.set_properties('U1', PACKAGE=value)
                self.assertFalse(self.same_net(c, ('U1', 'VCC'), ('R1', '1')))
                self.assertFalse(self.same_net(c, ('U1', 'GND'), ('R1', '2')))

    def test_cloned_unknown_pp_name_and_wrong_complete_pad_mapping_are_not_aliases(self):
        c = self.fixture()
        original = self.model(c)
        for replacement in ('PP (UNKNOWN) = 40', 'PP (VCC) = 20', 'PP (VCC) = 40/41', 'PP (VCC) = *'):
            with self.subTest(declaration=replacement):
                clone = copy.deepcopy(original)
                clone['pinouts']['DIL40'] = [replacement if line == 'PP (VCC) = 40' else line
                                            for line in clone['pinouts']['DIL40']]
                with patch('proteus86.connectivity.describe_definition', return_value=clone):
                    self.assertFalse(self.same_net(c, ('U1', 'VCC'), ('R1', '1')))
                    # Reusing pad 20 for both PP names invalidates the complete
                    # package's implicit map, rather than joining either rail.
                    self.assertEqual(self.same_net(c, ('U1', 'GND'), ('R1', '2')),
                                     replacement != 'PP (VCC) = 20')
                    self.assertFalse(self.same_net(c, ('U1', 'VCC'), ('R1', '2')))

    def test_cloned_missing_pp_declarations_do_not_guess_from_vcc_or_gnd_spelling(self):
        c = self.fixture()
        clone = self.model(c)
        clone['pinouts']['DIL40'] = [line for line in clone['pinouts']['DIL40'] if not line.startswith('PP ')]
        with patch('proteus86.connectivity.describe_definition', return_value=clone):
            self.assertFalse(self.same_net(c, ('U1', 'VCC'), ('R1', '1')))
            self.assertFalse(self.same_net(c, ('U1', 'GND'), ('R1', '2')))

    def test_cloned_ambiguous_or_non_single_unit_package_is_not_merged(self):
        c = self.fixture()
        original = self.model(c)
        edits = [lambda lines: lines + ['PP (VCC) = 41'],
                 lambda lines: lines + ['PP (ALIAS) = 40'],
                 lambda lines: lines + ['PP broken'],
                 lambda lines: [line.replace('ELEMENTS=1', 'ELEMENTS=2') for line in lines],
                 lambda lines: [line for line in lines if line != 'ELEMENTS=1']]
        for index, edit in enumerate(edits):
            with self.subTest(edit=index):
                clone = copy.deepcopy(original)
                clone['pinouts']['DIL40'] = edit(clone['pinouts']['DIL40'])
                with patch('proteus86.connectivity.describe_definition', return_value=clone):
                    self.assertFalse(self.same_net(c, ('U1', 'VCC'), ('R1', '1')))
                    self.assertFalse(self.same_net(c, ('U1', 'GND'), ('R1', '2')))

    def test_physical_query_never_reads_implicit_power_metadata(self):
        c = self.fixture()
        with patch('proteus86.connectivity.definition_groups',
                   side_effect=AssertionError('physical query inspected implicit model power')):
            self.assertFalse(self.same_net(c, ('U1', 'VCC'), ('R1', '1'), physical=True))

    def test_cloned_grouped_pad_mapping_only_joins_its_exact_declared_logical_pin(self):
        c = self.fixture()
        clone = self.model(c)
        clone['pinouts']['DIL40'] = [line.replace('PP (VCC) = 40', 'PP (VCC) = 40/41')
                                    for line in clone['pinouts']['DIL40']]
        part = c._parts[c._index('U1')]
        template = copy.deepcopy(c._template(part))
        template['pins'] = [(name, '40/41' if name == 'VCC' else number)
                            for name, number in template['pins']]
        part['template'] = template
        with patch('proteus86.connectivity.describe_definition', return_value=clone):
            self.assertTrue(self.same_net(c, ('U1', 'VCC'), ('R1', '1')))
            self.assertTrue(self.same_net(c, ('U1', 'GND'), ('R1', '2')))
            self.assertFalse(self.same_net(c, ('U1', 'P0.0/AD0'), ('R1', '1')))

    def test_braced_package_text_and_current_call_metadata_reuse(self):
        c = self.fixture(second_mcu=True)
        clone = self.model(c)
        clone['pinouts']['DIL40'] = ['{' + line.replace('ELEMENTS=1', 'ELEMENTS = 1') + '}'
                                    for line in clone['pinouts']['DIL40']]
        with patch('proteus86.connectivity.describe_definition', return_value=clone) as describe:
            with patch('proteus86.connectivity.definition_groups', wraps=definition_groups) as definitions:
                self.assertTrue(self.same_net(c, ('U1', 'VCC'), ('U2', 'VCC')))
                self.assertEqual((describe.call_count, definitions.call_count), (1, 1))

    def test_successive_model_or_package_edits_do_not_use_stale_implicit_membership(self):
        c = self.fixture()
        self.assertTrue(self.same_net(c, ('U1', 'VCC'), ('R1', '1')))
        c.set_properties('U1', PACKAGE='UNKNOWN')
        self.assertFalse(self.same_net(c, ('U1', 'VCC'), ('R1', '1')))
        c.set_properties('U1', PACKAGE='DIL40')
        self.assertTrue(self.same_net(c, ('U1', 'VCC'), ('R1', '1')))


if __name__ == '__main__':
    unittest.main()
