"""Only the exact independently observed native entity extension is writable."""
import hashlib
import os
from pathlib import Path
import struct
import tempfile
import unittest
from zipfile import ZipFile

from proteus86 import Circuit, UnsupportedFormat
from proteus86._codec.component_codec import _entities
from proteus86._codec.proteus_project import _cdb_entity_table_offset, _lp
from proteus86.inspection import netcheck


def with_extension(source, target, extension):
    with ZipFile(source) as archive:
        members = {info.filename: archive.read(info.filename) for info in archive.infolist()}
    data = members['ROOT.CDB']
    pos = _cdb_entity_table_offset(data) + 4 + 16
    _, _, pos = _lp(data, pos)
    count = struct.unpack_from('<I', data, pos)[0]
    pos += 4
    for _ in range(count):
        _, _, pos = _lp(data, pos)
        _, _, pos = _lp(data, pos)
    assert struct.unpack_from('<I', data, pos)[0] == 0
    members['ROOT.CDB'] = data[:pos] + struct.pack('<I', len(extension)) + extension + data[pos + 4:]
    with ZipFile(target, 'x') as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)


class NativeEntityExtensionTests(unittest.TestCase):
    def test_observed_zero_block_roundtrips_without_changing_topology_or_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            c = Circuit()
            c.add_mm('AT89C51RD2', 'U1', 'AT89C51RD2', 0, 0)
            source = c.save(root / 'ordinary.pdsprj')
            native = root / 'observed.pdsprj'
            with_extension(source, native, bytes(2048))
            original = native.read_bytes()
            reopened = Circuit.open(native)
            self.assertEqual(reopened.nets(), Circuit.open(source).nets())
            saved = reopened.save(root / 'retained.pdsprj')
            self.assertEqual(native.read_bytes(), original)
            with ZipFile(saved) as archive:
                records, _ = _entities(archive.read('ROOT.CDB'))
            self.assertEqual(records['U1']['extension'], bytes(2048))
            self.assertEqual(Circuit.open(saved).nets(), reopened.nets())

    def test_unknown_size_nonzero_payload_and_unverified_device_still_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for device, payload in [('AT89C51RD2', bytes(1024)),
                                    ('AT89C51RD2', bytes(2047) + b'\x01'),
                                    ('AT89C52', bytes(2048))]:
                with self.subTest(device=device, size=len(payload), nonzero=any(payload)):
                    c = Circuit()
                    c.add_mm(device, 'U1', device, 0, 0)
                    original = c.save(root / (device + str(len(payload)) + str(any(payload)) + '.pdsprj'))
                    target = root / ('bad-' + original.name)
                    with_extension(original, target, payload)
                    before = hashlib.sha256(target.read_bytes()).digest()
                    with self.assertRaises(UnsupportedFormat):
                        Circuit.open(target)
                    self.assertEqual(hashlib.sha256(target.read_bytes()).digest(), before)

    def test_actual_private_native32_fixture_when_explicitly_configured(self):
        fixture = os.environ.get('PROTEUS86_NATIVE32_FIXTURE')
        if not fixture:
            self.skipTest('Optional private native-save reproduction is not distributed')
        root = Path(fixture)
        before = Circuit.open(root / 'before.pdsprj')
        after = Circuit.open(root / 'capture02-counter/after.pdsprj')
        self.assertEqual(len(after.components()), 32)
        expected = [net for net in before.nets() if len(net) > 1]
        self.assertTrue(netcheck(root / 'capture02-counter/after.pdsprj', expected)['passed'])
        from proteus86.session import parse_sdf
        from proteus86.verification import verify_netlist
        self.assertTrue(verify_netlist(after, parse_sdf((root / 'capture02-counter-reopened.SDF').read_text(encoding='utf-8')))['passed'])


if __name__ == '__main__':
    unittest.main()
