"""Saved-drawing diagnostics must distinguish real nodes from visual contacts."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from proteus86 import Circuit, UnsupportedFormat, mm, wire_quality
from proteus86.quality import _analyze


def snapshot(*paths, nodes=()):
    return dict(wires=[dict(offset=i+1,points=[(mm(x),mm(y)) for x,y in path]) for i,path in enumerate(paths)],
                junctions=[dict(position=(mm(x),mm(y)),wires=refs) for x,y,refs in nodes])


def analyze(data,gap=2.54,run=5.08):
    return _analyze(data,mm(gap),mm(run))


class WireQualityTests(unittest.TestCase):
    def test_long_overlap_is_not_hidden_by_a_junction_or_same_coordinate(self):
        data=snapshot([(0,0),(20,0)],[(10,0),(30,0)],nodes=[(10,0,[1,2])])
        report=analyze(data)
        self.assertFalse(report['passed'])
        self.assertEqual(report['overlaps'],[dict(wires=[0,1],overlap_mm=10.0)])

    def test_gap_boundary_and_short_projected_parallel_run(self):
        a=[(0,0),(20,0)]
        self.assertTrue(analyze(snapshot(a,[(0,2.54),(20,2.54)]))['passed'])
        report=analyze(snapshot(a,[(0,2.53),(20,2.53)]))
        self.assertFalse(report['passed']);self.assertEqual(report['near_parallel'][0]['gap_mm'],2.53)
        self.assertTrue(analyze(snapshot(a,[(19,1),(30,1)]))['passed'])
        self.assertFalse(analyze(snapshot(a,[(19,1),(30,1)]),run=1)['passed'])

    def test_only_referenced_wires_meeting_at_real_node_are_exempt(self):
        paths=([(-10,0),(0,0)],[(0,0),(0,10)],[(0,0),(10,0)])
        good=snapshot(*paths,nodes=[(0,0,[1,2,3])])
        self.assertTrue(analyze(good)['passed'])
        incomplete=snapshot(*paths,nodes=[(0,0,[1,2])])
        result=analyze(incomplete)
        self.assertFalse(result['passed'])
        self.assertEqual(len(result['crossings']),2)
        self.assertTrue(all(2 in issue['wires'] for issue in result['crossings']))

    def test_non_node_crossing_t_contact_and_collinear_touch_are_visible(self):
        for other in ([(-5,0),(5,0)],[(-5,0),(0,0)]):
            with self.subTest(other=other):
                result=analyze(snapshot([(0,-10),(0,10)],other))
                self.assertEqual(len(result['crossings']),1)
                self.assertFalse(result['passed'])
        result=analyze(snapshot([(-10,0),(0,0)],[(0,0),(10,0)]))
        self.assertFalse(result['passed']);self.assertEqual(len(result['crossings']),1)

    def test_redundant_vertices_and_nonadjacent_self_crossing(self):
        result=analyze(snapshot([(0,0),(10,0),(20,0)]))
        self.assertEqual(result['straight_wires'],1);self.assertEqual(result['bends'],0)
        loop=analyze(snapshot([(0,0),(20,0),(20,20),(10,20),(10,-10)]))
        self.assertFalse(loop['passed']);self.assertEqual(len(loop['crossings']),1)

    def test_minimum_gap_keeps_distant_parallel_runs_and_excludes_short_projection(self):
        paths = ([(100,0),(0,0)], [(25,7.62),(75,7.62)], [(0,2.54),(4,2.54)],
                 [(200,10),(200,-10)], [(207.62,10),(207.62,-10)])
        report = analyze(snapshot(*paths))
        self.assertTrue(report['passed'])
        self.assertEqual(report['minimum_measured_parallel_gap_mm'], 7.62)
        self.assertEqual(report['wire_length_mm'], 194)
        near = analyze(snapshot(*paths), gap=8)
        self.assertEqual([item['wires'] for item in near['near_parallel']], [[0,1],[3,4]])
        swapped = [[(y,x) for x,y in path] for path in paths]
        self.assertEqual(analyze(snapshot(*swapped), gap=8), near)

    def test_bend_contact_is_reported_once_and_cannot_be_exempted_as_endpoint(self):
        paths = ([(-10,0),(0,0),(0,10)], [(10,0),(0,0)])
        for nodes in ((), [(0,0,[1,2])]):
            with self.subTest(nodes=nodes):
                report = analyze(snapshot(*paths, nodes=nodes))
                self.assertFalse(report['passed'])
                self.assertEqual(report['crossings'], [dict(wires=[0,1],position_mm=[0,0])])
                self.assertEqual(report['overlaps'], [])

    def test_public_audit_and_cli_are_read_only_and_report_gap_failures(self):
        c=Circuit()
        with c.batch():
            for ref,x,y in [('R1',0,0),('R2',50.8,0),('R3',0,15.24),('R4',50.8,15.24)]:
                c.add_mm('RESISTOR',ref,'1k',x,y)
            c.connect('R1.2','R2.1');c.connect('R3.2','R4.1')
        with tempfile.TemporaryDirectory() as temporary:
            path=c.save(Path(temporary)/'spacing.pdsprj')
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertTrue(wire_quality(path)['passed'])
            self.assertFalse(wire_quality(path,min_gap_mm=20.32)['passed'])
            from proteus86.__main__ import main
            for options,code in (([],0),(['--min-gap','20.32'],1)):
                stream=io.StringIO()
                with patch('sys.argv',['proteus86','wire-quality',str(path),*options]),contextlib.redirect_stdout(stream):
                    self.assertEqual(main(),code)
                self.assertEqual(json.loads(stream.getvalue())['passed'],code==0)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest)

    def test_invalid_parameters_and_unsupported_format_are_not_bypassed(self):
        for value in (0,-1,True,float('nan'),float('inf')):
            with self.subTest(value=value),self.assertRaises(ValueError):
                wire_quality('unused.pdsprj',min_gap_mm=value)
        with patch.object(Circuit,'open',side_effect=UnsupportedFormat('Unknown objects')),patch(
                'proteus86._codec.net_objects.decode_net_objects',side_effect=AssertionError('Guard bypassed')):
            with self.assertRaisesRegex(UnsupportedFormat,'Unknown objects'):
                wire_quality('unknown.pdsprj')


if __name__=='__main__':
    unittest.main()
