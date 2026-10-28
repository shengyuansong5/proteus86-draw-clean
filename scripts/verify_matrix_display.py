"""Reproduce the independent 8051 matrix/display acceptance on fresh copies.

Default: rebuild the example HEX, generate a probed circuit, check its complete
29-net topology and prepare independent control groups; no Proteus is launched.

Native execution requires --execute-native and a NEW absolute ASCII --temp-dir.
Sixteen keys run sequentially in groups of 5/5/5/1, never simultaneously. Optional
--capture also needs an unlocked, connected interactive desktop and brings only
the owned Proteus window forward. Images do not replace digital assertions.

Files stay in the explicitly chosen output/temp directories; preparation uses
output-dir/tmp and never silently falls back to system TEMP. Supply a compatible
local Proteus installation/template through the documented environment
variables. No vendor or private fixtures are bundled. The native temp path may
use any drive selected explicitly by the caller.

Examples (choose new directories on a drive available to you):
  python scripts/verify_matrix_display.py --output-dir output/matrix-file-new
  python scripts/verify_matrix_display.py --output-dir output/matrix-native-new --execute-native --temp-dir D:/ProteusTemp/matrix-native-new
"""
import argparse
from contextlib import contextmanager
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __package__ in ('proteus86_support.scripts', '_proteus86_checkout_support.scripts'):
    from importlib import import_module
    _support = __package__.rsplit('.', 1)[0]
    build_firmware = import_module(_support + '.examples.build_matrix_firmware').build
    generate = import_module(_support + '.examples.draw_matrix_display').generate
else:
    from examples.build_matrix_firmware import build as build_firmware
    from examples.draw_matrix_display import generate
from proteus86 import __version__
from proteus86.digital import prepare_control_batches, read_display_frame, run_control_batches
from proteus86.inspection import netcheck


KEYS = tuple('K' + str(index) for index in range(16))
INITIAL = '01234567'
GROUP_SIZES = [5, 5, 5, 1]
INITIALIZE_SECONDS = .2  # The batch runner then releases/settles for .02 s.
SETTLE_SECONDS = .02
HOLD_SECONDS = .12
_INTERRUPTIONS = (KeyboardInterrupt, SystemExit, GeneratorExit)


class VerificationCancelled(RuntimeError):
    """A caller's progress callback explicitly cancelled further verification."""


def _require(condition, message):
    if not condition:
        raise RuntimeError(message)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _recording_failure(original, phase, error):
    """Annotate an exception already unwinding; never replace it with I/O."""
    try:
        failures = list(getattr(original, 'verification_record_errors', []))
        failures.append(dict(phase=phase, type=type(error).__name__, message=str(error)))
        original.verification_record_errors = failures
        if hasattr(original, 'add_note'):
            original.add_note('Verification record failed at ' + phase + ': ' + repr(error))
    except BaseException:
        pass


def _launch_evidence(report):
    """Observed owned PIDs prove launch; absent evidence after a call is unknown."""
    groups = _native_groups(report)
    pids = [group.get('pid') for group in groups]
    startup = report.get('native_startup_error', {})
    pids.append(startup.get('owned_pid'))
    observed = sorted({pid for pid in pids if type(pid) is int and pid > 0})
    called = report['native_runner_called']
    report.update(native_pids_observed=observed, native_processes_observed=bool(observed),
                  native_processes_launched=True if observed else None if called else False,
                  native_launch_state='observed' if observed else 'unknown' if called else 'not_attempted')


def _native_groups(report):
    native = report.get('native_result')
    groups = native.get('groups') if isinstance(native, dict) else None
    return [group for group in groups if isinstance(group, dict)] if isinstance(groups, list) else []


def _observed_initialization_time(report):
    for group in _native_groups(report):
        initialization = group.get('initialization')
        if not isinstance(initialization, dict):
            continue
        elapsed = initialization.get('elapsed_seconds')
        if (initialization.get('state') == 'paused' and type(elapsed) in (int, float) and
                math.isfinite(elapsed) and elapsed > 0):
            return True
    return False


def _capture_preflight():
    # Check the installed API's owned-window capability without grabbing a
    # screen or starting a native process. Non-capture modes never import PIL.
    from proteus86.capture import _require_window_capture
    _require_window_capture()


def _write(path, value):
    """Publish a complete JSON snapshot atomically inside its owned directory."""
    path = Path(path)
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name + '-', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _temporary_environment(directory):
    previous = {key: os.environ.get(key) for key in ('TEMP', 'TMP', 'PYTHONDONTWRITEBYTECODE')}
    old_tempdir, old_bytecode = tempfile.tempdir, sys.dont_write_bytecode
    try:
        os.environ['TEMP'] = os.environ['TMP'] = str(directory)
        os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
        tempfile.tempdir, sys.dont_write_bytecode = str(directory), True
        yield
    finally:
        tempfile.tempdir, sys.dont_write_bytecode = old_tempdir, old_bytecode
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _paths(output_dir, temp_dir, execute_native, capture):
    if type(execute_native) is not bool or type(capture) is not bool:
        raise ValueError('execute_native and capture must be booleans')
    if capture and not execute_native:
        raise ValueError('--capture requires --execute-native and an unlocked interactive desktop')
    output = Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError('Output directory must be new: ' + str(output))
    if execute_native and temp_dir is None:
        raise ValueError('--execute-native requires an explicitly supplied new absolute ASCII --temp-dir')
    if temp_dir is not None and not Path(temp_dir).is_absolute():
        raise ValueError('--temp-dir must be an explicitly supplied absolute path')
    temporary = Path(temp_dir).resolve() if temp_dir is not None else None
    if temporary is not None:
        if not str(temporary).isascii():
            raise ValueError('--temp-dir must be a new absolute ASCII directory')
        if temporary.exists():
            raise FileExistsError('Temporary run directory must be new: ' + str(temporary))
        if output == temporary or output in temporary.parents or temporary in output.parents:
            raise ValueError('Output and temporary run directories must be separate, non-nested new directories')
    return output, temporary


def contract_check(metadata):
    """Validate this example's call contract; introspection never runs native I/O."""
    _require(metadata.get('bundled_firmware') is True or metadata.get('independent_example_code_verified') is True,
             'This verifier requires the independently verified example firmware')
    _require(metadata.get('keys') == list(KEYS), 'Expected exactly K0..K15 in row-major order')
    _require(metadata.get('initial_display') == INITIAL, 'Unexpected initial display contract')
    _require(metadata.get('segment_probes') == ['PS' + str(i) for i in range(8)], 'Expected PS0..PS7 for A..DP')
    _require(metadata.get('digit_probes') == ['PD' + str(i) for i in range(8)], 'Expected PD0..PD7 for digits 1..8')
    _require(metadata.get('segment_active_low') is False and metadata.get('digit_active_low') is True,
             'Expected high-active segments and low-active digit selects')
    _require(metadata.get('recommended_stable_press_seconds') == .08 and
             metadata.get('recommended_stable_release_seconds') == .08, 'Unexpected firmware settling contract')
    options = dict(segments=metadata['segment_probes'], digits=metadata['digit_probes'],
                   segment_active_low=False, digit_active_low=True,
                   sample_seconds=.002, max_samples=256, stable_frames=2,
                   max_native_seconds=.5, timeout=30)
    inspect.signature(read_display_frame).bind(object(), **options)
    inspect.signature(run_control_batches).bind(
        Path('source.pdsprj'), Path('new-batches'), callback=lambda sim, ref: {'passed': False},
        controls=metadata['keys'], batch_size=5, initialize_seconds=INITIALIZE_SECONDS,
        settle_seconds=SETTLE_SECONDS, stop_on_failure=True)
    return dict(passed=True, scope='file_and_call_contract_only', native_processes_launched=False,
                simulation_executed=False, frame_options=options, controls=list(KEYS),
                firmware_basis=('fresh_assembly_address_byte_equivalence' if
                                metadata.get('independent_example_code_verified') is True else 'bundled_file_identity'),
                group_sizes=GROUP_SIZES, press_seconds=.08, hold_seconds=HOLD_SECONDS,
                release_seconds=.08, short_pulse_seconds=.003,
                bounce_cycles=3, bounce_pressed_seconds=.002, bounce_released_seconds=.003)


def make_callback(metadata, evidence_dir, *, progress=None, capture=False):
    """Assert the independent firmware's finite single-key scenarios.

    progress receives complete, already-saved case snapshots. False cancels;
    exceptions and interruptions preserve partial records and remain unpassed.
    The batch runner owns simulation creation, native time checks and cleanup.
    """
    if type(capture) is not bool:
        raise ValueError('capture must be a boolean')
    if progress is not None and not callable(progress):
        raise TypeError('progress must be callable or None')
    contract = contract_check(metadata)
    directory = Path(evidence_dir)
    current_sim, accepted_count = None, 0
    state = dict(serial=0, cases_completed=0, reconstructed_frames=0, native_sdf_samples=0, cancelled=False)

    def callback(sim, ref):
        nonlocal current_sim, accepted_count
        _require(ref in KEYS, 'Unexpected key reference: ' + str(ref))
        state['serial'] += 1
        case = dict(ref=ref, passed=False, status='running', scope='proteus_native_single_key_matrix_display', records=[])
        path = directory / ('case-%02d-%s.json' % (state['serial'], ref))
        pending_error = None

        def checkpoint(phase):
            _write(path, case)
            if progress is not None:
                update = dict(phase=phase, ref=ref, record=str(path), case=case, summary=state)
                # The receiver cannot mutate the recorded evidence.
                if progress(json.loads(json.dumps(update, allow_nan=False))) is False:
                    state['cancelled'] = True
                    raise VerificationCancelled('Progress callback cancelled at ' + ref + '/' + phase)

        def record(kind, value):
            case['records'].append(dict(kind=kind, value=value))
            checkpoint(kind)
            return value

        def interact(phase, pressed):
            value = record(phase, sim.interact(controls={ref: pressed}))
            actions = value.get('actions', [])
            _require(value.get('backend') == 'proteus_native_sdf' and len(actions) == 1 and
                     actions[0].get('ref') == ref and actions[0].get('state') == pressed,
                     'Missing native actuator readback: ' + phase)
            return value

        def advance(phase, seconds):
            tolerance = min(.0005, seconds / 4)
            value = record(phase, sim.run_for(seconds, tolerance=tolerance))
            elapsed = value.get('elapsed_seconds')
            _require(value.get('state') == 'paused' and type(elapsed) in (int, float) and
                     math.isfinite(elapsed) and abs(elapsed - seconds) <= tolerance + 1e-9,
                     'Native time did not complete the requested interval: ' + phase)
            return value

        def frame(phase, expected):
            try:
                reading = read_display_frame(sim, **contract['frame_options'])
            except BaseException as error:
                partial = getattr(error, 'report', getattr(error, 'digital_report', None))
                if partial is not None:
                    try:
                        record(phase + '_partial_sampling', partial)
                    except BaseException as recording_error:
                        _recording_failure(error, phase + '_partial_sampling', recording_error)
                raise
            record(phase, reading)
            _require(reading.get('passed') is True and reading.get('backend') == 'proteus_native_sdf' and
                     reading.get('atomic_instantaneous_frame') is False, 'Invalid native frame evidence: ' + phase)
            _require(reading.get('text') == expected and reading.get('decimal_points') == [],
                     phase + ': expected ' + expected + ', observed ' + repr(reading.get('text')))
            _require(type(reading.get('stable_frames')) is int and reading['stable_frames'] >= 2 and
                     len(reading.get('completed_frames', [])) >= 2,
                     'Display must contain at least two agreeing complete reconstructions')
            _require(all(item.get('text') == expected and item.get('decimal_points') == []
                         for item in reading['completed_frames'][-2:]),
                     'The last two complete display reconstructions do not agree')
            start, end, current = (reading.get(key) for key in
                                   ('window_start_seconds', 'window_end_seconds', 'simulation_seconds'))
            _require(all(type(value) in (int, float) and math.isfinite(value) for value in (start, end, current)) and
                     0 <= start < end == current,
                     'Display reconstruction requires a finite advancing native sampling window')
            state['reconstructed_frames'] += 1
            state['native_sdf_samples'] += len(reading.get('samples', []))
            return reading

        try:
            checkpoint('started')
            if current_sim is not sim:
                current_sim, accepted_count = sim, 0
                frame('initial', INITIAL)
                if capture and ref == KEYS[0]:
                    image = record('running_capture', sim.capture(directory / 'running-initial.png',
                                                                 advance_seconds=.05, foreground=True))
                    _require(image.get('passed') is True and image.get('simulation_executed') is True,
                             'Requested native running capture did not pass')
                if ref == KEYS[0]:
                    interact('short_press', 1)
                    advance('short_advance', .003)
                    interact('short_release', 0)
                    advance('short_settle', .08)
                    frame('short_pulse_rejected', INITIAL)
                    for index in range(3):
                        interact('bounce_%d_press' % index, 1)
                        advance('bounce_%d_high' % index, .002)
                        interact('bounce_%d_release' % index, 0)
                        advance('bounce_%d_low' % index, .003)
                    advance('bounce_settle', .08)
                    frame('bounce_rejected', INITIAL)
            interact('press', 1)
            advance('press_settle', .08)
            accepted_count = (accepted_count + 1) % 16
            expected = '012345' + format(accepted_count, 'X') + format(KEYS.index(ref), 'X')
            advance('long_hold', HOLD_SECONDS)
            held = frame('accepted_press_and_long_hold_single_response', expected)
            interact('release', 0)
            advance('release_settle', .08)
            if ref == KEYS[0]:
                released = frame('stable_release', expected)
                _require(released['simulation_seconds'] > held['simulation_seconds'], 'Release did not advance native time')
                interact('rearm_press', 1)
                advance('rearm_advance', .08)
                accepted_count = (accepted_count + 1) % 16
                expected = '012345' + format(accepted_count, 'X') + '0'
                frame('second_press_after_release', expected)
                interact('rearm_release', 0)
                advance('rearm_release_advance', .08)
                frame('second_stable_release', expected)
            diagnostics = record('diagnostics', sim.diagnostics())
            _require(diagnostics.get('passed') is True, 'Native diagnostics contain errors')
            case['expected_display'] = expected
            # A progress hook can still reject/cancel this completed set of
            # checks. Do not publish a passed case until it has accepted.
            checkpoint('completed')
            case.update(passed=True, status='completed')
            state['cases_completed'] += 1
            return case
        except BaseException as error:
            pending_error = error
            cancelled = isinstance(error, (VerificationCancelled, KeyboardInterrupt, SystemExit, GeneratorExit))
            state['cancelled'] |= cancelled
            case.update(passed=False, status='cancelled' if cancelled else 'failed',
                        error=dict(type=type(error).__name__, message=str(error)))
            raise
        finally:
            try:
                _write(path, case)
            except BaseException as recording_error:
                if case['passed']:
                    state['cases_completed'] -= 1
                case.update(passed=False, status='cancelled' if state['cancelled'] else 'failed',
                            final_record_error=repr(recording_error))
                if pending_error is None:
                    raise
                _recording_failure(pending_error, 'case_final_checkpoint', recording_error)

    callback.state = state
    return callback


def verify(output_dir, *, execute_native=False, temp_dir=None, capture=False, progress=None):
    """Prepare by default; explicitly requested native work retains partial JSON."""
    if progress is not None and not callable(progress):
        raise TypeError('progress must be callable or None')
    output, native_root = _paths(output_dir, temp_dir, execute_native, capture)
    output.mkdir(parents=True, exist_ok=False)
    if native_root is not None:
        native_root.mkdir(parents=True, exist_ok=False)
    temporary = (native_root or output) / 'tmp'
    temporary.mkdir()
    report_path = output / 'result.json'
    report = dict(tool_version=__version__, verifier_sha256=_sha(Path(__file__)),
                  passed=False, status='preparing', scope='file_contract_preparation_only',
                  backend='file', native_execution_requested=execute_native,
                  native_execution_attempted=False, native_processes_launched=False,
                  native_phase_entered=False, native_runner_called=False,
                  native_processes_observed=False, native_pids_observed=[], native_launch_state='not_attempted',
                  native_run_completed=False, simulation_executed=False,
                  temporary_directory=str(temporary),
                  capture_requested=capture, stages=[], case_progress=[],
                  limitations=['Sequential groups of 5/5/5/1; not simultaneous 16-key control.',
                               'Finite debounce/hold windows for the independent example firmware.',
                               'Reconstructed displays span native scan phases and are not atomic frames.',
                               'No voltage, brightness, current or physical hardware validation.'])
    source, callback, pending_interruption = None, None, None

    def checkpoint(phase, details=None):
        report['stages'].append(dict(phase=phase, details=details))
        _write(report_path, report)
        if progress is not None and progress(json.loads(json.dumps(
                dict(phase=phase, record=str(report_path), status=report['status']), allow_nan=False))) is False:
            raise VerificationCancelled('Progress callback cancelled at ' + phase)

    def case_progress(update):
        report['case_progress'].append({key: update[key] for key in ('phase', 'ref', 'record', 'summary')})
        _write(report_path, report)
        return progress(update) if progress is not None else None

    with _temporary_environment(temporary):
        try:
            checkpoint('preparation_started')
            firmware = build_firmware(ROOT / 'examples/matrix_display.a51', output / 'firmware-build',
                                      check_against=ROOT / 'examples/matrix_display.hex')
            report['firmware_build'] = firmware
            checkpoint('firmware_built')
            generated = generate(output / 'source', probes=True, firmware=output / 'firmware-build/matrix_display.hex')
            source = Path(generated['project'])
            report['file_result'] = generated
            report['source_sha256'] = _sha(source)
            metadata = json.loads((source.parent / 'design.json').read_text(encoding='utf-8'))
            expected = json.loads((source.parent / 'expected_nets.json').read_text(encoding='utf-8'))
            report['file_netcheck'] = netcheck(source, expected)
            _require(generated['parts'] == 48 and len(expected) == 29 and report['file_netcheck']['passed'],
                     'Generated circuit must pass the complete 48-part, 29-net contract')
            _require(generated['firmware']['sha256'] == firmware['hex_sha256'], 'Generated firmware differs from rebuilt source')
            _require(firmware.get('reference_address_bytes_equal') is True,
                     'Freshly assembled program must match the independent example at every occupied address')
            # The generator conservatively recognizes its bundled image by raw
            # file hash. Git/ZIP line endings can change an Intel HEX hash while
            # leaving its addressed machine bytes identical. Preserve its raw
            # design.json and create our own explicitly justified contract.
            metadata = dict(metadata, independent_example_code_verified=True,
                            initial_display=INITIAL, recommended_stable_press_seconds=.08,
                            recommended_stable_release_seconds=.08,
                            verification_firmware_sha256=firmware['hex_sha256'],
                            verification_addressed_bytes_sha256=firmware['addressed_bytes_sha256'])
            _write(output / 'verification-contract.json', metadata)
            report['contract'] = contract_check(metadata)
            checkpoint('source_and_contract_checked')
            prepared = prepare_control_batches(source, output / 'prepared-controls', controls=list(KEYS), batch_size=5)
            report['preparation'] = prepared
            _require(prepared['passed'] and [len(group['controls']) for group in prepared['groups']] == GROUP_SIZES and
                     [ref for group in prepared['groups'] for ref in group['controls']] == list(KEYS),
                     'Prepared groups must cover all 16 keys exactly once in groups of 5/5/5/1')
            checkpoint('control_groups_prepared')
            if not execute_native:
                checkpoint('file_checks_completed')
                report.update(passed=True, status='prepared')
            else:
                if capture:
                    _capture_preflight()
                    checkpoint('capture_capability_checked',
                               dict(scope='Python_owned_window_capture_capability_only',
                                    desktop_required='unlocked, connected interactive desktop'))
                evidence = native_root / 'case-evidence'
                evidence.mkdir()
                report.update(status='running', scope='proteus_native_matrix_display', backend='proteus_native_sdf',
                              native_phase_entered=True, native_root=str(native_root))
                checkpoint('native_execution_started')
                callback = make_callback(metadata, evidence, progress=case_progress, capture=capture)
                report.update(native_execution_attempted=True, native_runner_called=True,
                              native_processes_launched=None, native_launch_state='unknown')
                native = run_control_batches(source, native_root / 'batches', callback=callback,
                                             controls=list(KEYS), batch_size=5,
                                             initialize_seconds=INITIALIZE_SECONDS, settle_seconds=SETTLE_SECONDS,
                                             stop_on_failure=True)
                report['native_result'] = native
                report['native_summary'] = dict(callback.state)
                if callback.state['cancelled']:
                    raise VerificationCancelled('Native verification was cancelled')
                complete = (native.get('passed') is True and native.get('native_run_completed') is True and
                            native.get('source_unchanged') is True and native.get('cases_completed') == 16 and
                            [len(group['controls']) for group in native.get('groups', [])] == GROUP_SIZES and
                            all(group.get('passed') and group.get('process_closed') and
                                not group.get('forced_owned_cleanup') for group in native.get('groups', [])) and
                            callback.state['cases_completed'] == 16 and callback.state['reconstructed_frames'] == 25)
                checkpoint('native_execution_completed' if complete else 'native_execution_failed')
                report.update(passed=complete, status='completed' if complete else 'failed', native_run_completed=complete)
        except BaseException as error:
            cancelled = isinstance(error, (VerificationCancelled, KeyboardInterrupt, SystemExit, GeneratorExit))
            if isinstance(error, _INTERRUPTIONS):
                pending_interruption = error
            if report['native_runner_called']:
                startup = {name: getattr(error, name) for name in
                           ('owned_pid', 'process_closed', 'owned_startup_cleanup', 'owned_cleanup_error')
                           if hasattr(error, name)}
                if startup:
                    report['native_startup_error'] = startup
            # The batch runner persists before re-raising an interruption.
            saved = native_root / 'batches/control-results.json' if native_root is not None else None
            try:
                if saved is not None and saved.is_file():
                    recovered = json.loads(saved.read_text(encoding='utf-8'))
                    _require(isinstance(recovered, dict), 'Recovered native result must be a JSON object')
                    report['native_result'] = recovered
                    cancelled |= report['native_result'].get('status') == 'interrupted'
            except BaseException as recovery_error:
                report['native_result_recovery_error'] = repr(recovery_error)
                if pending_interruption is not None:
                    _recording_failure(pending_interruption, 'native_result_recovery', recovery_error)
                elif isinstance(recovery_error, _INTERRUPTIONS):
                    pending_interruption = recovery_error
                    report.update(passed=False, native_run_completed=False, status='cancelled',
                                  error=dict(type=type(recovery_error).__name__, message=str(recovery_error)))
                    raise
            report.update(passed=False, native_run_completed=False,
                          status='cancelled' if cancelled else 'failed',
                          error=dict(type=type(error).__name__, message=str(error)))
            if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                raise
        finally:
            if callback is not None:
                report['native_summary'] = dict(callback.state)
            _launch_evidence(report)
            report['simulation_executed'] = (bool(report.get('native_summary', {}).get('reconstructed_frames')) or
                                             _observed_initialization_time(report))
            if source is not None:
                try:
                    report['source_unchanged'] = source.is_file() and _sha(source) == report['source_sha256']
                except BaseException as error:
                    report.update(source_unchanged=False, source_check_error=repr(error))
                    if pending_interruption is not None:
                        _recording_failure(pending_interruption, 'source_preservation_check', error)
                    elif not isinstance(error, OSError):
                        raise
                if not report['source_unchanged']:
                    report.update(passed=False, status='cancelled' if pending_interruption else 'failed', native_run_completed=False)
            try:
                _write(report_path, report)
            except BaseException as recording_error:
                report.update(passed=False, native_run_completed=False, final_record_error=repr(recording_error))
                if pending_interruption is None:
                    raise
                _recording_failure(pending_interruption, 'verification_final_checkpoint', recording_error)
            if pending_interruption is not None:
                try:
                    pending_interruption.verification_report = report
                except BaseException:
                    pass
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                     allow_abbrev=False)
    parser.add_argument('--output-dir', type=Path, required=True, help='new file/evidence directory')
    parser.add_argument('--execute-native', action='store_true', help='explicitly launch only newly owned Proteus processes')
    parser.add_argument('--temp-dir', type=Path, help='new, separate absolute ASCII directory; required for native execution')
    parser.add_argument('--capture', action='store_true', help='capture the owned running window; requires native mode and an unlocked connected desktop')
    arguments = parser.parse_args(argv)
    try:
        report = verify(arguments.output_dir, execute_native=arguments.execute_native,
                        temp_dir=arguments.temp_dir, capture=arguments.capture)
    except (ValueError, OSError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps({key: report[key] for key in ('passed', 'status', 'scope', 'native_runner_called',
                                                'native_launch_state', 'native_processes_launched',
                                                'native_run_completed', 'simulation_executed')}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
