import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from examples import build_demo_firmware as demo


ROOT = Path(__file__).resolve().parents[1]
TEMP_PARENT = ROOT / 'artifacts' / 'demo-firmware-tests'


class DemoFirmwareBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TEMP_PARENT.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=TEMP_PARENT)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def fixture(self, name):
        return ROOT / 'examples' / name

    def source(self, text):
        path = self.directory / 'input.a51'
        path.write_text(text, encoding='utf-8')
        return path

    def test_both_original_sources_reproduce_every_occupied_address(self):
        for name, count in (('blink8051', 39), ('key_counter', 42)):
            with self.subTest(name=name):
                source, reference = self.fixture(name + '.a51'), self.fixture(name + '.hex')
                before = source.read_bytes(), reference.read_bytes()
                result = demo.build(source, self.directory / name, check_against=reference)
                rebuilt = demo.hex_codec.decode_hex((self.directory / name / (name + '.hex')).read_text())
                expected = demo.hex_codec.decode_hex(before[1].decode('ascii'))
                self.assertEqual(rebuilt, expected)
                self.assertEqual(result['program_bytes'], count)
                self.assertTrue(result['reference_address_bytes_equal'])
                self.assertEqual(result['source_sha256'], hashlib.sha256(before[0]).hexdigest())
                self.assertEqual(result['reference_hex_sha256'], hashlib.sha256(before[1]).hexdigest())
                self.assertEqual(result['builder_source_sha256'], hashlib.sha256(Path(demo.__file__).read_bytes()).hexdigest())
                self.assertEqual(result['hex_codec_source_sha256'], hashlib.sha256(Path(demo.hex_codec.__file__).read_bytes()).hexdigest())
                self.assertEqual((source.read_bytes(), reference.read_bytes()), before)

    def test_known_blink_opcodes_calls_and_backward_branches(self):
        assembly = demo.assemble(self.fixture('blink8051.a51').read_text())
        data = bytes(assembly.image[index] for index in range(39))
        self.assertEqual(data[:6], bytes.fromhex('75 90 FF 75 A0 00'))
        self.assertEqual(assembly.symbols['DELAY'], 0x1A)
        self.assertEqual(data[12:15], bytes.fromhex('12 00 1A'))
        self.assertEqual(data[24:26], bytes.fromhex('80 EC'))
        self.assertEqual(data[32:], bytes.fromhex('DD FE DE FA DF F6 22'))

    def test_known_counter_bit_branches_register_and_accumulator_opcodes(self):
        assembly = demo.assemble(self.fixture('key_counter.a51').read_text())
        data = bytes(assembly.image[index] for index in range(42))
        self.assertEqual(data[:11], bytes.fromhex('75 81 60 78 00 75 90 FF 20 B2 FD'))
        self.assertEqual(data[17:21], bytes.fromhex('08 E8 F4 F5'))
        self.assertEqual(data[22:25], bytes.fromhex('30 B2 FD'))
        self.assertEqual(assembly.symbols['DELAY'], 0x21)

    def test_mutated_immediate_changes_actual_generated_byte(self):
        text = self.fixture('blink8051.a51').read_text()
        original = demo.assemble(text).image
        changed = demo.assemble(text.replace('MOV R7,#8', 'MOV R7,#9')).image
        self.assertEqual([address for address in original if original[address] != changed[address]], [27])
        self.assertEqual(changed[27], 9)

    def test_inserted_instruction_relocates_both_forward_calls(self):
        text = self.fixture('blink8051.a51').read_text()
        changed = demo.assemble(text.replace('DELAY:  MOV', '        NOP\nDELAY:  MOV'))
        self.assertEqual(changed.symbols['DELAY'], 0x1B)
        calls = [entry for entry in changed.listing if entry['instruction'].startswith('LCALL')]
        self.assertEqual([entry['bytes'] for entry in calls], ['12001B', '12001B'])

    def test_sparse_segments_and_lowercase_tab_syntax(self):
        assembly = demo.assemble('cseg at 0\nmov\tsp,#0x60\nCSEG AT 0100H\nHERE: ret\nend\n')
        self.assertEqual(assembly.image, {0: 0x75, 1: 0x81, 2: 0x60, 0x100: 0x22})
        self.assertEqual(assembly.symbols, {'HERE': 0x100})

    def test_relative_branch_limits_are_signed_and_checked_after_resolution(self):
        accepted = demo.assemble('CSEG AT 0\nSJMP TARGET\n' + 'NOP\n' * 127 + 'TARGET: RET\nEND')
        self.assertEqual(accepted.image[1], 127)
        accepted = demo.assemble('CSEG AT 0\nSTART: NOP\n' + 'NOP\n' * 125 + 'SJMP START\nEND')
        self.assertEqual(accepted.image[127], 0x80)
        for text in ('CSEG AT 0\nSJMP TARGET\n' + 'NOP\n' * 128 + 'TARGET: RET\nEND',
                     'CSEG AT 0\nSTART: NOP\n' + 'NOP\n' * 126 + 'SJMP START\nEND'):
            with self.subTest(source=text[:30]), self.assertRaisesRegex(demo.AssemblyError, '-128..127'):
                demo.assemble(text)

    def test_unknown_labels_duplicate_reserved_and_missing_boundaries_rejected(self):
        cases = {
            'unknown': 'CSEG AT 0\nLCALL MISSING\nEND',
            'duplicate': 'CSEG AT 0\nX: NOP\nX: RET\nEND',
            'reserved': 'CSEG AT 0\nSP: RET\nEND',
            'before_segment': 'RET\nEND',
            'label_before_segment': 'X:\nCSEG AT 0\nRET\nEND',
            'missing_end': 'CSEG AT 0\nRET',
            'after_end': 'CSEG AT 0\nRET\nEND\nNOP',
            'empty': 'CSEG AT 0\nEND',
        }
        for name, text in cases.items():
            with self.subTest(name=name), self.assertRaises(demo.AssemblyError):
                demo.assemble(text)

    def test_external_directives_unknown_forms_and_expressions_rejected(self):
        for statement in ('INCLUDE lib.inc', '$INCLUDE (lib.inc)', 'EXTRN CODE (INIT)',
                          'ORG 0', 'DB 0', 'MACRO X', 'MOV DPTR,#0', 'MOV A,A', 'CPL SP',
                          'DJNZ 90H,X', 'MOV R0,#1+2', 'MOV R0,', 'INC R8'):
            with self.subTest(statement=statement), self.assertRaises(demo.AssemblyError):
                demo.assemble('CSEG AT 0\n' + statement + '\nEND')

    def test_numeric_and_instruction_address_overflow_rejected(self):
        for text in ('CSEG AT 10000H\nRET\nEND',
                     'CSEG AT 0\nMOV R0,#256\nEND',
                     'CSEG AT 0\nMOV 100H,#1\nEND',
                     'CSEG AT 0\nJB 100H,0\nEND',
                     'CSEG AT 0\nLCALL 10000H\nEND',
                     'CSEG AT 0FFFFH\nLCALL 0\nEND',
                     'CSEG AT 0\nMOV R0,#-1\nEND'):
            with self.subTest(source=text), self.assertRaises(demo.AssemblyError):
                demo.assemble(text)

    def test_overlapping_code_addresses_are_rejected(self):
        with self.assertRaisesRegex(demo.AssemblyError, 'overlapping code at 0001H'):
            demo.assemble('CSEG AT 0\nMOV R0,#1\nCSEG AT 1\nRET\nEND')

    def test_reference_record_segmentation_does_not_change_address_comparison(self):
        image = demo.assemble(self.fixture('key_counter.a51').read_text()).image
        reference = self.directory / 'differently-segmented.hex'
        reference.write_text(demo.hex_codec.encode_hex(image, record_size=7), encoding='ascii')
        result = demo.build(self.fixture('key_counter.a51'), self.directory / 'build', check_against=reference)
        self.assertTrue(result['reference_address_bytes_equal'])
        self.assertFalse(result['reference_hex_bytes_equal'])

    def test_mismatched_reference_fails_before_writing_output(self):
        reference = self.directory / 'reference.hex'
        image = demo.assemble(self.fixture('blink8051.a51').read_text()).image
        image[27] = 9
        reference.write_text(demo.hex_codec.encode_hex(image), encoding='ascii')
        output = self.directory / 'build'
        with self.assertRaisesRegex(demo.AssemblyError, '001BH'):
            demo.build(self.fixture('blink8051.a51'), output, check_against=reference)
        self.assertFalse(output.exists())

    def test_missing_reference_address_is_not_ignored(self):
        reference = self.directory / 'reference.hex'
        image = demo.assemble(self.fixture('blink8051.a51').read_text()).image
        del image[0]
        reference.write_text(demo.hex_codec.encode_hex(image), encoding='ascii')
        with self.assertRaisesRegex(demo.AssemblyError, '0000H'):
            demo.build(self.fixture('blink8051.a51'), self.directory / 'build', check_against=reference)
        self.assertFalse((self.directory / 'build').exists())

    def test_bad_reference_checksum_fails_before_output(self):
        reference = self.directory / 'bad.hex'
        reference.write_text(':010000002200\n:00000001FF\n', encoding='ascii')
        with self.assertRaisesRegex(demo.hex_codec.AssemblyError, 'checksum'):
            demo.build(self.fixture('blink8051.a51'), self.directory / 'build', check_against=reference)
        self.assertFalse((self.directory / 'build').exists())

    def test_existing_destination_and_invalid_source_preserve_files(self):
        destination = self.directory / 'build'
        destination.mkdir()
        sentinel = destination / 'keep.txt'
        sentinel.write_bytes(b'original')
        with self.assertRaises(FileExistsError):
            demo.build(self.fixture('blink8051.a51'), destination)
        self.assertEqual(sentinel.read_bytes(), b'original')
        invalid = self.source('CSEG AT 0\nINCLUDE x\nEND')
        with self.assertRaises(demo.AssemblyError):
            demo.build(invalid, self.directory / 'invalid-build')
        self.assertFalse((self.directory / 'invalid-build').exists())

    def test_unicode_space_paths_cli_manifest_and_original_preservation(self):
        source_dir = self.directory / '独立 source'
        source_dir.mkdir()
        source = source_dir / '计数 demo.a51'
        raw = self.fixture('key_counter.a51').read_bytes()
        source.write_bytes(raw)
        output = self.directory / '中文 output'
        environment = {**os.environ, 'TEMP': str(self.directory), 'TMP': str(self.directory),
                       'PYTHONDONTWRITEBYTECODE': '1'}
        run = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(Path(demo.__file__)),
                              '--source', str(source), '--output-dir', str(output),
                              '--check-against', str(self.fixture('key_counter.hex'))],
                             cwd=ROOT, env=environment, capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['hex'], '计数 demo.hex')
        self.assertEqual(manifest['program_bytes'], 42)
        self.assertTrue(manifest['reference_address_bytes_equal'])
        self.assertEqual(source.read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()
