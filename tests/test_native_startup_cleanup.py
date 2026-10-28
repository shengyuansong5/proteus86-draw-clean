"""Interrupted constructors must close only their own process and re-raise."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from proteus86.session import Session, NativeSession
from proteus86.simulation import Simulation
from proteus86.digital import run_control_batches


ROOT = Path(__file__).resolve().parents[1]


def process(pid=871):
    result = Mock(pid=pid)
    result.poll.return_value = None

    def terminate():
        result.poll.return_value = 0

    result.terminate.side_effect = terminate
    result.wait.return_value = 0
    return result


class NativeStartupCleanupTests(unittest.TestCase):
    def test_session_startup_failures_and_interruptions_close_exact_owned_handle(self):
        for error in (RuntimeError('startup failed'), KeyboardInterrupt('cancel startup'),
                      SystemExit(130), GeneratorExit('generator cancelled')):
            with self.subTest(kind=type(error).__name__):
                owned = process()

                def launch(instance, *args, **options):
                    instance.process, instance.pid = owned, owned.pid
                    raise error

                with patch.object(NativeSession, '__init__', launch):
                    with self.assertRaises(type(error)) as caught:
                        Session('unused.pdsprj', executable='D:/fake/PDS.EXE')
                self.assertIs(caught.exception, error)
                owned.terminate.assert_called_once_with()
                owned.wait.assert_called_once_with(timeout=5)
                self.assertEqual(error.owned_pid, owned.pid)
                self.assertTrue(error.process_closed)

    def test_failed_validation_before_launch_preserves_exception_without_process_claim(self):
        error = FileNotFoundError('pre-launch project validation')
        with patch.object(NativeSession, '__init__', side_effect=error):
            with self.assertRaises(FileNotFoundError) as caught:
                Session('unused.pdsprj', executable='D:/fake/PDS.EXE')
        self.assertIs(caught.exception, error)
        self.assertFalse(hasattr(error, 'owned_pid'))

    def test_already_closed_process_is_not_terminated_again(self):
        owned, error = process(), RuntimeError('lower layer cleaned up')
        owned.poll.return_value = 2

        def launch(instance, *args, **options):
            instance.process, instance.pid = owned, owned.pid
            raise error

        with patch.object(NativeSession, '__init__', launch):
            with self.assertRaises(RuntimeError):
                Session('unused.pdsprj', executable='D:/fake/PDS.EXE')
        owned.terminate.assert_not_called()
        owned.wait.assert_not_called()
        self.assertTrue(error.process_closed)
        self.assertEqual(error.owned_startup_cleanup, 'already_closed')

    def test_cleanup_failure_or_second_interrupt_never_masks_original(self):
        for cleanup_error in (OSError('synthetic cleanup failure'), KeyboardInterrupt('second interrupt')):
            with self.subTest(kind=type(cleanup_error).__name__):
                owned, original = process(), KeyboardInterrupt('original interruption')
                owned.terminate.side_effect = cleanup_error

                def launch(instance, *args, **options):
                    instance.process, instance.pid = owned, owned.pid
                    raise original

                with patch.object(NativeSession, '__init__', launch):
                    with self.assertRaises(KeyboardInterrupt) as caught:
                        Session('unused.pdsprj', executable='D:/fake/PDS.EXE')
                self.assertIs(caught.exception, original)
                self.assertFalse(original.process_closed)
                self.assertIn(str(cleanup_error), original.owned_cleanup_error)

    def test_interrupt_while_waiting_for_process_exit_preserves_original(self):
        owned, original = process(), SystemExit(130)
        owned.terminate.side_effect = None
        owned.wait.side_effect = KeyboardInterrupt('cleanup wait interrupted')

        def launch(instance, *args, **options):
            instance.process, instance.pid = owned, owned.pid
            raise original

        with patch.object(NativeSession, '__init__', launch):
            with self.assertRaises(SystemExit) as caught:
                Session('unused.pdsprj', executable='D:/fake/PDS.EXE')
        self.assertIs(caught.exception, original)
        self.assertFalse(original.process_closed)
        self.assertIn('cleanup wait interrupted', original.owned_cleanup_error)

    def test_simulation_constructor_interruption_closes_session_before_return(self):
        for original in (RuntimeError('profile rejected'), KeyboardInterrupt('reader interrupted'), SystemExit(130)):
            with self.subTest(kind=type(original).__name__):
                owned = process()
                session = SimpleNamespace(process=owned, pid=owned.pid)

                class BrokenSimulation(Simulation):
                    def __init__(self, session):
                        raise original

                with patch('proteus86.simulation.prepare_run', return_value={'project': 'copy.pdsprj'}), \
                     patch('proteus86.session.Session', return_value=session):
                    with self.assertRaises(type(original)) as caught:
                        BrokenSimulation.open('source.pdsprj', 'run')
                self.assertIs(caught.exception, original)
                owned.terminate.assert_called_once_with()
                self.assertTrue(original.process_closed)

    def test_preflight_failure_never_constructs_a_session(self):
        error = KeyboardInterrupt('firmware copy interrupted')
        with patch('proteus86.simulation.prepare_run', side_effect=error), \
             patch('proteus86.session.Session') as launch:
            with self.assertRaises(KeyboardInterrupt) as caught:
                Simulation.open('source.pdsprj', 'run')
        self.assertIs(caught.exception, error)
        launch.assert_not_called()

    def test_simulation_preserves_constructor_cleanup_metadata(self):
        error = KeyboardInterrupt('session interrupted')
        error.owned_pid, error.process_closed = 872, True
        with patch('proteus86.simulation.prepare_run', return_value={'project': 'copy.pdsprj'}), \
             patch('proteus86.session.Session', side_effect=error):
            with self.assertRaises(KeyboardInterrupt) as caught:
                Simulation.open('source.pdsprj', 'run')
        self.assertIs(caught.exception, error)
        self.assertEqual(error.owned_pid, 872)
        self.assertTrue(error.process_closed)

    def test_control_batch_retains_failed_startup_pid_and_cleanup_evidence(self):
        parent = ROOT / 'artifacts/native-startup-tests/tmp'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            root = Path(directory)
            source = root / 'source.pdsprj'
            source.write_bytes(b'opaque file; preparation is mocked')
            prepared = dict(passed=True, groups=[dict(index=0, controls=['K0'], project=str(source))])
            error = RuntimeError('native profile rejected after launch')
            error.owned_pid, error.process_closed = 873, True
            error.owned_startup_cleanup = 'terminated'
            with patch('proteus86.digital.prepare_control_batches', return_value=prepared), \
                 patch.object(Simulation, 'open', side_effect=error):
                report = run_control_batches(source, root / 'run', callback=lambda *_: {'passed': True})
            self.assertFalse(report['passed'])
            row = report['groups'][0]
            self.assertEqual(row['pid'], 873)
            self.assertTrue(row['startup_failure'])
            self.assertTrue(row['process_closed'])
            self.assertEqual(row['owned_startup_cleanup'], 'terminated')
            self.assertEqual(row['cases'], [])
            saved = json.loads((root / 'run/control-results.json').read_text())
            self.assertEqual(saved['groups'][0]['pid'], 873)
            self.assertTrue(saved['source_unchanged'])

    def test_control_batch_startup_interrupt_is_persisted_and_reraised(self):
        parent = ROOT / 'artifacts/native-startup-tests/tmp'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            root = Path(directory)
            source = root / 'source.pdsprj'
            source.write_bytes(b'opaque mocked project')
            prepared = dict(passed=True, groups=[dict(index=0, controls=['K0'], project=str(source))])
            error = KeyboardInterrupt('launch interrupted')
            error.owned_pid, error.process_closed = 874, True
            with patch('proteus86.digital.prepare_control_batches', return_value=prepared), \
                 patch.object(Simulation, 'open', side_effect=error):
                with self.assertRaises(KeyboardInterrupt) as caught:
                    run_control_batches(source, root / 'run', callback=lambda *_: {'passed': True})
            self.assertIs(caught.exception, error)
            saved = json.loads((root / 'run/control-results.json').read_text())
            self.assertEqual(saved['status'], 'interrupted')
            self.assertFalse(saved['passed'])
            self.assertTrue(saved['groups'][0]['process_closed'])

    def test_failed_checkpoint_does_not_mask_original_startup_interruption(self):
        from proteus86.scenario_runner import _write_report
        parent = ROOT / 'artifacts/native-startup-tests/tmp'
        parent.mkdir(parents=True, exist_ok=True)
        for interruption in (KeyboardInterrupt('original Ctrl+C'), SystemExit(130)):
            with self.subTest(kind=type(interruption).__name__), tempfile.TemporaryDirectory(dir=parent) as directory:
                root = Path(directory)
                source = root / 'source.pdsprj'
                source.write_bytes(b'opaque mocked project')
                prepared = dict(passed=True, groups=[dict(index=0, controls=['K0'], project=str(source))])
                interruption.owned_pid, interruption.process_closed = 875, True
                calls = 0

                def fail_after_initial_records(*args, **options):
                    nonlocal calls
                    calls += 1
                    if calls > 2:
                        raise OSError('checkpoint storage unavailable')
                    return _write_report(*args, **options)

                with patch('proteus86.digital.prepare_control_batches', return_value=prepared), \
                     patch.object(Simulation, 'open', side_effect=interruption), \
                     patch('proteus86.scenario_runner._write_report', side_effect=fail_after_initial_records):
                    with self.assertRaises(type(interruption)) as caught:
                        run_control_batches(source, root / 'run', callback=lambda *_: {'passed': True})
                self.assertIs(caught.exception, interruption)
                self.assertIn('checkpoint storage unavailable', interruption.native_checkpoint_error)
                self.assertTrue(interruption.process_closed)
                # The last real checkpoint stays unpassed, not an invented
                # successful final record after an unwritable output device.
                saved = json.loads((root / 'run/control-results.json').read_text())
                self.assertFalse(saved['passed'])


if __name__ == '__main__':
    unittest.main()
