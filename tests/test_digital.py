"""File grouping and synthetic observations are not native simulation proof."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from proteus86 import Circuit
from proteus86.digital import (DisplaySamplingError, decode_seven_segment,
                               prepare_control_batches, read_display_frame,
                               run_control_batches)


CODES = (0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07,
         0x7F, 0x6F, 0x77, 0x7C, 0x39, 0x5E, 0x79, 0x71)


class Display:
    def __init__(self, samples, *, digit_count=8, active_low=False, segment_count=8, digit_active_low=True):
        self.samples = iter(samples)
        self.clock = 0.1
        self.digit_count = digit_count
        self.segment_count = segment_count
        self.active_low = active_low
        self.digit_active_low = digit_active_low
        self.steps = []
        self.pause_calls = 0
        self.diagnostics_passed = True
        self.stalled = False
        self.time_key = 'simulation_seconds'

    def pause(self):
        self.pause_calls += 1
        return dict(state='paused', simulation_seconds=self.clock)

    def observe(self, refs):
        item = next(self.samples)
        if isinstance(item, BaseException):
            raise item
        active, code = item
        active = [] if active is None else [active] if isinstance(active, int) else active
        bits = {f'S{i}': ((code >> i) & 1) ^ self.active_low for i in range(self.segment_count)}
        bits.update({f'D{i}': int((i not in active) if self.digit_active_low else (i in active))
                     for i in range(self.digit_count)})
        return dict(backend='proteus_native_sdf', **{self.time_key: self.clock},
                    time_resolution_seconds=1e-6, probes=bits)

    def run_for(self, duration, **options):
        self.steps.append(duration)
        if not self.stalled:
            self.clock = round(self.clock + duration, 6)
        return dict(state='paused', simulation_seconds=self.clock)

    def diagnostics(self):
        return dict(passed=self.diagnostics_passed, errors=[] if self.diagnostics_passed else ['synthetic model error'])


def observe(display, **options):
    return read_display_frame(display, segments=[f'S{i}' for i in range(display.segment_count)],
                              digits=[f'D{i}' for i in range(display.digit_count)], **options)


class DigitalDisplayTests(unittest.TestCase):
    def test_hex_decimal_point_blank_minus_and_configurable_polarity(self):
        for index, code in enumerate(CODES):
            with self.subTest(index=index):
                decoded = decode_seven_segment(code | 0x80)
                self.assertEqual(decoded['character'], format(index, 'X'))
                self.assertTrue(decoded['decimal_point'])
                self.assertEqual(decode_seven_segment(code ^ 0xFF, segment_active_low=True)['character'], format(index, 'X'))
        self.assertEqual(decode_seven_segment(0)['character'], ' ')
        self.assertEqual(decode_seven_segment(0x40)['character'], '-')
        for invalid in (True, -1, 256, float('nan'), '3F'):
            with self.assertRaises(ValueError):
                decode_seven_segment(invalid)
        with self.assertRaisesRegex(ValueError, 'Unrecognized'):
            decode_seven_segment(1)

    def test_two_complete_rounds_reconstruct_digits_points_and_native_window(self):
        samples = []
        for _ in range(2):
            for digit in range(8):
                samples.extend([(None, 0), (digit, CODES[digit] | (0x80 if digit in (2, 7) else 0))])
        display = Display(samples)
        result = observe(display, max_samples=64)
        self.assertTrue(result['passed'])
        self.assertEqual(result['text'], '01234567')
        self.assertEqual(result['decimal_points'], [2, 7])
        self.assertEqual(result['stable_frames'], 2)
        self.assertEqual(len(result['completed_frames']), 2)
        self.assertFalse(result['atomic_instantaneous_frame'])
        self.assertEqual(result['window_start_seconds'], 0.1)
        self.assertEqual(result['simulation_seconds'], display.clock)
        self.assertEqual(result['window_end_seconds'], display.clock)
        self.assertEqual(display.pause_calls, 2)
        self.assertEqual(len(set(display.steps)), 2)
        self.assertEqual(len(result['samples'][0]['probes']), 16)

    def test_changed_partial_round_is_discarded_instead_of_mixing_digits(self):
        display = Display([(0, CODES[0]), (0, CODES[1]), (1, CODES[2]),
                           (0, CODES[1]), (1, CODES[2])], digit_count=2)
        result = observe(display, max_samples=8)
        self.assertEqual(result['text'], '12')
        self.assertEqual([frame['text'] for frame in result['completed_frames']], ['12', '12'])

    def test_different_complete_frames_do_not_count_as_stable(self):
        display = Display([(0, CODES[0]), (1, CODES[1]), (0, CODES[0]), (1, CODES[2]),
                           (0, CODES[0]), (1, CODES[2])], digit_count=2)
        result = observe(display, max_samples=8)
        self.assertEqual(result['text'], '02')
        self.assertEqual([frame['text'] for frame in result['completed_frames']], ['01', '02', '02'])

    def test_segment_active_low_and_seven_probe_input(self):
        display = Display([(0, CODES[10]), (0, CODES[10])], digit_count=1,
                          active_low=True, segment_count=7)
        result = observe(display, max_samples=2, segment_active_low=True)
        self.assertEqual(result['text'], 'A')
        self.assertEqual(result['decimal_points'], [])

    def test_high_digit_select_and_low_segment_polarities_are_independent(self):
        display = Display([(0, CODES[15] | 0x80)] * 2, digit_count=1,
                          active_low=True, digit_active_low=False)
        result = observe(display, max_samples=2, digit_active_low=False, segment_active_low=True)
        self.assertEqual(result['text'], 'F')
        self.assertEqual(result['decimal_points'], [0])

    def test_missing_digits_stop_at_native_time_bound_with_partial_evidence(self):
        display = Display([(0, CODES[0])] * 100, digit_count=2)
        with self.assertRaises(DisplaySamplingError) as caught:
            observe(display, max_samples=100, max_native_seconds=0.01)
        report = caught.exception.report
        self.assertFalse(report['passed'])
        self.assertLessEqual(report['window_end_seconds'] - report['window_start_seconds'], 0.01 + 1e-9)
        self.assertLess(len(report['samples']), 100)
        self.assertEqual(report['completed_frames'], [])

    def test_sample_limit_without_two_stable_rounds_cannot_pass(self):
        display = Display([(0, CODES[0]), (1, CODES[1]), (0, CODES[0]), (1, CODES[2])], digit_count=2)
        with self.assertRaises(DisplaySamplingError) as caught:
            observe(display, max_samples=4)
        self.assertEqual(caught.exception.report['stable_frames'], 1)
        self.assertFalse(caught.exception.report['passed'])

    def test_actual_at_alias_stale_time_multiple_selects_and_unknown_code_fail(self):
        cases = [('alias', Display([(0, CODES[0])] * 2, digit_count=1)),
                 ('stalled', Display([(0, CODES[0])] * 2, digit_count=1)),
                 ('selects', Display([([0, 1], CODES[0])], digit_count=2)),
                 ('code', Display([(0, 1)], digit_count=1))]
        cases[0][1].time_key = 'actual_at'
        cases[1][1].stalled = True
        for name, display in cases:
            with self.subTest(name=name), self.assertRaises(DisplaySamplingError) as caught:
                observe(display, max_samples=4)
            self.assertFalse(caught.exception.report['passed'])
            self.assertEqual(display.pause_calls, 2)
        display = Display([(0, CODES[0])], digit_count=1)
        display.time_key = 'actual_at'
        with self.assertRaisesRegex(DisplaySamplingError, 'simulation_seconds'):
            observe(display, max_samples=2)

    def test_diagnostics_failure_stays_unpassed(self):
        display = Display([(0, CODES[0])] * 2, digit_count=1)
        display.diagnostics_passed = False
        with self.assertRaisesRegex(DisplaySamplingError, 'diagnostics') as caught:
            observe(display, max_samples=2)
        self.assertFalse(caught.exception.report['passed'])

    def test_unknown_probe_error_names_the_signal_and_preserves_rejected_state(self):
        display = Display([], digit_count=1)
        probes = {f'S{i}': 0 for i in range(8)}
        probes.update(S3='X', D0=0)
        display.observe = Mock(return_value=dict(backend='proteus_native_sdf', simulation_seconds=.1,
                                                 time_resolution_seconds=1e-6, probes=probes))
        with self.assertRaisesRegex(DisplaySamplingError, 'S3') as caught:
            observe(display, max_samples=2)
        self.assertEqual(caught.exception.report['rejected_probe_states'], {'S3': 'X'})
        self.assertFalse(caught.exception.report['passed'])

    def test_pause_failure_after_stable_samples_stays_unpassed(self):
        display = Display([(0, CODES[0])] * 2, digit_count=1)
        original = display.pause
        calls = []

        def pause():
            calls.append(True)
            if len(calls) > 1:
                raise RuntimeError('synthetic pause failure')
            return original()

        display.pause = pause
        with self.assertRaisesRegex(DisplaySamplingError, 'pause') as caught:
            observe(display, max_samples=2)
        self.assertFalse(caught.exception.report['passed'])

    def test_interruption_is_rethrown_with_partial_report_and_pause(self):
        interruption = KeyboardInterrupt('cancel')
        display = Display([(0, CODES[0]), interruption], digit_count=1)
        with self.assertRaises(KeyboardInterrupt) as caught:
            observe(display, max_samples=2)
        self.assertIs(caught.exception, interruption)
        self.assertFalse(interruption.digital_report['passed'])
        self.assertEqual(len(interruption.digital_report['samples']), 1)
        self.assertEqual(display.pause_calls, 2)

    def test_invalid_parameters_fail_before_operating_simulation(self):
        sim = SimpleNamespace(pause=Mock(), observe=Mock(), run_for=Mock())
        defaults = dict(segments=[f'S{i}' for i in range(8)], digits=['D0'])
        for changes in [dict(segments='S0'), dict(segments=['S0'] * 8), dict(digits=['S0']),
                        dict(max_samples=1), dict(stable_frames=1), dict(sample_seconds=True),
                        dict(max_native_seconds=0), dict(digit_active_low=1)]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                read_display_frame(sim, **dict(defaults, **changes))
        sim.pause.assert_not_called()
        sim.observe.assert_not_called()
        sim.run_for.assert_not_called()


class CircuitFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def source(self, count=16, *, firmware=False):
        c = Circuit()
        with c.batch():
            for index in range(count):
                c.add_mm('BUTTON', 'K' + str(index), 'KEY', index % 4 * 50.8, -(index // 4) * 25.4)
            c.bind_controls(*['K' + str(index) for index in range(min(count, 2))])
            c.set_properties('K' + str(count - 1), STATE='1')
            if firmware:
                c.add_mm('AT89C52', 'U1', 'AT89C52', -50.8, 0)
                image = self.root / '程序 固件.hex'
                image.write_bytes((Path(__file__).resolve().parents[1] / 'examples/blink8051.hex').read_bytes())
                c.bind_firmware('U1', image)
        return c.save(self.root / '原始工程.pdsprj')


class PreparedBatchTests(CircuitFixture):
    def test_sixteen_keys_become_four_exclusive_portable_groups_without_source_edits(self):
        source = self.source(firmware=True)
        original = source.read_bytes()
        with patch('subprocess.Popen', side_effect=AssertionError('File preparation launched an application')):
            prepared = prepare_control_batches(source, self.root / '分组 输出')
        self.assertEqual([len(row['controls']) for row in prepared['groups']], [5, 5, 5, 1])
        self.assertEqual([ref for row in prepared['groups'] for ref in row['controls']], ['K' + str(i) for i in range(16)])
        self.assertEqual(source.read_bytes(), original)
        self.assertFalse(prepared['native_processes_launched'])
        source_parts = {part['ref']: part for part in Circuit.open(source).components()}
        for row in prepared['groups']:
            self.assertEqual(set(row['bindings']), set(row['controls']))
            slots = [value for binding in row['bindings'].values() for value in binding.values()]
            self.assertEqual(len(slots), len(set(slots)))
            parts = {part['ref']: part for part in Circuit.open(row['project']).components()}
            self.assertEqual(parts['K15']['properties']['STATE'], source_parts['K15']['properties']['STATE'])
            program = parts['U1']['properties']['PROGRAM']
            self.assertFalse(Path(program).is_absolute())
            self.assertTrue(program.isascii())
            image = Path(row['project']).parent / program
            self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(), row['firmware']['U1']['sha256'])

    def test_invalid_controls_and_existing_destination_fail_before_publication(self):
        source = self.source(2)
        for controls, size, expected in [(['K0', 'K0'], 5, ValueError), (['MISSING'], 5, KeyError),
                                          (['K0'], True, ValueError), (['K0'], 6, ValueError)]:
            target = self.root / 'not-created'
            with self.subTest(controls=controls, size=size), self.assertRaises(expected):
                prepare_control_batches(source, target, controls=controls, batch_size=size)
            self.assertFalse(target.exists())
        target = self.root / 'existing'
        target.mkdir()
        marker = target / 'user.txt'
        marker.write_text('preserve')
        with self.assertRaises(FileExistsError):
            prepare_control_batches(source, target)
        self.assertEqual(marker.read_text(), 'preserve')

    def test_failed_group_preparation_does_not_publish_a_partial_destination(self):
        source = self.source(6)
        original = source.read_bytes()
        from proteus86.digital import prepare_run
        calls = []

        def fail_second(*args, **options):
            calls.append(True)
            if len(calls) == 2:
                raise RuntimeError('synthetic second-batch failure')
            return prepare_run(*args, **options)

        destination = self.root / 'failed'
        with patch('proteus86.digital.prepare_run', side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, 'second-batch'):
                prepare_control_batches(source, destination)
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob('.p86-controls-*')), [])
        self.assertEqual(source.read_bytes(), original)

    def test_unrecognized_key_property_is_not_silently_removed(self):
        source = self.source(2)
        c = Circuit.open(source)
        c.set_properties('K0', KEY='custom-property')
        invalid = c.save(self.root / 'custom-key.pdsprj')
        original = invalid.read_bytes()
        with self.assertRaisesRegex(ValueError, 'refusing to remove'):
            prepare_control_batches(invalid, self.root / 'not-published')
        self.assertFalse((self.root / 'not-published').exists())
        self.assertEqual(invalid.read_bytes(), original)


class Runner:
    next_pid = 10

    def __init__(self):
        self.clock = 0.0
        self.closed = False
        Runner.next_pid += 1
        self.session = SimpleNamespace(pid=Runner.next_pid, process=SimpleNamespace(poll=lambda: 0 if self.closed else None))

    def run_for(self, seconds, **options):
        self.clock = round(self.clock + seconds, 6)
        return self.pause()

    def pause(self):
        return dict(state='paused', simulation_seconds=self.clock)

    def interact(self, *, controls):
        return dict(backend='proteus_native_sdf', simulation_seconds=self.clock,
                    actions=[dict(ref=ref, state=state, changed=True) for ref, state in controls.items()])

    def diagnostics(self):
        return dict(passed=True, errors=[])

    def close(self):
        self.closed = True


class ControlRunnerTests(CircuitFixture):
    def test_all_groups_use_new_owned_contexts_and_actual_native_time(self):
        source = self.source(6)
        sims, calls = [], []

        def opening(*args, **options):
            sim = Runner()
            sims.append(sim)
            return sim

        def callback(sim, ref):
            calls.append(ref)
            sim.run_for(0.03)
            return dict(passed=True, sample='synthetic')

        with patch('proteus86.simulation.Simulation.open', side_effect=opening):
            report = run_control_batches(source, self.root / 'run', callback=callback)
        self.assertTrue(report['passed'])
        self.assertTrue(report['native_run_completed'])
        self.assertEqual(calls, ['K' + str(i) for i in range(6)])
        self.assertEqual(len(sims), 2)
        self.assertTrue(all(sim.closed for sim in sims))
        self.assertTrue(all(row['process_closed'] for row in report['groups']))
        self.assertEqual(report['cases_completed'], 6)
        self.assertTrue(report['source_unchanged'])

    def test_false_callback_or_no_time_progress_is_failed_and_closed(self):
        source = self.source(1)
        for label, callback in [('false', lambda sim, ref: dict(passed=False)),
                                ('stale', lambda sim, ref: dict(passed=True))]:
            sim = Runner()
            with self.subTest(label=label), patch('proteus86.simulation.Simulation.open', return_value=sim):
                report = run_control_batches(source, self.root / label, callback=callback)
            self.assertFalse(report['passed'])
            self.assertFalse(report['native_run_completed'])
            self.assertTrue(sim.closed)
            self.assertFalse(report['groups'][0]['cases'][0]['passed'])
            self.assertEqual(report['status'], 'failed')

    def test_callback_exception_and_interrupt_keep_partial_records_and_close(self):
        source = self.source(1)
        for interruption in (RuntimeError('callback failure'), KeyboardInterrupt('cancel')):
            sim = Runner()
            target = self.root / type(interruption).__name__

            def callback(sim, ref):
                raise interruption

            with patch('proteus86.simulation.Simulation.open', return_value=sim):
                if isinstance(interruption, KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt) as caught:
                        run_control_batches(source, target, callback=callback)
                    self.assertIs(caught.exception, interruption)
                else:
                    result = run_control_batches(source, target, callback=callback)
                    self.assertFalse(result['passed'])
            record = json.loads((target / 'control-results.json').read_text(encoding='utf-8'))
            self.assertFalse(record['passed'])
            self.assertFalse(record['native_run_completed'])
            self.assertEqual(record['cases_completed'], 0)
            self.assertTrue(sim.closed)
            self.assertTrue(record['groups'][0]['process_closed'])

    def test_invalid_callback_does_not_start_or_create_a_run(self):
        source = self.source(1)
        target = self.root / 'never'
        with patch('proteus86.simulation.Simulation.open') as opening:
            with self.assertRaises(TypeError):
                run_control_batches(source, target, callback=None)
        opening.assert_not_called()
        self.assertFalse(target.exists())

    def test_failed_graceful_close_only_terminates_the_owned_process_and_stays_failed(self):
        source = self.source(1)
        sim = Runner()
        sim.close = Mock(side_effect=RuntimeError('close failed'))
        sim.session.process.terminate = Mock(side_effect=lambda: setattr(sim, 'closed', True))
        sim.session.process.wait = Mock(return_value=0)

        def callback(sim, ref):
            sim.run_for(0.01)
            return dict(passed=True)

        with patch('proteus86.simulation.Simulation.open', return_value=sim):
            report = run_control_batches(source, self.root / 'close-failure', callback=callback)
        self.assertFalse(report['passed'])
        self.assertTrue(report['groups'][0]['forced_owned_cleanup'])
        self.assertTrue(report['groups'][0]['process_closed'])
        sim.session.process.terminate.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
