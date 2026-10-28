"""Topology/model acceptance for the explicit 8051 visual example profile."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from proteus86 import Circuit,from_design,wiringcheck,wire_quality
from proteus86.inspection import netcheck
from proteus86._codec.net_objects import decode_net_objects
from proteus86.routing import clean
from examples.draw_8051_neat import arrange,topology,ROOT


def wire_geometry(path):
    return sorted(min(tuple(clean(w['points'])),tuple(clean(w['points']))[::-1])
                  for w in decode_net_objects(path)['wires'])


class NeatExampleTests(unittest.TestCase):
    def test_ordered_rows_preserve_nets_models_and_source(self):
        circuit=from_design((ROOT/'proteus86/examples/mcu_complex.txt').read_text(encoding='utf-8'))
        models=lambda c:{p['ref']:(p['device'],p['value'],p['properties']) for p in c.components()}
        before,nets=models(circuit),topology(circuit)
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);source=circuit.save(directory/'before.pdsprj')
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            arrange(circuit);circuit.fit_sheet();after=circuit.save(directory/'after.pdsprj')
            reopened=Circuit.open(after)
            self.assertEqual(topology(reopened),nets);self.assertEqual(models(reopened),before)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),digest)
            self.assertTrue(netcheck(after,[g for g in nets if len(g)>1])['passed'])
            self.assertFalse(wiringcheck(after)['warnings'])
            quality=wire_quality(after,min_parallel_mm=0.00001)
            self.assertTrue(quality['passed'],quality)
            self.assertFalse(quality['overlaps'])
            self.assertFalse(quality['crossings'])
            self.assertFalse(quality['near_parallel'])
            self.assertGreaterEqual(quality['minimum_measured_parallel_gap_mm'],2.54)
            decoded=decode_net_objects(after)
            ground_wire=next(wire for wire in decoded['wires'] if ('RR1','1') in wire['pin_references'])
            self.assertEqual(len(clean(ground_wire['points'])),2)
            power_wire=next(wire for wire in decoded['wires'] if ('CR1','2') in wire['pin_references'])
            self.assertEqual(len(clean(power_wire['points'])),2)
            parts={p['ref']:p['position'] for p in reopened.components()}
            for i in range(1,9):
                self.assertEqual(parts['D'+str(i)]['y'],parts['R'+str(i)]['y'])
                self.assertEqual(parts['D'+str(i)]['x'],parts['D1']['x'])
                if i>1:self.assertEqual(parts['D'+str(i-1)]['y']-parts['D'+str(i)]['y'],1016000)
                lane=next(pin['position'][0] for pin in reopened.pins('U1') if pin['number']==str(i))-5588000+(i-1)*762000
                request=next(item for item in reopened._connections if {item['first'],item['second']}==
                             {('R'+str(i),'2'),reopened._endpoint(('U1',str(i)))})
                self.assertEqual({point[0] for point in request['points'][1:-1]},{lane})

    def test_reapplying_profile_does_not_drift_devices_or_routes(self):
        circuit=from_design((ROOT/'proteus86/examples/mcu_complex.txt').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            arrange(circuit);circuit.fit_sheet();first=circuit.save(directory/'first.pdsprj')
            parts,nets=circuit.components(),circuit.nets()
            arrange(circuit);circuit.fit_sheet();second=circuit.save(directory/'second.pdsprj')
            self.assertEqual(circuit.components(),parts)
            self.assertEqual(circuit.nets(),nets)
            self.assertEqual(wire_geometry(first),wire_geometry(second))

    def test_wrong_profile_is_rejected_before_any_edit(self):
        circuit=Circuit();before=circuit.components()
        with self.assertRaisesRegex(ValueError,'25-part'):arrange(circuit)
        self.assertEqual(circuit.components(),before)
