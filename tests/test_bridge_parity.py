"""Shared contract coverage, actual saved-file round trips and native ownership."""
import json
from pathlib import Path
import tempfile
import unittest
import os
from unittest.mock import patch, MagicMock

from proteus86 import Circuit
from proteus86.bridge import dispatch, tool_catalog
from proteus86.bridge_operations import Operations, CIRCUIT_METHODS, READ_METHODS, SIM_METHODS, EDITOR_METHODS
from proteus86.simulation import Simulation


class BridgeParityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.output = self.workspace / 'outputs'
        self.native = self.workspace / 'native'
        self.output.mkdir()
        self.native.mkdir()
        self.ops = Operations(self.workspace, self.output)

    def tearDown(self):
        self.ops.close()
        self.temp.cleanup()

    def test_public_core_additions_require_contract_review(self):
        circuit_names = {name for name in dir(Circuit) if not name.startswith('_') and callable(getattr(Circuit, name))}
        self.assertEqual(circuit_names - {'open', 'save', 'batch'}, CIRCUIT_METHODS | READ_METHODS)
        sim_names = {name for name in dir(Simulation) if not name.startswith('_') and callable(getattr(Simulation, name))}
        self.assertEqual(sim_names - {'open', 'close', 'capture', 'run_scenario'}, SIM_METHODS)
        from proteus86.session import Session
        editor_names = {name for name in dir(Session) if not name.startswith('_') and callable(getattr(Session, name))}
        self.assertEqual(editor_names - {'save', 'export_netlist', 'close'}, EDITOR_METHODS)

    def test_async_submission_or_partial_report_is_never_a_pass(self):
        result = self.output / 'partial.json'
        result.write_text(json.dumps({'passed': True, 'native_run_completed': True}), encoding='utf-8')
        process = MagicMock()
        process.poll.return_value = None
        self.ops.jobs['owned-job'] = dict(process=process, directory=self.native, result=result)
        self.assertFalse(self.ops._native_job_status('owned-job')['passed'])
        process.poll.return_value = 0
        self.assertTrue(self.ops._native_job_status('owned-job')['passed'])
        result.write_text(json.dumps({'passed': False, 'status': 'cancelled'}), encoding='utf-8')
        self.assertFalse(self.ops._native_job_status('owned-job')['passed'])

    def test_async_cancel_is_cooperative_and_cannot_target_unknown_process(self):
        process = MagicMock()
        process.poll.return_value = None
        self.ops.jobs['owned-job'] = dict(process=process, directory=self.native, result=self.output/'missing.json')
        self.ops._native_job_cancel('owned-job')
        self.assertTrue((self.native / 'cancel').is_file())
        process.terminate.assert_not_called()
        process.kill.assert_not_called()
        with self.assertRaises(ValueError):
            self.ops._native_job_cancel('another-process')
        process.poll.return_value = 0

    def test_recipe_failure_closes_only_owned_context_and_remains_failed(self):
        from proteus86.bridge_jobs import run_recipe
        fake = MagicMock()
        fake.native_action.side_effect = [dict(handle='ours'), RuntimeError('controlled')]
        result = run_recipe(fake, self.output/'recipe',
                            [dict(action='open', params={}, **{'as': 'sim'}),
                             dict(action='call', params={'handle': '$sim', 'method': 'run_for'})], lambda _: True)
        self.assertFalse(result['passed'])
        self.assertFalse(result['native_run_completed'])
        self.assertTrue(result['owned_processes_closed'])
        fake.close.assert_called_once()

    def test_native_opt_in_is_required_for_both_catalog_and_execution(self):
        self.assertNotIn('native_action', {t['name'] for t in tool_catalog(False)})
        self.assertIn('native_action', {t['name'] for t in tool_catalog(True)})
        with self.assertRaises(ValueError):
            self.ops.native_action('open', {'project': 'none', 'name': 'test'})
        result = dispatch(self.ops, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                    'params': {'name': 'capabilities', 'arguments': {}}})
        value = json.loads(result['result']['content'][0]['text'])
        self.assertEqual(value['platforms'], ['Codex', 'DeepSeek Harness'])
        self.assertFalse(value['native_enabled'])

    def test_model_paths_cannot_escape_or_write_to_read_only_source(self):
        original = self.workspace / 'source.hex'
        original.write_text('sentinel', encoding='utf-8')
        for name in ('../escape', str(original), str(self.workspace.parent / 'foreign.hex')):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.ops.path(name, write=True)
        self.assertEqual(self.ops.path('source.hex', exists=True), original)
        with self.assertRaises(ValueError):
            self.ops.programs({'components': [{'properties': {'PROGRAM': '../foreign.hex'}}]})
        self.assertEqual(original.read_text(encoding='utf-8'), 'sentinel')

    def test_native_call_cannot_execute_private_or_arbitrary_methods(self):
        self.ops.allow_native = True
        # This test supplies an already-owned mock; no native path is opened.
        self.ops.native_root = self.native
        sim = MagicMock()
        sim.session.process.poll.return_value = 0
        self.ops.simulations['owned'] = sim
        with self.assertRaises(ValueError):
            self.ops.native_action('call', {'handle': 'owned', 'method': '__getattribute__', 'args': ['session']})
        sim.run_for.return_value = {'simulation_seconds': 0.2, 'state': 'paused'}
        result = self.ops.native_action('call', {'handle': 'owned', 'method': 'run_for', 'args': [0.2]})
        self.assertEqual(result['simulation_seconds'], 0.2)
        sim.run_for.assert_called_once_with(0.2)
        self.assertTrue(self.ops.native_action('close', {'handle': 'owned'})['closed'])
        self.assertNotIn('owned', self.ops.simulations)

    def test_native_environment_restores_temp_and_cache_on_interruption(self):
        self.ops.native_root = self.native
        prior = {key: os.environ.get(key) for key in ('TEMP', 'TMP')}
        cached = tempfile.tempdir
        interruption = KeyboardInterrupt('controlled')
        with self.assertRaises(KeyboardInterrupt) as caught:
            with self.ops.native_environment():
                self.assertEqual(os.environ['TEMP'], str(self.native/'runtime-tmp'))
                self.assertEqual(os.environ['TMP'], str(self.native/'runtime-tmp'))
                self.assertIsNone(tempfile.tempdir)
                raise interruption
        self.assertIs(caught.exception, interruption)
        self.assertEqual({key: os.environ.get(key) for key in ('TEMP','TMP')}, prior)
        self.assertEqual(tempfile.tempdir, cached)

    def test_cleanup_failure_retains_owned_handle_for_recovery(self):
        sim = MagicMock()
        sim.close.side_effect = RuntimeError('controlled cleanup failure')
        self.ops.simulations['owned'] = sim
        with self.assertRaisesRegex(RuntimeError, 'cleanup failed'):
            self.ops.close()
        self.assertIn('owned', self.ops.simulations)
        sim.close.side_effect = None
        sim.session.process.poll.return_value = 0
        self.ops.close()
        self.assertNotIn('owned', self.ops.simulations)

    def test_failed_graceful_cleanup_terminates_only_exact_owned_popen_and_stays_failed(self):
        sim = MagicMock()
        sim.close.side_effect = RuntimeError('owned window cannot close')
        sim.session.process.poll.side_effect = [None, 0]
        self.ops.simulations['owned'] = sim
        with self.assertRaisesRegex(RuntimeError, 'forced_owned_termination'):
            self.ops.close()
        sim.session.process.terminate.assert_called_once_with()
        sim.session.process.wait.assert_called_once_with(timeout=5)
        sim.session.process.poll.side_effect = None
        sim.session.process.poll.return_value = 0
        sim.close.side_effect = None
        self.ops.close()

    def test_real_edit_save_reopen_checked_backup_and_expected_nets(self):
        expected = [['R1.1', 'R2.1', 'VCC'], ['R1.2', 'R2.2', 'GND']]
        design = '[parts]\nR1 RES 10k\nR2 RES 10k\n[terms]\nVCC POWER\nGND GROUND\n[nets]\nR1.1,R2.1,VCC\nR1.2,R2.2,GND\n'
        first = self.ops.project_action('generate', {'design': design, 'destination': 'first.pdsprj'})
        original = Path(first['project']).read_bytes()
        edit = self.ops.circuit_edit(source=str(self.output / 'first.pdsprj'), destination='edited.pdsprj',
                                    operations=[{'method': 'update', 'args': ['R1'], 'kwargs': {'value': '22k'}}],
                                    expected_nets=expected)
        self.assertTrue(edit['netcheck']['passed'])
        self.assertEqual(Path(first['project']).read_bytes(), original)
        self.assertEqual({p['ref']: p['value'] for p in edit['components']}['R1'], '22k')
        before = Path(edit['project']).read_bytes()
        overwrite = self.ops.circuit_edit(source=edit['project'], destination='edited.pdsprj', overwrite=True,
                                         operations=[{'method': 'update', 'args': ['R1'], 'kwargs': {'value': '33k'}}],
                                         expected_nets=expected)
        self.assertEqual(Path(overwrite['backup']).read_bytes(), before)

    def test_failed_edit_never_publishes_or_modifies_source(self):
        with patch.object(Circuit, 'save') as save:
            with self.assertRaises(ValueError):
                self.ops.circuit_edit(destination='bad.pdsprj', operations=[{'method': '__dict__'}], expected_nets=[])
            save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
