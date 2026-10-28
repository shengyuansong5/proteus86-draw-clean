import hashlib
import json
import tempfile
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from proteus86 import Circuit, from_spec, from_design, route_file, parse_design
from proteus86.design import format_layout
from proteus86.inspection import netcheck
from proteus86.preview import svg
from proteus86.netlist import protel_to_design
from proteus86.repair import check_pin_order, fix_pin_order, _pin_tables
from proteus86._codec.proteus_project import Project
from proteus86._codec.component_codec import _short
from zipfile import ZipFile
from proteus86.installation import ROOT


class PipelineTests(unittest.TestCase):
    def test_cli_routes_real_saved_file_and_pin_repair_accepts_only_its_own_options(self):
        text = (ROOT / 'proteus86/examples/parallel.txt').read_text()
        with tempfile.TemporaryDirectory() as directory:
            source = from_design(text, route=False).save(Path(directory) / 'placed.pdsprj')
            target = Path(directory) / 'routed.pdsprj'
            result = subprocess.run([sys.executable, '-m', 'proteus86', 'route', str(source), '-o', str(target),
                                     '--net', 'R1.1,R2.1,VCC', '--net', 'R1.2,R2.2,GND'],
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(netcheck(target, parse_design(text)['nets'])['passed'])
            fixed = Path(directory) / 'checked.pdsprj'
            result = subprocess.run([sys.executable, '-m', 'proteus86', 'fix-pins', str(target), '-o', str(fixed)],
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(check_pin_order(fixed)['passed'])

    def test_complete_saved_file_pipeline_never_launches_an_application(self):
        text=(ROOT/'proteus86/examples/parallel.txt').read_text()
        with tempfile.TemporaryDirectory() as directory, patch('subprocess.Popen',side_effect=AssertionError('GUI process launched')):
            placed=from_design(text,route=False)
            before=placed.components()
            source=placed.save(Path(directory)/'placed.pdsprj')
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            result=route_file(source,Path(directory)/'routed.pdsprj',parse_design(text)['nets'])
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),digest)
            self.assertEqual(Circuit.open(result).components(),before)
            self.assertTrue(netcheck(result,parse_design(text)['nets'])['passed'])
            preview=ET.fromstring(svg(result))
            self.assertEqual(preview.tag,'{http://www.w3.org/2000/svg}svg')

    def test_hub_layout_aligns_peripherals_and_roundtrips_layout_text(self):
        text=(ROOT/'proteus86/examples/mcu_auto.txt').read_text()
        circuit=from_design(text)
        parts={part['ref']:part for part in circuit.components()}
        self.assertLess(parts['D1']['position']['x'],parts['R1']['position']['x'])
        self.assertLess(parts['R1']['position']['x'],parts['U1']['position']['x'])
        layout=format_layout(circuit,parse_design(text))
        again=from_design(layout)
        self.assertEqual(circuit.components(),again.components())
        self.assertEqual(circuit.nets(),again.nets())

    def test_coordinate_free_json_can_autoplace_and_connect_multinode_nets(self):
        spec={'components':[{'device':'CAPACITOR','ref':'C'+str(i),'value':'1u'} for i in range(1,5)],
              'nets':[[f'C{i}.1' for i in range(1,5)],[f'C{i}.2' for i in range(1,5)]]}
        circuit=from_spec(spec)
        self.assertEqual(sorted(map(len,circuit.nets())),[4,4])
        self.assertEqual(len({tuple(part['position'].values()) for part in circuit.components()}),4)

    def test_netcheck_detects_missing_join_and_unexpected_short(self):
        text=(ROOT/'proteus86/examples/parallel.txt').read_text()
        with tempfile.TemporaryDirectory() as directory:
            placed=from_design(text,route=False).save(Path(directory)/'unrouted.pdsprj')
            self.assertFalse(netcheck(placed,parse_design(text)['nets'])['passed'])
            c=from_design(text)
            c.connect('R1.1','R1.2')
            bad=c.save(Path(directory)/'short.pdsprj')
            self.assertFalse(netcheck(bad,parse_design(text)['nets'])['passed'])

    def test_legacy_crystal_pin_swap_declaration_preserves_real_mapping(self):
        c=Circuit()
        c.import_device('CRYSTAL',library='DEVICE')
        c.add_mm('CRYSTAL','X1','12MHz',0,0)
        self.assertEqual({pin['number'] for pin in c.pins('X1')},{'1','2'})

    def test_layout_retains_explicit_library_for_ambiguous_device(self):
        design = parse_design('[parts]\nX1 CRYSTAL 12MHz library=DEVICE\n')
        circuit = from_design(design)
        layout = format_layout(circuit, design)
        again = from_design(layout)
        self.assertEqual(circuit.components(), again.components())
        self.assertEqual(parse_design(layout)['parts'][0]['library'], 'DEVICE')

    def test_protel_conversion_can_be_consumed_by_the_actual_generator(self):
        text='PROTEL NETLIST 2.0\n[\nDESIGNATOR\nR1\nFOOTPRINT\nRES\nPARTTYPE\n10k\n]\n[\nDESIGNATOR\nR2\nFOOTPRINT\nRES\nPARTTYPE\n10k\n]\n(\nVCC\nR1-1 RES-1 Passive\nR2-1 RES-1 Passive\n)\n(\nGND\nR1-2 RES-2 Passive\nR2-2 RES-2 Passive\n)\n'
        result=protel_to_design(text,device_field='FOOTPRINT')
        c=from_design(result)
        self.assertEqual(sorted(map(len,c.nets())),[2,2])
        self.assertEqual([part['value'] for part in c.components()],['10k','10k'])

    def test_pin_order_repair_changes_only_the_cdb_and_restores_exact_members(self):
        with tempfile.TemporaryDirectory() as directory:
            c=from_design((ROOT/'proteus86/examples/parallel.txt').read_text())
            source=c.save(Path(directory)/'correct.pdsprj')
            broken=Project(source)
            ref,left,right,pins=next(_pin_tables(broken))
            broken._cdb[left:right]=b''.join(_short(name)+_short(number) for name,number in reversed(pins))
            bad=broken.save(Path(directory)/'bad_order.pdsprj')
            self.assertFalse(check_pin_order(bad)['passed'])
            fixed=Path(directory)/'fixed.pdsprj'
            result=fix_pin_order(bad,fixed)
            self.assertEqual(result['repaired_components'],[ref])
            self.assertTrue(check_pin_order(fixed)['passed'])
            with ZipFile(source) as a,ZipFile(fixed) as b:
                self.assertEqual({name:a.read(name) for name in a.namelist()},{name:b.read(name) for name in b.namelist()})
