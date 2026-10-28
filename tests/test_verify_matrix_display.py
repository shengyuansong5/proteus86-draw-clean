"""Public verifier tests are file-only or mocked; they never launch Proteus."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from proteus86.digital import DisplaySamplingError
from scripts import verify_matrix_display as verifier


def metadata():
    return dict(bundled_firmware=True, keys=list(verifier.KEYS), initial_display='01234567',
                segment_probes=['PS' + str(i) for i in range(8)],
                digit_probes=['PD' + str(i) for i in range(8)],
                segment_active_low=False, digit_active_low=True,
                recommended_stable_press_seconds=.08, recommended_stable_release_seconds=.08)


class MockSimulation:
    """A clock/command recorder; no instruction execution or native evidence."""
    def __init__(self):
        self.time = 0.22
        self.interactions = []
        self.intervals = []

    def interact(self, *, controls):
        self.interactions.append(dict(controls))
        return dict(backend='proteus_native_sdf', simulation_seconds=self.time,
                    actions=[dict(ref=ref, state=state) for ref, state in controls.items()])

    def run_for(self, seconds, *, tolerance):
        self.intervals.append(seconds)
        self.time += seconds
        return dict(state='paused', simulation_seconds=self.time,
                    elapsed_seconds=seconds, tolerance_seconds=tolerance)

    def diagnostics(self):
        return dict(passed=True, errors=[], warnings=[])

    def capture(self, path, **options):
        raise RuntimeError('Mock locked desktop; capture remains unpassed')


class FrameOracle:
    """Explicit expected display words, independent of callback counter logic."""
    def __init__(self, words):
        self.words = list(words)
        self.observed = []

    def __call__(self, sim, **options):
        word = self.words.pop(0)
        self.observed.append(word)
        start = sim.time
        sim.time += .04
        return dict(passed=True, backend='proteus_native_sdf', atomic_instantaneous_frame=False,
                    text=word, decimal_points=[], stable_frames=2,
                    simulation_seconds=sim.time, window_start_seconds=start, window_end_seconds=sim.time,
                    completed_frames=[dict(text=word, decimal_points=[], simulation_seconds=start + .02),
                                      dict(text=word, decimal_points=[], simulation_seconds=sim.time)],
                    samples=[dict(simulation_seconds=start + (i + 1) * .002) for i in range(16)])


class VerifyMatrixDisplayTests(unittest.TestCase):
    def setUp(self):
        # Do not depend on a missing caller TEMP silently falling back to C.
        parent = Path(__file__).resolve().parents[1] / 'artifacts/tmp'
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=parent)
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def evidence(self, name='cases'):
        folder = self.directory / name
        folder.mkdir()
        return folder

    def test_default_real_file_preparation_never_launches_a_process(self):
        before = (os.environ.get('TEMP'), os.environ.get('TMP'), tempfile.tempdir, sys_bytecode())
        output = self.directory / 'file only'
        with patch('subprocess.Popen', side_effect=AssertionError('default mode launched software')):
            with patch.object(verifier, 'run_control_batches', side_effect=AssertionError('native runner called')) as native:
                report = verifier.verify(output)
        self.assertTrue(report['passed'], report.get('error'))
        self.assertEqual(report['status'], 'prepared')
        self.assertEqual(report['scope'], 'file_contract_preparation_only')
        self.assertEqual(report['tool_version'], verifier.__version__)
        self.assertEqual(report['verifier_sha256'], verifier._sha(Path(verifier.__file__)))
        self.assertFalse(report['native_execution_attempted'])
        self.assertFalse(report['native_processes_launched'])
        self.assertFalse(report['simulation_executed'])
        self.assertFalse(report['native_run_completed'])
        native.assert_not_called()
        self.assertEqual([len(g['controls']) for g in report['preparation']['groups']], [5, 5, 5, 1])
        self.assertEqual(report['file_result']['parts'], 48)
        self.assertEqual(report['file_netcheck']['expected_nets'], 29)
        self.assertTrue((output / 'source/resources/firmware').is_dir())
        self.assertEqual(report, json.loads((output / 'result.json').read_text('utf-8')))
        self.assertEqual(before, (os.environ.get('TEMP'), os.environ.get('TMP'), tempfile.tempdir, sys_bytecode()))

    def test_invalid_options_fail_before_creating_output_or_starting_software(self):
        existing = self.directory / 'existing'
        existing.mkdir()
        marker = existing / 'keep'
        marker.write_text('unchanged')
        cases = [dict(output_dir=self.directory / 'capture', capture=True),
                 dict(output_dir=self.directory / 'native', execute_native=True),
                 dict(output_dir=existing),
                 dict(output_dir=self.directory / 'bool', execute_native=1),
                 dict(output_dir=self.directory / 'unicode', execute_native=True, temp_dir=self.directory / '中文'),
                 dict(output_dir=self.directory / 'nested', temp_dir=self.directory / 'nested/tmp'),
                 dict(output_dir=self.directory / 'same', temp_dir=self.directory / 'same'),
                 dict(output_dir=self.directory / 'used-temp', temp_dir=existing),
                 dict(output_dir=self.directory / 'relative-temp', temp_dir=Path('relative-temp'))]
        with patch('subprocess.Popen', side_effect=AssertionError('invalid request launched software')):
            for options in cases:
                with self.subTest(options=options), self.assertRaises((ValueError, FileExistsError)):
                    verifier.verify(**options)
        self.assertEqual(marker.read_text(), 'unchanged')
        self.assertEqual(sorted(path.name for path in self.directory.iterdir()), ['existing'])

    def test_explicit_ascii_native_path_on_another_drive_is_only_preflighted_not_created(self):
        # Public users may choose another drive. This test performs only a
        # read-only path preflight; actual files remain under the test checkout.
        selected = Path('C:/proteus-verifier-preflight-' + self.directory.name)
        output, temporary = verifier._paths(self.directory / 'plan', selected, True, False)
        self.assertEqual(temporary.drive.upper(), 'C:')
        self.assertFalse(temporary.exists())
        self.assertFalse(output.exists())

    def test_fresh_extraction_creates_its_explicit_test_temp_parent(self):
        fresh = self.directory / 'fresh-extraction'
        self.assertFalse((fresh / 'artifacts').exists())
        nested = VerifyMatrixDisplayTests()
        with patch(__name__ + '.__file__', str(fresh / 'tests/test_verify_matrix_display.py')):
            with patch('tempfile.gettempdir', side_effect=AssertionError('fresh test used system temp fallback')):
                nested.setUp()
        try:
            self.assertTrue(nested.directory.is_dir())
            nested.directory.relative_to(fresh / 'artifacts/tmp')
        finally:
            nested.tearDown()

    def test_cli_requires_exact_explicit_native_flag_and_native_temp(self):
        output = self.directory / 'cli'
        cases = [['--output-dir', str(output), '--capture'],
                 ['--output-dir', str(output), '--execute-native'],
                 ['--output-dir', str(output), '--execute'],
                 ['--output-dir', str(output), '--unknown']]
        with patch('subprocess.Popen', side_effect=AssertionError('invalid CLI launched software')):
            for arguments in cases:
                with self.subTest(arguments=arguments), redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        verifier.main(arguments)
                    self.assertEqual(raised.exception.code, 2)
        self.assertFalse(output.exists())

    def test_file_cancellation_has_readable_checkpoints_and_no_native_claims(self):
        updates = []

        def progress(update):
            saved = json.loads(Path(update['record']).read_text('utf-8'))
            self.assertFalse(saved['native_run_completed'])
            self.assertFalse(saved['passed'])
            updates.append(update['phase'])
            return update['phase'] != 'firmware_built'

        with patch('subprocess.Popen', side_effect=AssertionError('cancelled prepare launched software')):
            report = verifier.verify(self.directory / 'cancelled', progress=progress)
        self.assertEqual(updates, ['preparation_started', 'firmware_built'])
        self.assertEqual(report['status'], 'cancelled')
        self.assertFalse(report['passed'])
        self.assertFalse(report['native_execution_attempted'])
        self.assertTrue((self.directory / 'cancelled/firmware-build/manifest.json').is_file())
        self.assertFalse((self.directory / 'cancelled/source').exists())

    def test_file_failure_retains_completed_build_and_partial_result(self):
        with patch.object(verifier, 'generate', side_effect=RuntimeError('intentional fixture failure')):
            report = verifier.verify(self.directory / 'failed')
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(report['passed'])
        self.assertEqual(report['error']['message'], 'intentional fixture failure')
        self.assertEqual(report['stages'][-1]['phase'], 'firmware_built')
        self.assertFalse(report['native_execution_attempted'])

    def test_final_file_checkpoint_is_unpassed_until_progress_accepts_completion(self):
        def progress(update):
            saved = json.loads(Path(update['record']).read_text('utf-8'))
            self.assertFalse(saved['passed'])
            return update['phase'] != 'file_checks_completed'

        with patch('subprocess.Popen', side_effect=AssertionError('file cancellation launched software')):
            report = verifier.verify(self.directory / 'last-checkpoint', progress=progress)
        self.assertEqual((report['status'], report['passed']), ('cancelled', False))
        self.assertEqual(report['stages'][-1]['phase'], 'file_checks_completed')
        self.assertTrue(report['source_unchanged'])

    def test_crlf_reference_hex_keeps_code_equivalence_without_relabeling_generator_metadata(self):
        checkout = self.directory / 'crlf-checkout'
        examples = checkout / 'examples'
        examples.mkdir(parents=True)
        shutil.copyfile(verifier.ROOT / 'examples/matrix_display.a51', examples / 'matrix_display.a51')
        canonical = (verifier.ROOT / 'examples/matrix_display.hex').read_text('ascii')
        (examples / 'matrix_display.hex').write_bytes(canonical.replace('\n', '\r\n').encode('ascii'))
        output = self.directory / 'crlf-output'
        with patch('subprocess.Popen', side_effect=AssertionError('code-equivalence check launched software')):
            with patch.object(verifier, 'ROOT', checkout):
                with patch('examples.draw_matrix_display.__file__', str(examples / 'draw_matrix_display.py')):
                    report = verifier.verify(output)
        self.assertTrue(report['passed'], report.get('error'))
        self.assertEqual(report['contract']['firmware_basis'], 'fresh_assembly_address_byte_equivalence')
        original = json.loads((output / 'source/design.json').read_text('utf-8'))
        derived = json.loads((output / 'verification-contract.json').read_text('utf-8'))
        self.assertFalse(original['bundled_firmware'])
        self.assertIsNone(original['initial_display'])
        self.assertTrue(derived['independent_example_code_verified'])
        self.assertEqual(derived['initial_display'], '01234567')

    def test_group_callback_checks_all_expected_counts_and_saves_each_stage(self):
        # K0's release/repress adds the second response before K1 in group one.
        words = ['01234567', '01234567', '01234567', '01234510', '01234510', '01234520', '01234520',
                 '01234531', '01234542', '01234553', '01234564',
                 '01234567', '01234515', '01234526', '01234537', '01234548', '01234559',
                 '01234567', '0123451A', '0123452B', '0123453C', '0123454D', '0123455E',
                 '01234567', '0123451F']
        oracle = FrameOracle(words)
        updates = []

        def progress(update):
            saved = json.loads(Path(update['record']).read_text('utf-8'))
            self.assertEqual(saved, update['case'])
            updates.append((update['ref'], update['phase']))

        callback = verifier.make_callback(metadata(), self.evidence(), progress=progress)
        simulations, results = [], []
        with patch.object(verifier, 'read_display_frame', side_effect=oracle):
            for refs in [verifier.KEYS[:5], verifier.KEYS[5:10], verifier.KEYS[10:15], verifier.KEYS[15:]]:
                sim = MockSimulation()
                simulations.append(sim)
                results.extend(callback(sim, ref) for ref in refs)
        self.assertTrue(all(result['passed'] for result in results))
        self.assertEqual([results[i]['expected_display'] for i in (0, 1, 4, 5, 10, 15)],
                         ['01234520', '01234531', '01234564', '01234515', '0123451A', '0123451F'])
        self.assertEqual(callback.state['cases_completed'], 16)
        self.assertEqual(callback.state['reconstructed_frames'], 25)
        self.assertEqual(callback.state['native_sdf_samples'], 400)  # mocked, never native acceptance
        self.assertEqual(oracle.words, [])
        self.assertEqual(len([entry for entry in updates if entry[1] == 'completed']), 16)
        self.assertEqual(sum(sim.intervals.count(.12) for sim in simulations), 16)
        self.assertEqual(simulations[0].intervals.count(.002), 3)
        self.assertEqual(simulations[0].intervals.count(.003), 4)

    def test_sampling_failure_keeps_partial_native_report_without_passing(self):
        evidence = self.evidence()
        callback = verifier.make_callback(metadata(), evidence)
        partial = dict(passed=False, samples=[{'simulation_seconds': .221}], error='unknown state')
        with patch.object(verifier, 'read_display_frame', side_effect=DisplaySamplingError('unknown state', partial)):
            with self.assertRaises(DisplaySamplingError):
                callback(MockSimulation(), 'K0')
        saved = json.loads(next(evidence.glob('case-*.json')).read_text('utf-8'))
        self.assertFalse(saved['passed'])
        self.assertEqual(saved['status'], 'failed')
        self.assertEqual(saved['records'][0], dict(kind='initial_partial_sampling', value=partial))

    def test_frame_contract_rejects_wrong_text_unknown_time_and_single_scan(self):
        for index, change in enumerate([{'text': '00000000'}, {'stable_frames': 1},
                                        {'simulation_seconds': None},
                                        {'completed_frames': [dict(text='01234567', decimal_points=[])]}]):
            with self.subTest(change=change):
                evidence = self.evidence('invalid-%d' % index)
                callback = verifier.make_callback(metadata(), evidence)
                sim = MockSimulation()
                frame = FrameOracle(['01234567'])(sim)
                frame.update(change)
                with patch.object(verifier, 'read_display_frame', return_value=frame):
                    with self.assertRaises(RuntimeError):
                        callback(sim, 'K0')
                self.assertFalse(json.loads(next(evidence.glob('*.json')).read_text('utf-8'))['passed'])

    def test_callback_cancellation_and_optional_locked_capture_preserve_unpassed_case(self):
        callback = verifier.make_callback(metadata(), self.evidence('cancel'), progress=lambda update: False)
        with self.assertRaises(verifier.VerificationCancelled):
            callback(MockSimulation(), 'K0')
        self.assertTrue(callback.state['cancelled'])
        saved = json.loads(next((self.directory / 'cancel').glob('*.json')).read_text('utf-8'))
        self.assertEqual((saved['status'], saved['passed']), ('cancelled', False))
        callback = verifier.make_callback(metadata(), self.evidence('capture'), capture=True)
        with patch.object(verifier, 'read_display_frame', side_effect=FrameOracle(['01234567'])):
            with self.assertRaisesRegex(RuntimeError, 'locked desktop'):
                callback(MockSimulation(), 'K0')
        saved = json.loads(next((self.directory / 'capture').glob('case-*.json')).read_text('utf-8'))
        self.assertEqual((saved['status'], saved['passed']), ('failed', False))

    def test_contract_refuses_other_firmware_or_probe_order(self):
        for change in ({'bundled_firmware': False}, {'keys': list(reversed(verifier.KEYS))},
                       {'segment_probes': ['PS0'] * 8}, {'digit_active_low': False}):
            model = metadata()
            model.update(change)
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                verifier.contract_check(model)

    def test_interrupted_mock_native_runner_preserves_cancelled_report_and_environment(self):
        output, native_root = self.directory / 'interrupt-output', self.directory / 'interrupt-native'
        before = (os.environ.get('TEMP'), os.environ.get('TMP'), tempfile.tempdir)

        def interrupted(source, destination, **options):
            destination.mkdir()
            self.assertEqual(Path(os.environ['TEMP']), native_root / 'tmp')
            verifier._write(destination / 'control-results.json',
                            dict(passed=False, status='interrupted', native_run_completed=False,
                                 groups=[dict(pid=123, process_closed=True, passed=False,
                                              initialization=dict(state='paused', elapsed_seconds=.2))]))
            raise KeyboardInterrupt('mock user cancellation')

        with patch('subprocess.Popen', side_effect=AssertionError('mock verification launched software')):
            with patch.object(verifier, 'run_control_batches', side_effect=interrupted):
                # Only the runner/interruption lifecycle is mocked here. ASCII
                # native-path rejection has its own real preflight tests; keep
                # these pure file fixtures under this checkout's D directory.
                with patch.object(verifier, '_paths', return_value=(output, native_root)):
                    with patch.object(verifier, '_capture_preflight', side_effect=AssertionError('unrequested Pillow import')):
                        with self.assertRaises(KeyboardInterrupt):
                            verifier.verify(output, execute_native=True, temp_dir=native_root)
        saved = json.loads((output / 'result.json').read_text('utf-8'))
        self.assertEqual((saved['status'], saved['passed'], saved['native_run_completed']), ('cancelled', False, False))
        self.assertTrue(saved['native_result']['groups'][0]['process_closed'])
        self.assertTrue(saved['source_unchanged'])
        self.assertTrue(saved['simulation_executed'])  # only the mock initialization contract
        self.assertEqual(before, (os.environ.get('TEMP'), os.environ.get('TMP'), tempfile.tempdir))

    def test_requested_capture_capability_is_checked_before_any_native_runner(self):
        output, native_root = self.directory / 'capture-output', self.directory / 'capture-native'
        with patch('subprocess.Popen', side_effect=AssertionError('failed capture preflight launched software')):
            with patch.object(verifier, '_paths', return_value=(output, native_root)):
                with patch.object(verifier, '_capture_preflight', side_effect=RuntimeError('missing window capture capability')):
                    with patch.object(verifier, 'run_control_batches') as runner:
                        report = verifier.verify(output, execute_native=True, temp_dir=native_root, capture=True)
                        runner.assert_not_called()
        self.assertFalse(report['passed'])
        self.assertEqual(report['status'], 'failed')
        self.assertIn('window capture capability', report['error']['message'])
        self.assertFalse(report['native_execution_attempted'])
        self.assertFalse(report['native_processes_launched'])
        self.assertTrue(report['file_netcheck']['passed'])

    def test_late_callback_cancellation_does_not_count_a_failed_case_as_completed(self):
        evidence = self.evidence()
        callback = verifier.make_callback(metadata(), evidence,
                                          progress=lambda update: update['phase'] != 'completed')
        oracle = FrameOracle(['01234567', '01234567', '01234567', '01234510',
                              '01234510', '01234520', '01234520'])
        with patch.object(verifier, 'read_display_frame', side_effect=oracle):
            with self.assertRaises(verifier.VerificationCancelled):
                callback(MockSimulation(), 'K0')
        self.assertEqual(callback.state['cases_completed'], 0)
        saved = json.loads(next(evidence.glob('case-*.json')).read_text('utf-8'))
        self.assertEqual((saved['status'], saved['passed']), ('cancelled', False))

    def test_mock_runner_success_flag_cannot_replace_the_requested_case_and_frame_evidence(self):
        output, native_root = self.directory / 'empty-output', self.directory / 'empty-native'
        claimed = dict(passed=True, native_run_completed=True, cases_completed=16, source_unchanged=True,
                       groups=[dict(controls=list(refs), passed=True, process_closed=True)
                               for refs in (verifier.KEYS[:5], verifier.KEYS[5:10],
                                            verifier.KEYS[10:15], verifier.KEYS[15:])])
        with patch('subprocess.Popen', side_effect=AssertionError('mock runner launched software')):
            with patch.object(verifier, '_paths', return_value=(output, native_root)):
                with patch.object(verifier, 'run_control_batches', return_value=claimed):
                    report = verifier.verify(output, execute_native=True, temp_dir=native_root)
        self.assertEqual((report['status'], report['passed'], report['native_run_completed']), ('failed', False, False))
        self.assertEqual(report['native_summary']['cases_completed'], 0)
        self.assertEqual(report['native_summary']['reconstructed_frames'], 0)

    def test_progress_cancelled_mock_native_run_has_native_scope_and_unpassed_partial_evidence(self):
        output, native_root = self.directory / 'cancel-output', self.directory / 'cancel-native'

        def progress(update):
            return not (update.get('ref') == 'K0' and update['phase'] == 'started')

        def cancelled(source, destination, *, callback, **options):
            destination.mkdir()
            with self.assertRaises(verifier.VerificationCancelled):
                callback(MockSimulation(), 'K0')
            result = dict(passed=False, status='failed', native_run_completed=False, cases_completed=0,
                          source_unchanged=True, groups=[dict(pid=123, controls=list(verifier.KEYS[:5]),
                                                              passed=False, process_closed=True)])
            verifier._write(destination / 'control-results.json', result)
            return result

        with patch('subprocess.Popen', side_effect=AssertionError('mock cancellation launched software')):
            with patch.object(verifier, '_paths', return_value=(output, native_root)):
                with patch.object(verifier, 'run_control_batches', side_effect=cancelled):
                    report = verifier.verify(output, execute_native=True, temp_dir=native_root, progress=progress)
        self.assertEqual((report['scope'], report['status'], report['passed']),
                         ('proteus_native_matrix_display', 'cancelled', False))
        self.assertFalse(report['native_run_completed'])
        self.assertTrue(report['native_result']['groups'][0]['process_closed'])
        self.assertTrue(report['native_summary']['cancelled'])

    def test_native_phase_progress_cancellation_does_not_claim_a_runner_call_or_launch(self):
        output, native_root = self.directory / 'before-output', self.directory / 'before-native'
        with patch('subprocess.Popen', side_effect=AssertionError('pre-run cancellation launched software')):
            with patch.object(verifier, '_paths', return_value=(output, native_root)):
                with patch.object(verifier, 'run_control_batches') as runner:
                    report = verifier.verify(output, execute_native=True, temp_dir=native_root,
                                             progress=lambda row: row['phase'] != 'native_execution_started')
                    runner.assert_not_called()
        self.assertEqual((report['status'], report['passed']), ('cancelled', False))
        self.assertTrue(report['native_phase_entered'])
        self.assertFalse(report['native_runner_called'])
        self.assertFalse(report['native_execution_attempted'])
        self.assertIs(report['native_processes_launched'], False)
        self.assertEqual(report['native_launch_state'], 'not_attempted')

    def test_startup_error_without_owned_evidence_is_unknown_not_false(self):
        output, native_root = self.directory / 'unknown-output', self.directory / 'unknown-native'
        with patch('subprocess.Popen', side_effect=AssertionError('mock startup launched software')):
            with patch.object(verifier, '_paths', return_value=(output, native_root)):
                with patch.object(verifier, 'run_control_batches', side_effect=RuntimeError('no launch evidence')):
                    report = verifier.verify(output, execute_native=True, temp_dir=native_root)
        self.assertEqual((report['status'], report['passed']), ('failed', False))
        self.assertTrue(report['native_runner_called'])
        self.assertTrue(report['native_execution_attempted'])
        self.assertIsNone(report['native_processes_launched'])
        self.assertEqual(report['native_launch_state'], 'unknown')
        self.assertFalse(report['native_processes_observed'])

    def test_owned_startup_exception_retains_pid_and_cleanup_without_process_enumeration(self):
        output, native_root = self.directory / 'owned-output', self.directory / 'owned-native'
        error = RuntimeError('owned startup failure')
        error.owned_pid = 4321
        error.process_closed = True
        error.owned_startup_cleanup = {'exact_process_handle': True, 'closed': True}
        with patch('subprocess.Popen', side_effect=AssertionError('mock owned startup launched software')):
            with patch.object(verifier, '_paths', return_value=(output, native_root)):
                with patch.object(verifier, 'run_control_batches', side_effect=error):
                    report = verifier.verify(output, execute_native=True, temp_dir=native_root)
        self.assertTrue(report['native_processes_launched'])
        self.assertEqual(report['native_pids_observed'], [4321])
        self.assertEqual(report['native_launch_state'], 'observed')
        self.assertEqual(report['native_startup_error']['owned_startup_cleanup'], error.owned_startup_cleanup)
        self.assertTrue(report['native_startup_error']['process_closed'])
        self.assertFalse(report['passed'])

    def test_batch_startup_failure_record_is_kept_with_observed_pid(self):
        output, native_root = self.directory / 'batch-output', self.directory / 'batch-native'
        failure = dict(passed=False, native_run_completed=False, cases_completed=0, source_unchanged=True,
                       groups=[dict(controls=list(verifier.KEYS[:5]), pid=4567, startup_failure=True,
                                    process_closed=True, owned_startup_cleanup={'closed': True}, passed=False)])
        with patch('subprocess.Popen', side_effect=AssertionError('mock batch startup launched software')):
            with patch.object(verifier, '_paths', return_value=(output, native_root)):
                with patch.object(verifier, 'run_control_batches', return_value=failure):
                    report = verifier.verify(output, execute_native=True, temp_dir=native_root)
        self.assertTrue(report['native_processes_launched'])
        self.assertEqual(report['native_result'], failure)
        self.assertTrue(report['native_result']['groups'][0]['startup_failure'])
        self.assertFalse(report['passed'])

    def test_callback_record_io_failure_does_not_replace_original_interruptions(self):
        original_write = verifier._write
        for index, error in enumerate((KeyboardInterrupt('cancel'), SystemExit(7), GeneratorExit('close'))):
            with self.subTest(interruption=type(error).__name__):
                evidence = self.evidence('io-interrupt-%d' % index)
                error.digital_report = {'passed': False, 'samples': [{'simulation_seconds': .221}]}
                callback = verifier.make_callback(metadata(), evidence)

                def fail_partial_and_final(path, report):
                    if report.get('records'):
                        raise OSError('mock record disk failure')
                    original_write(path, report)

                with patch.object(verifier, 'read_display_frame', side_effect=error):
                    with patch.object(verifier, '_write', side_effect=fail_partial_and_final):
                        with self.assertRaises(type(error)) as raised:
                            callback(MockSimulation(), 'K0')
                self.assertIs(raised.exception, error)
                self.assertEqual([row['phase'] for row in error.verification_record_errors],
                                 ['initial_partial_sampling', 'case_final_checkpoint'])
                self.assertTrue(callback.state['cancelled'])
                self.assertFalse(json.loads(next(evidence.glob('case-*.json')).read_text('utf-8'))['passed'])

    def test_callback_final_write_error_without_an_original_error_fails_the_case(self):
        original_write = verifier._write
        evidence = self.evidence()
        callback = verifier.make_callback(metadata(), evidence)

        def reject_final_pass(path, report):
            if report.get('passed'):
                raise OSError('mock final case write failure')
            original_write(path, report)

        oracle = FrameOracle(['01234567', '01234567', '01234567', '01234510',
                              '01234510', '01234520', '01234520'])
        with patch.object(verifier, 'read_display_frame', side_effect=oracle):
            with patch.object(verifier, '_write', side_effect=reject_final_pass):
                with self.assertRaisesRegex(OSError, 'final case write failure'):
                    callback(MockSimulation(), 'K0')
        self.assertEqual(callback.state['cases_completed'], 0)
        self.assertFalse(json.loads(next(evidence.glob('case-*.json')).read_text('utf-8'))['passed'])

    def test_recovery_json_and_final_write_failures_preserve_original_interrupt(self):
        output, native_root = self.directory / 'io-output', self.directory / 'io-native'
        error = KeyboardInterrupt('original user cancellation')
        original_write = verifier._write

        def interrupted(source, destination, **options):
            destination.mkdir()
            (destination / 'control-results.json').write_text('{incomplete', encoding='utf-8')
            raise error

        def reject_final_cancel(path, report):
            if path == output / 'result.json' and report.get('status') == 'cancelled':
                raise OSError('mock final report disk failure')
            original_write(path, report)

        with patch('subprocess.Popen', side_effect=AssertionError('mock interrupt launched software')):
            with patch.object(verifier, '_paths', return_value=(output, native_root)):
                with patch.object(verifier, 'run_control_batches', side_effect=interrupted):
                    with patch.object(verifier, '_write', side_effect=reject_final_cancel):
                        with self.assertRaises(KeyboardInterrupt) as raised:
                            verifier.verify(output, execute_native=True, temp_dir=native_root)
        self.assertIs(raised.exception, error)
        self.assertEqual([row['phase'] for row in error.verification_record_errors],
                         ['native_result_recovery', 'verification_final_checkpoint'])
        self.assertEqual(error.verification_report['status'], 'cancelled')
        self.assertIsNone(error.verification_report['native_processes_launched'])
        self.assertFalse(error.verification_report['passed'])

    def test_final_master_write_error_without_original_exception_is_not_success(self):
        output = self.directory / 'write-output'
        original_write = verifier._write

        def reject_prepared(path, report):
            if path == output / 'result.json' and report.get('status') == 'prepared':
                raise OSError('mock final prepared report failure')
            original_write(path, report)

        with patch('subprocess.Popen', side_effect=AssertionError('file mode launched software')):
            with patch.object(verifier, '_write', side_effect=reject_prepared):
                with self.assertRaisesRegex(OSError, 'final prepared report failure'):
                    verifier.verify(output)
        self.assertFalse(json.loads((output / 'result.json').read_text('utf-8'))['passed'])


def sys_bytecode():
    import sys
    return sys.dont_write_bytecode


if __name__ == '__main__':
    unittest.main()
