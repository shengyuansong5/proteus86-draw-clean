"""Reproducible, tool-independent assembly checks; no Proteus is launched."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples.build_matrix_firmware import AssemblyError, assemble, build, decode_hex, encode_hex


EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'


class MatrixAssemblerTests(unittest.TestCase):
    def test_source_build_matches_all_235_reference_bytes_at_their_addresses(self):
        source = (EXAMPLES / 'matrix_display.a51').read_text(encoding='utf-8')
        with patch('subprocess.Popen', side_effect=AssertionError('assembler launched software')):
            assembly = assemble(source)
            actual = decode_hex(encode_hex(assembly.image))
        reference = decode_hex((EXAMPLES / 'matrix_display.hex').read_text(encoding='ascii'))
        self.assertEqual(actual, reference)
        self.assertEqual(len(actual), 235)
        self.assertEqual(actual[0], 0x02)  # reset vector: LJMP START
        self.assertEqual(assembly.symbols['START']['value'], 0x30)
        self.assertNotIn(0x10, actual)  # interrupt-vector gap remains sparse
        self.assertEqual(assembly.symbols['SEGMENTS']['value'], 0x108)

    def test_changed_immediate_changes_machine_code_without_reference_input(self):
        source = (EXAMPLES / 'matrix_display.a51').read_text(encoding='utf-8')
        original = assemble(source)
        changed = assemble(source.replace('MOV R6,#250', 'MOV R6,#249'))
        differences = [address for address in original.image
                       if original.image[address] != changed.image[address]]
        self.assertEqual(len(differences), 1)
        self.assertEqual((original.image[differences[0]], changed.image[differences[0]]), (250, 249))
        self.assertEqual(original.symbols, changed.symbols)

    def test_forward_labels_are_relocated_from_source(self):
        source = 'CSEG AT 0\nMOV DPTR,#TABLE\nSJMP DONE\nTABLE: DB 3FH\nDONE: RET\nEND\n'
        original = assemble(source)
        changed = assemble(source.replace('TABLE: DB', 'NOP\nTABLE: DB'))
        self.assertEqual(original.image[2], 5)
        self.assertEqual(changed.image[2], 6)
        self.assertEqual(original.image[4], 1)
        self.assertEqual(changed.image[4], 2)
        self.assertEqual(changed.symbols['DONE']['value'], original.symbols['DONE']['value'] + 1)

    def test_instruction_operand_order_and_signed_branches(self):
        source = ('X DATA 20H\nY DATA 21H\nCSEG AT 0\nLOOP: MOV X,Y\n'
                  'MOV 0B0H,R3\nMOV @R0,A\nMOV A,@R0\nCJNE A,X,LOOP\nEND\n')
        # MOV direct,direct stores source before destination. Relative target
        # is measured from the end of the current instruction (10 bytes).
        self.assertEqual(bytes(assemble(source).image.values()),
                         bytes([0x85, 0x21, 0x20, 0x8B, 0xB0, 0xF6, 0xE6, 0xB5, 0x20, 0xF6]))

    def test_unknown_syntax_invalid_labels_and_address_ranges_fail_closed(self):
        invalid = {
            'unknown instruction': 'CSEG AT 0\nPUSH A\nEND',
            'unknown directive': 'CSEG AT 0\nORG 20H\nEND',
            'unsupported register': 'CSEG AT 0\nMOV R8,#1\nEND',
            'missing label': 'CSEG AT 0\nLCALL MISSING\nEND',
            'duplicate label': 'CSEG AT 0\nLOOP: NOP\nLOOP: RET\nEND',
            'reserved label': 'CSEG AT 0\nA: RET\nEND',
            'wrong symbol kind': 'X DATA 20H\nCSEG AT 0\nLCALL X\nEND',
            'large immediate': 'CSEG AT 0\nMOV A,#100H\nEND',
            'negative immediate': 'CSEG AT 0\nMOV A,#-1\nEND',
            'large data address': 'X DATA 100H\nCSEG AT 0\nRET\nEND',
            'large origin': 'CSEG AT 10000H\nRET\nEND',
            'address overflow': 'CSEG AT 0FFFFH\nLJMP 0\nEND',
            'label beyond code space': 'CSEG AT 0FFFFH\nNOP\nPAST_END:\nEND',
            'overlapping code': 'CSEG AT 0\nLJMP 0\nCSEG AT 1\nRET\nEND',
            'branch range': 'CSEG AT 0\nSJMP FAR\nCSEG AT 200H\nFAR: RET\nEND',
            'missing END': 'CSEG AT 0\nRET',
            'statement after END': 'CSEG AT 0\nRET\nEND\nNOP',
            'missing section': 'RET\nEND',
            'empty operand': 'CSEG AT 0\nMOV A,\nEND',
            'expressions unsupported': 'CSEG AT 0\nMOV A,#1+2\nEND',
        }
        for name, source in invalid.items():
            with self.subTest(name=name), self.assertRaises(AssemblyError):
                assemble(source)
        with self.assertRaisesRegex(AssemblyError, 'line 2:.*MISSING'):
            assemble('CSEG AT 0\nLCALL MISSING\nEND')

    def test_hex_checksums_record_types_and_sparse_round_trip(self):
        image = {0: 2, 1: 0, 2: 0x30, 0xFFFF: 0x22}
        text = encode_hex(image)
        self.assertEqual(decode_hex(text), image)
        corrupted = text.replace('020030', '020031', 1)
        for invalid in [corrupted, ':00000001FE\n', ':00000001FF\n',
                        text + ':00000001FF\n', text.replace(':00000001FF\n', ''),
                        ':0100000200FD\n:00000001FF\n',
                        ':02FFFF002200DE\n:00000001FF\n',
                        text.splitlines()[0] + '\n' + text,
                        ':0100000000FF0\n:00000001FF\n']:
            with self.subTest(text=invalid), self.assertRaises(AssemblyError):
                decode_hex(invalid)
        for invalid in [{0x10000: 0}, {-1: 0}, {0: 256}, {True: 0}]:
            with self.assertRaises(AssemblyError):
                encode_hex(invalid)

    def test_manifest_is_reproducible_and_has_source_to_addressed_byte_hash(self):
        source = EXAMPLES / 'matrix_display.a51'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch('subprocess.Popen', side_effect=AssertionError('build launched software')):
                first = build(source, root / 'first', check_against=EXAMPLES / 'matrix_display.hex')
                second = build(source, root / 'second', check_against=EXAMPLES / 'matrix_display.hex')
            self.assertEqual(first, second)
            self.assertFalse(first['external_tools_used'])
            self.assertFalse(first['native_simulation_executed'])
            self.assertTrue(first['reference_address_bytes_equal'])
            self.assertEqual(first['source_sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(first, json.loads((root / 'first/manifest.json').read_text(encoding='utf-8')))
            image = decode_hex((root / 'first/matrix_display.hex').read_text(encoding='ascii'))
            addressed = b''.join(address.to_bytes(2, 'big') + bytes([image[address]]) for address in sorted(image))
            self.assertEqual(first['addressed_bytes_sha256'], hashlib.sha256(addressed).hexdigest())
            self.assertEqual((root / 'first/matrix_display.hex').read_bytes(),
                             (root / 'second/matrix_display.hex').read_bytes())
            self.assertEqual((root / 'first/manifest.json').read_bytes(),
                             (root / 'second/manifest.json').read_bytes())
            with self.assertRaises(FileExistsError):
                build(source, root / 'first')
            bad = root / 'invalid.a51'
            bad.write_text('CSEG AT 0\nBAD\nEND', encoding='utf-8')
            with self.assertRaises(AssemblyError):
                build(bad, root / 'failed')
            self.assertFalse((root / 'failed').exists())
            with self.assertRaisesRegex(AssemblyError, 'reference differs'):
                reference = root / 'different.hex'
                reference.write_text(encode_hex({0: 0x22}), encoding='ascii')
                build(source, root / 'mismatch', check_against=reference)
            self.assertFalse((root / 'mismatch').exists())

    def test_build_from_isolated_source_needs_no_bundled_hex_or_external_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'standalone.a51'
            source.write_text('CSEG AT 0\nMOV A,#5AH\nRET\nEND\n', encoding='utf-8')
            with patch('subprocess.Popen', side_effect=AssertionError('build launched software')):
                manifest = build(source, root / 'output')
            self.assertEqual(decode_hex((root / 'output/matrix_display.hex').read_text('ascii')),
                             {0: 0x74, 1: 0x5A, 2: 0x22})
            self.assertIsNone(manifest['reference_address_bytes_equal'])
            self.assertEqual(manifest['program_bytes'], 3)


if __name__ == '__main__':
    unittest.main()
