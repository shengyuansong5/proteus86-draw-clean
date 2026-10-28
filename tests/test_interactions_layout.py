import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import threading
import time
from unittest.mock import Mock,patch

from proteus86 import Circuit,Scenario,evaluate_samples,from_design
from proteus86.scenarios import timeline
from proteus86.simulation import clock_resolution,reached_target
from proteus86.interactions import observe,set_control,snapshot
from proteus86.inspection import netcheck
from proteus86.installation import ROOT


def native_data(state='0',probe='0'):
    return dict(backend='proteus_native_sdf',simulation_seconds=.125,time_resolution_seconds=1e-9,parts={
        'B1':dict(device='BUTTON',properties=dict(STATE=state,INC='0',DEC='1')),
        'P1':dict(device='LOGICPROBE',properties=dict(STATE=probe))})


def fake_sim(data):
    return SimpleNamespace(status=Mock(return_value=dict(state='paused',simulation_seconds=.125)),
        session=SimpleNamespace(pid=123,_wait=Mock(return_value={'hwnd':456}),_ready=Mock(),netlist=Mock()),
        _initial_bindings={r:{key:p['properties'].get(key) for key in ('INC','DEC','KEY')} for r,p in data['parts'].items()})


class InteractionsLayoutTests(unittest.TestCase):
    def test_clock_display_precision_does_not_cause_false_timeouts_or_hide_overshoot(self):
        self.assertEqual(clock_resolution('00:00:01.115819'),1e-6)
        self.assertEqual(clock_resolution('0.015819200s'),1e-9)
        rounded=dict(simulation_seconds=1.115819,time_resolution_seconds=1e-6)
        self.assertTrue(reached_target(rounded,1.1158192,0))
        self.assertFalse(reached_target(rounded,1.11582,0))
        self.assertFalse(reached_target(rounded,1.11,.003))
        self.assertFalse(reached_target(dict(simulation_seconds=None),0,.003))

    def test_stimuli_are_explicit_and_conflicts_or_unachievable_tolerance_fail(self):
        scene=Scenario().bounce('B1',at=.02,intervals=[.01]*4).hold('B1',at=.2,seconds=.1)
        frames=timeline(scene,.4,.01,tolerance=.003)
        events=[a for frame in frames for a in frame['actions']]
        self.assertEqual([a['state'] for a in events],[1,0,1,0,1,1,0])
        self.assertEqual(events[-1]['at'],.3)
        with self.assertRaises(ValueError):timeline(scene,.4,.001,tolerance=.003)
        with self.assertRaises(ValueError):timeline(Scenario().press('B1',at=.1).release('B1',at=.1),.2,.02,tolerance=0)
        for bad in (-1,float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):Scenario().press('B1',at=bad)
        with self.assertRaises(ValueError):Scenario().bounce('B1',at=0,intervals=[.001])

    def test_native_dispatch_requires_exclusive_bindings_and_actual_readback(self):
        data=native_data();sim=fake_sim(data)
        with patch('proteus86.interactions.snapshot',side_effect=[data,native_data('1')]),patch('proteus86.native_simulation.message') as send:
            result=set_control(sim,'B1',1)
        self.assertTrue(result['changed']);self.assertEqual(result['command_time_seconds'],.125)
        send.assert_called_once_with(123,456,0x111,3)
        with patch('proteus86.interactions.snapshot',return_value=data),patch('proteus86.native_simulation.message') as send:
            with self.assertRaisesRegex(RuntimeError,'read-back'):set_control(sim,'B1',1)
        send.assert_called_once()
        data['parts']['P1']['properties']['KEY']='0';sim=fake_sim(data)
        with patch('proteus86.interactions.snapshot',return_value=data),patch('proteus86.native_simulation.message') as send:
            with self.assertRaisesRegex(RuntimeError,'collision'):set_control(sim,'B1',1)
        send.assert_not_called()

    def test_repeated_press_is_idempotent_and_binding_changes_refuse_dispatch(self):
        data=native_data('1');sim=fake_sim(data)
        with patch('proteus86.interactions.snapshot',return_value=data),patch('proteus86.native_simulation.message') as send:
            self.assertFalse(set_control(sim,'B1',1)['changed'])
        send.assert_not_called()
        data['parts']['B1']['properties']['INC']='2'
        with patch('proteus86.interactions.snapshot',return_value=data),patch('proteus86.native_simulation.message') as send:
            with self.assertRaisesRegex(RuntimeError,'changed after opening'):set_control(sim,'B1',0)
        send.assert_not_called()

    def test_unknown_probe_or_changed_native_time_is_not_accepted_as_measurement(self):
        for raw in (None,'X','2'):
            data=native_data(probe=raw);sim=fake_sim(data)
            with patch('proteus86.interactions.snapshot',return_value=data):
                with self.assertRaisesRegex(RuntimeError,'unknown/nonbinary'):observe(sim,['P1'])
        sim=fake_sim(native_data());sim.session.netlist.return_value={'parts':native_data()['parts']}
        sim.status.side_effect=[dict(state='paused',simulation_seconds=.125),dict(state='paused',simulation_seconds=.126)]
        with self.assertRaisesRegex(RuntimeError,'time changed'):snapshot(sim)

    def test_sequence_counts_only_observed_native_samples_and_detects_extra_responses(self):
        samples=[{'probes':{'P0':value,'P1':1}} for value in (1,1,0,0,1)]
        result=evaluate_samples(samples,['P0','P1'],expected_sequences={'P0':[1,0,1]},expected_changes={'P0':2},expected_words=['11','01','11'])
        self.assertTrue(result['passed']);self.assertEqual(result['observed_counts']['P0']['rising'],1)
        self.assertEqual(result['coverage'],'sampled_states_only')
        samples.append({'probes':{'P0':0,'P1':1}})
        self.assertFalse(evaluate_samples(samples,['P0','P1'],expected_changes={'P0':2})['passed'])
        self.assertFalse(evaluate_samples([],['P0'])['passed'])
        with self.assertRaises(ValueError):evaluate_samples(samples,['P0'],expected_changes={'TYPO':2})

    def test_module_grid_moves_rows_but_preserves_saved_connectivity(self):
        text=(ROOT/'proteus86/examples/parallel.txt').read_text()
        c=from_design(text);before=c.nets()
        with tempfile.TemporaryDirectory() as temp:
            source=c.save(Path(temp)/'before.pdsprj');original=source.read_bytes()
            c.arrange_modules({'outputs':dict(rows=[['R1'],['R2']],origin_mm=[25.4,20.32],pitch_mm=[20.32,20.32])})
            self.assertEqual(c.nets(),before)
            parts={p['ref']:p['position'] for p in c.components()}
            self.assertEqual(parts['R1']['x'],parts['R2']['x'])
            self.assertEqual(parts['R1']['y']-parts['R2']['y'],2032000)
            saved=c.save(Path(temp)/'after.pdsprj')
            self.assertEqual(source.read_bytes(),original)
            self.assertTrue(netcheck(saved,[['R1.1','R2.1','VCC'],['R1.2','R2.2','GND']])['passed'])
            self.assertEqual(Circuit.open(saved).nets(),before)

    def test_invalid_module_plans_are_rejected_without_moving_any_component(self):
        c=from_design((ROOT/'proteus86/examples/parallel.txt').read_text());before=c.components()
        for rows in ([['R1'],['R1']],[['R1'],['UNKNOWN']]):
            with self.assertRaises(ValueError):c.arrange_modules({'bad':dict(rows=rows,origin_mm=[0,0])})
            self.assertEqual(c.components(),before)

    def test_native_save_waits_for_complete_zip_after_early_menu_acknowledgment(self):
        from proteus86.session import Session,_archive_digest
        from proteus86._codec.proteus_session import Session as NativeSession
        with tempfile.TemporaryDirectory() as temp:
            project=Circuit().save(Path(temp)/'private.pdsprj');data=project.read_bytes()
            session=Session.__new__(Session);session.project=project;session.pid=123
            session.process=Mock();session.process.poll.return_value=None
            session._ready=Mock(return_value={'hwnd':1});finished=threading.Event();workers=[]
            def native_save(_):
                project.write_bytes(data[:40])  # Modified timestamp/menu are already visible.
                def close_zip():
                    time.sleep(.06);project.write_bytes(data);finished.set()
                worker=threading.Thread(target=close_zip);workers.append(worker);worker.start()
                return project
            with patch.object(NativeSession,'save',native_save):
                saved=session.save()
                self.assertTrue(finished.is_set())
                self.assertEqual(saved,project);self.assertEqual(_archive_digest(project),_archive_digest(session.last_backup))
            for worker in workers:worker.join()
