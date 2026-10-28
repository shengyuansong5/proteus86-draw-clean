import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from proteus86 import Circuit,firmware_info,prepare_run
from proteus86.installation import ROOT
from proteus86.simulation import Simulation,seconds,classify_diagnostics


def hex_line(address,kind,payload):
    raw=bytes([len(payload)])+address.to_bytes(2,'big')+bytes([kind])+bytes(payload)
    return ':'+(raw+bytes([-sum(raw)&255])).hex().upper()+'\n'


class SimulationFileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.directory=Path(self.temp.name)

    def tearDown(self):self.temp.cleanup()

    def test_checked_firmware_is_the_real_39_byte_fixture(self):
        info=firmware_info(ROOT/'examples/blink8051.hex')
        self.assertEqual(info['program_bytes'],39)
        self.assertEqual((info['address_min'],info['address_max']),(0,38))

    def test_hex_extended_addresses_are_resolved_and_overlap_rejected(self):
        path=self.directory/'extended.hex'
        path.write_text(hex_line(0,4,[0,1])+hex_line(0x10,0,[0x80,0xfe])+hex_line(0,1,[]))
        info=firmware_info(path)
        self.assertEqual((info['address_min'],info['address_max']),(0x10010,0x10011))
        path.write_text(hex_line(0,0,[1,2])+hex_line(1,0,[3])+hex_line(0,1,[]))
        with self.assertRaises(ValueError):firmware_info(path)

    def test_corrupt_truncated_or_trailing_firmware_is_refused(self):
        for i,text in enumerate((':0200000080FE81\n:00000001FF\n',
                                 ':0200000080FE80\n',':00000001FF\n:0200000080FE80\n')):
            path=self.directory/(str(i)+'.hex');path.write_text(text)
            with self.assertRaises(ValueError):firmware_info(path)

    def test_run_bundle_preserves_source_and_topology_without_launching(self):
        c=Circuit()
        with c.batch():
            c.add_mm('AT89C52','U1','AT89C52',0,0)
            c.set_properties('U1',PROGRAM='missing.hex',CLOCK='12MHz')
        source=c.save(self.directory/'source.pdsprj');before=source.read_bytes()
        destination=self.directory/'bundle'
        with patch('subprocess.Popen',side_effect=AssertionError('Preflight launched Proteus')):
            bundle=prepare_run(source,destination,firmware={'U1':ROOT/'examples/blink8051.hex'})
        output=Circuit.open(bundle['project'])
        self.assertEqual(output.nets(),Circuit.open(source).nets())
        properties=output.components()[0]['properties']
        self.assertEqual(properties['PROGRAM'],str(Path('firmware/U1.hex')))
        self.assertEqual(properties['CLOCK'],'12MHz')
        self.assertEqual(source.read_bytes(),before)
        self.assertEqual(hashlib.sha256((destination/'firmware/U1.hex').read_bytes()).hexdigest(),bundle['firmware']['U1']['sha256'])
        with self.assertRaises(FileExistsError):prepare_run(source,destination)
        self.assertEqual(source.read_bytes(),before)

    def test_missing_firmware_fails_before_output_or_process(self):
        c=Circuit()
        with c.batch():
            c.add_mm('AT89C52','U1','AT89C52',0,0)
            c.set_properties('U1',PROGRAM='missing.hex')
        source=c.save(self.directory/'missing.pdsprj')
        with patch('subprocess.Popen',side_effect=AssertionError('Preflight launched Proteus')):
            with self.assertRaises(FileNotFoundError):prepare_run(source,self.directory/'absent')
        self.assertFalse((self.directory/'absent').exists())

    def test_invalid_duration_does_not_send_a_native_command(self):
        sim=Simulation.__new__(Simulation);sim._command=Mock();sim.status=Mock()
        for duration in (0,-1,float('nan'),float('inf'),0.0000001):
            with self.assertRaises(ValueError):sim.run_for(duration)
        with self.assertRaises(ValueError):sim.run_for(1,timeout=0)
        sim._command.assert_not_called();sim.status.assert_not_called()

    def test_native_time_and_diagnostics_do_not_invent_success(self):
        self.assertEqual(seconds('01:02:03.250000'),3723.25)
        self.assertEqual(seconds('0.250000000s'),.25)
        for clock in ('1 second','00:60:00','00:00:60'):
            with self.assertRaises(ValueError):seconds(clock)
        normal={'text':'Read total of 39 bytes','image':0}
        warning={'text':'Model warning','image':1}
        error={'text':'Error Variable not found parsing property vt','image':1}
        self.assertTrue(classify_diagnostics([normal,warning])['passed'])
        report=classify_diagnostics([normal,warning,error])
        self.assertFalse(report['passed']);self.assertEqual(report['errors'],[error])
        self.assertEqual(report['warnings'],[warning])
        self.assertTrue(classify_diagnostics([{'text':"Loaded netlist 'file' for design 'Error monitor'",'image':0}])['passed'])
        self.assertTrue(classify_diagnostics([{'text':'ordinary note','image':2}])['passed'])

    def test_unknown_native_binary_is_rejected_before_memory_access(self):
        from proteus86.native_simulation import StatusReader,native
        executable=self.directory/'PDS.EXE';executable.write_bytes(b'not an executable')
        (self.directory/'WINCORE.DLL').write_bytes(b'unknown build')
        session=Mock();session.process.args=[str(executable)]
        with patch.object(native.k,'OpenProcess') as opening:
            with self.assertRaises(NotImplementedError):StatusReader(session)
        opening.assert_not_called()
