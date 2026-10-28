"""Offline failure/dispatch regressions; native evidence is collected separately."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from proteus86 import Scenario
from proteus86.interactions import interact
from proteus86.scenario_runner import run_scenario, _write_report


def data(states=(0, 0), probes=(0, 0), at=.2):
    parts = {}
    for i in range(2):
        parts['S' + str(i + 1)] = dict(device='LOGICSTATE', properties={
            'STATE': str(states[i]), 'INC': str(i * 2), 'DEC': str(i * 2 + 1)})
        parts['P' + str(i + 1)] = dict(device='LOGICPROBE', properties={'STATE': str(probes[i])})
    return dict(backend='proteus_native_sdf', simulation_seconds=at,
                time_resolution_seconds=1e-9, parts=parts)


def io_sim(initial):
    return SimpleNamespace(status=Mock(return_value=dict(state='paused', simulation_seconds=.2)),
                           session=SimpleNamespace(pid=123, _wait=Mock(return_value={'hwnd': 456}), _ready=Mock()),
                           _initial_bindings={ref: {key: part['properties'].get(key) for key in ('INC', 'DEC', 'KEY')}
                                              for ref, part in initial['parts'].items()})


class BatchReadbackTests(unittest.TestCase):
    def test_two_inputs_and_probes_share_two_fresh_exports(self):
        before, after = data(), data((1, 1), (1, 1))
        sim = io_sim(before)
        with patch('proteus86.interactions.snapshot', side_effect=[before, after]) as export, \
                patch('proteus86.native_simulation.message') as send:
            result = interact(sim, controls={'S1': 1, 'S2': 1}, probes=['P1', 'P2'])
        self.assertEqual(export.call_count, 2)
        self.assertEqual(send.call_count, 2)
        self.assertEqual(result['native_exports'], 2)
        self.assertEqual(result['observation']['probes'], {'P1': 1, 'P2': 1})
        self.assertEqual([action['ref'] for action in result['actions']], ['S1', 'S2'])

    def test_invalid_second_control_or_probe_cannot_partly_apply_request(self):
        for failure in ('binding', 'collision', 'probe'):
            with self.subTest(failure=failure):
                before = data()
                if failure == 'binding':before['parts']['S2']['properties'].pop('INC')
                if failure == 'collision':before['parts']['P2']['properties']['KEY'] = '0'
                sim = io_sim(before)
                probes = ['UNKNOWN'] if failure == 'probe' else ['P1']
                with patch('proteus86.interactions.snapshot', return_value=before), \
                        patch('proteus86.native_simulation.message') as send:
                    with self.assertRaises((RuntimeError, KeyError)):
                        interact(sim, controls={'S1': 1, 'S2': 1}, probes=probes)
                send.assert_not_called()

    def test_unchanged_inputs_need_one_snapshot_and_no_command(self):
        before = data();sim = io_sim(before)
        with patch('proteus86.interactions.snapshot', return_value=before) as export, \
                patch('proteus86.native_simulation.message') as send:
            result = interact(sim, controls={'S1': 0, 'S2': 0}, probes=['P1', 'P2'])
        self.assertEqual(export.call_count, 1)
        send.assert_not_called()
        self.assertFalse(any(action['changed'] for action in result['actions']))

    def test_late_readback_mismatch_is_never_success(self):
        before, after = data(), data((1, 0))
        sim = io_sim(before)
        with patch('proteus86.interactions.snapshot', side_effect=[before, after]), \
                patch('proteus86.native_simulation.message') as send:
            with self.assertRaisesRegex(RuntimeError, 'S2; expected 1, observed 0') as error:
                interact(sim, controls={'S1': 1, 'S2': 1})
        self.assertEqual(send.call_count, 2)
        self.assertEqual(len(error.exception.native_action_attempts), 2)

    def test_time_drift_stops_remaining_commands_and_records_attempt(self):
        before = data();sim = io_sim(before)
        sim.status.side_effect = [dict(state='paused', simulation_seconds=at) for at in (.2, .2, .201)]
        with patch('proteus86.interactions.snapshot', return_value=before), \
                patch('proteus86.native_simulation.message') as send:
            with self.assertRaisesRegex(RuntimeError, 'time changed') as error:
                interact(sim, controls={'S1': 1, 'S2': 1})
        self.assertEqual(send.call_count, 1)
        self.assertEqual(error.exception.native_action_attempts[0]['ref'], 'S1')
        self.assertFalse(error.exception.native_action_attempts[0]['readback_verified'])

    def test_time_drift_between_initial_and_final_snapshot_fails(self):
        before, after = data(), data((1, 1), at=.201)
        with patch('proteus86.interactions.snapshot', side_effect=[before, after]), \
                patch('proteus86.native_simulation.message'):
            with self.assertRaisesRegex(RuntimeError, 'time changed'):
                interact(io_sim(before), controls={'S1': 1, 'S2': 1})

    def test_bad_requests_are_rejected_without_any_export(self):
        for kwargs in ({}, {'controls': []}, {'controls': {'S1': True}}, {'probes': []},
                       {'probes': ['P1', 'P1']}, {'probes': [None]}):
            with self.subTest(kwargs=kwargs), patch('proteus86.interactions.snapshot') as export:
                with self.assertRaises((TypeError, ValueError)):
                    interact(io_sim(data()), **kwargs)
                export.assert_not_called()


class ScenarioSim:
    def __init__(self, directory):
        self.session = SimpleNamespace(project=directory/'circuit.pdsprj', pid=123)
        self.bundle = {'project': str(self.session.project)}
        self.at = .2
        self.states = {'S1': 0, 'S2': 0}
        self.calls = []
        self.fail_at = None
        self.bad_diagnostics = False

    def status(self):
        return dict(state='paused', simulation_seconds=self.at, time_resolution_seconds=1e-9)

    def run_for(self, seconds, **kwargs):
        self.at = round(self.at + seconds, 9)
        return self.status()

    def interact(self, *, controls, probes):
        if self.fail_at == len(self.calls):
            error = RuntimeError('Native control did not acknowledge')
            error.native_action_attempts = [dict(ref='S1', state=1, readback_verified=False)]
            raise error
        self.calls.append((dict(controls), copy.deepcopy(probes)))
        actions = []
        for ref, state in controls.items():
            actions.append(dict(backend='proteus_native_sdf', ref=ref, state=state,
                                changed=self.states[ref] != state, command_time_seconds=self.at))
            self.states[ref] = state
        observation = None if probes is None else dict(backend='proteus_native_sdf',
            simulation_seconds=self.at, probes={ref:self.states['S'+ref[-1]] for ref in probes})
        return dict(backend='proteus_native_sdf', simulation_seconds=self.at, actions=actions,
                    observation=observation, native_exports=1+int(any(a['changed'] for a in actions)))

    def diagnostics(self):
        return dict(passed=not self.bad_diagnostics, entries=[], errors=['native error'] if self.bad_diagnostics else [], warnings=[])


class ScenarioProgressTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.sim = ScenarioSim(self.directory)
        self.project = patch('proteus86.api.Project')
        project = self.project.start();self.addCleanup(self.project.stop)
        project.return_value.components.return_value = [dict(ref=ref, **part) for ref, part in data()['parts'].items()]

    def run_scene(self, **kwargs):
        scene = Scenario().press('S1', at=.02).press('S2', at=.02).release('S1', at=.06)
        return run_scenario(self.sim, scene, probes=['P1', 'P2'], until=.08, sample_every=.02, **kwargs)

    def test_shared_frames_and_checkpoints_exist_while_still_running(self):
        seen = []
        def progress(summary):
            record = json.loads(Path(summary['record']).read_text(encoding='utf-8'))
            self.assertEqual(record['status'], 'running')
            self.assertFalse(record['passed'])
            seen.append(summary['frames_completed'])
            summary['frames_total'] = -1  # Caller cannot mutate the real report.
        result = self.run_scene(progress=progress, checkpoint_every=1, expected_words=['00','11','01'])
        self.assertTrue(result['passed'])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(seen, [1,2,3,4,5])
        self.assertEqual(result['frames_total'], 5)
        self.assertEqual(self.sim.calls[1][0], {'S1':1, 'S2':1})
        self.assertEqual(len(self.sim.calls), 5)
        self.assertEqual(json.loads(Path(result['record']).read_text(encoding='utf-8'))['status'], 'completed')

    def test_callback_cancellation_keeps_partial_samples_and_stays_paused(self):
        result = self.run_scene(progress=lambda summary: summary['frames_completed'] < 2)
        self.assertEqual(result['status'], 'cancelled')
        self.assertFalse(result['passed']);self.assertFalse(result['native_run_completed'])
        self.assertEqual(len(result['samples']), 2)
        self.assertEqual(self.sim.status()['state'], 'paused')
        self.assertEqual(json.loads(Path(result['record']).read_text())['frames_completed'], 2)

    def test_callback_error_fails_without_losing_samples(self):
        def broken(summary):raise RuntimeError('consumer failed')
        result = self.run_scene(progress=broken)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('consumer failed', result['error'])
        self.assertEqual(len(result['samples']), 1)
        self.assertFalse(result['native_run_completed'])

    def test_native_failure_records_partial_dispatch_and_completed_frames(self):
        self.sim.fail_at = 2
        result = self.run_scene()
        self.assertFalse(result['passed'])
        self.assertEqual(result['frames_completed'], 2)
        self.assertEqual(result['failed_frame_action_attempts'][0]['ref'], 'S1')
        self.assertEqual(len(json.loads(Path(result['record']).read_text())['samples']), 2)

    def test_keyboard_interrupt_and_system_exit_persist_before_reraise(self):
        for exception in (KeyboardInterrupt, SystemExit):
            with self.subTest(exception=exception):
                before = set(self.directory.glob('scenario-*.json'))
                def stop(summary):raise exception()
                with self.assertRaises(exception):self.run_scene(progress=stop)
                report = json.loads(next(iter(set(self.directory.glob('scenario-*.json'))-before)).read_text())
                self.assertEqual(report['status'], 'cancelled')
                self.assertFalse(report['passed'])
                self.assertEqual(len(report['samples']), 1)

    def test_failed_assertions_or_native_diagnostics_cannot_pass(self):
        result = self.run_scene(expected_words=['00'])
        self.assertTrue(result['native_run_completed']);self.assertFalse(result['passed'])
        self.sim.bad_diagnostics = True
        result = self.run_scene()
        self.assertEqual(result['status'], 'failed');self.assertFalse(result['passed'])

    def test_bad_progress_options_fail_before_native_actions_or_report_creation(self):
        for kwargs in ({'progress': True}, {'checkpoint_every': True}, {'checkpoint_every': 0}):
            with self.assertRaises((ValueError, TypeError)):self.run_scene(**kwargs)
        self.assertFalse(self.sim.calls)
        self.assertFalse(list(self.directory.glob('scenario-*.json')))

    def test_atomic_report_refuses_collision_and_preserves_last_good_snapshot(self):
        path = self.directory/'existing.json'
        _write_report(path, {'saved':1}, first=True)
        with self.assertRaises(FileExistsError):_write_report(path, {'saved':2}, first=True)
        with patch('proteus86.scenario_runner.os.replace', side_effect=PermissionError('file busy')):
            with self.assertRaises(PermissionError):_write_report(path, {'saved':3})
        self.assertEqual(json.loads(path.read_text()), {'saved':1})
        self.assertFalse(list(self.directory.glob('*.tmp')))
