import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from proteus86 import Circuit, Project, UnsupportedFormat, from_spec, mm
from proteus86.installation import ROOT


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Native86Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def circuit(self, name="rc"):
        return from_spec(json.loads((ROOT / "proteus86/examples" / (name + ".json")).read_text(encoding="utf-8")))

    def test_three_examples_roundtrip_with_complete_connectivity(self):
        for name in ("rc", "led", "mcu"):
            with self.subTest(name=name):
                circuit = self.circuit(name)
                path = circuit.save(self.directory / (name + ".pdsprj"))
                reopened = Circuit.open(path)
                self.assertEqual(reopened.components(), circuit.components())
                self.assertEqual({frozenset(net) for net in reopened.nets()}, {frozenset(net) for net in circuit.nets()})
                second = reopened.save(self.directory / (name + "_again.pdsprj"))
                self.assertEqual(Circuit.open(second).components(), reopened.components())
                with ZipFile(path) as archive:
                    self.assertEqual(struct.unpack_from("<I", archive.read("ROOT.CDB"))[0], 5)
                    self.assertIsNone(archive.testzip())

    def test_mcu_package_numbers_and_logical_pin_names_with_dots(self):
        circuit = self.circuit("mcu")
        pins = {pin["name"]: pin["number"] for pin in circuit.pins("U1")}
        self.assertEqual(pins["VCC"], "40")
        self.assertEqual(pins["GND"], "20")
        self.assertEqual(pins["P1.0/T2"], "1")
        self.assertEqual(circuit._endpoint("U1.P1.0/T2"), circuit._endpoint("U1.1"))

    def test_edit_reroutes_and_preserves_electrical_nets(self):
        circuit = self.circuit()
        path = circuit.save(self.directory / "original.pdsprj")
        edited = Circuit.open(path)
        nets_before = {frozenset(net) for net in edited.nets()}
        edited.update("R1", value="22k")
        edited.move_mm("C1", 38.1, -12.7)
        result = edited.save(self.directory / "edited.pdsprj")
        reopened = Circuit.open(result)
        self.assertEqual(nets_before, {frozenset(net) for net in reopened.nets()})
        parts = {part["ref"]: part for part in reopened.components()}
        self.assertEqual(parts["R1"]["value"], "22k")
        self.assertEqual(parts["C1"]["position"], {"x": mm(38.1), "y": mm(-12.7)})

    def test_overwrite_requires_opt_in_and_verified_recoverable_backup(self):
        circuit = self.circuit()
        path = circuit.save(self.directory / "existing.pdsprj")
        before = digest(path)
        circuit.update("R1", value="33k")
        with self.assertRaises(UnsupportedFormat):
            circuit.save(path)
        self.assertEqual(before, digest(path))
        circuit.save(path, overwrite=True)
        self.assertEqual(before, digest(circuit.last_backup))
        self.assertNotEqual(before, digest(path))

    def test_concurrent_external_change_is_preserved(self):
        path = self.circuit().save(self.directory / "concurrent.pdsprj")
        stale = Circuit.open(path)
        fresh = Circuit.open(path)
        fresh.update("R1", value="47k")
        fresh.save(path, overwrite=True)
        latest = digest(path)
        with self.assertRaises(ValueError):
            stale.save(path, overwrite=True)
        self.assertEqual(latest, digest(path))

    def test_unknown_format_and_unknown_spec_fields_fail_closed(self):
        source = self.circuit().save(self.directory / "known.pdsprj")
        bad = self.directory / "unsupported.pdsprj"
        with ZipFile(source) as src, ZipFile(bad, "w") as dest:
            for name in src.namelist():
                data = src.read(name)
                if name == "ROOT.CDB":
                    data = struct.pack("<I", 7) + data[4:]
                dest.writestr(name, data)
        with self.assertRaises(UnsupportedFormat):
            Circuit.open(bad)
        with self.assertRaises(ValueError):
            from_spec({"componentz": []})

    def test_invalid_pin_and_duplicate_component_do_not_mutate(self):
        circuit = self.circuit()
        before = circuit.summary()
        with self.assertRaises(UnsupportedFormat):
            circuit.connect("R1.99", "C1.1")
        with self.assertRaises(UnsupportedFormat):
            circuit.add_mm("RESISTOR", "R1", "1k", 0, 0)
        self.assertEqual(before, circuit.summary())

    def test_empty_sheet_can_reopen_and_import_devices(self):
        empty = Circuit().save(self.directory / "empty.pdsprj")
        reopened = Circuit.open(empty)
        reopened.add_mm("RESISTOR", "R1", "1k", 0, 0)
        saved = reopened.save(self.directory / "one.pdsprj")
        self.assertEqual(len(Project(saved).components()), 1)


if __name__ == "__main__":
    unittest.main()
