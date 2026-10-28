"""Prepared control batches and bounded native multiplexed-display observations.

File preparation never launches Proteus. Runtime helpers use only the supplied
owned Simulation, or newly owned Simulation contexts created by the batch runner.
Reconstructed display frames are digital samples across a time window, not an
instantaneous hardware frame, voltage, current or brightness measurement.
"""
from collections.abc import Mapping
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile

from .api import Circuit
from .firmware import firmware_info, prepare_run
from .interactions import CONTROLS
from .scenarios import microseconds


_BINDINGS = frozenset({'INC', 'DEC', 'KEY'})
_SEGMENTS = dict(zip((0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07,
                     0x7F, 0x6F, 0x77, 0x7C, 0x39, 0x5E, 0x79, 0x71),
                    '0123456789ABCDEF'))
_SEGMENTS.update({0: ' ', 0x40: '-'})


def _sha(path):
    with Path(path).open('rb') as stream:
        result = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def _refs(values, name):
    if isinstance(values, (str, bytes)):
        raise ValueError(name + ' must be a sequence of distinct component references')
    try:
        result = list(values)
    except TypeError as error:
        raise ValueError(name + ' must be a sequence of distinct component references') from error
    if not result or any(not isinstance(ref, str) or not ref for ref in result) or len(set(result)) != len(result):
        raise ValueError(name + ' must contain distinct nonempty component references')
    return result


def _nets(circuit, physical=False):
    return sorted(sorted(tuple(pin) for pin in net) for net in circuit.nets(physical=physical))


def _models(circuit):
    return {part['ref']: dict(device=part['device'], value=part['value'],
                             position=part['position'], rotation_raw=part['rotation_raw'],
                             properties={key: value for key, value in part['properties'].items()
                                         if key not in _BINDINGS | {'PROGRAM'}})
            for part in circuit.components()}


def _firmware(circuit, project, *, portable=False):
    result = {}
    for part in circuit.components():
        program = part['properties'].get('PROGRAM')
        if program:
            path = Path(program)
            if portable and (path.is_absolute() or not program.isascii()):
                raise RuntimeError('Prepared firmware must use ASCII relative paths: ' + part['ref'])
            resolved = path if path.is_absolute() else Path(project).parent / path
            if portable:
                resolved.resolve(strict=True).relative_to(Path(project).parent.resolve())
            info = firmware_info(resolved)
            result[part['ref']] = dict(sha256=info['sha256'], format=info['format'])
    return result


def _owned_stage(stage, parent):
    if stage.resolve().parent != parent.resolve() or not stage.name.startswith('.p86-controls-'):
        raise RuntimeError('Refusing cleanup outside the private control-batch staging directory')


def prepare_control_batches(project, destination, *, controls=None, batch_size=5):
    """Create portable copies with at most five exclusively bound controls each.

    All original INC/DEC/KEY bindings are removed only in the copies, then each
    group receives its own ten-slot allocation. STATE and other model values are
    preserved: prepare an appropriate released-key source for keyboard tests.
    """
    if type(batch_size) is not int or not 1 <= batch_size <= 5:
        raise ValueError('batch_size must be an integer between 1 and 5')
    source = Path(project).resolve(strict=True)
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    digest = _sha(source)
    circuit = Circuit.open(source)
    parts = {part['ref']: part for part in circuit.components()}
    selected = _refs(controls if controls is not None else
                     [ref for ref, part in parts.items() if part['device'] in CONTROLS], 'controls')
    for ref in selected:
        if ref not in parts:
            raise KeyError('Control reference not found: ' + ref)
        if parts[ref]['device'] not in CONTROLS:
            raise NotImplementedError('Verified control batching requires BUTTON/LOGICSTATE: ' + ref)
    original_bindings = {}
    for ref, part in parts.items():
        bindings = {key: value for key, value in part['properties'].items() if key in _BINDINGS}
        for key, value in bindings.items():
            if not isinstance(value, str) or not re.fullmatch('[0-9]', value):
                raise ValueError(ref + '.' + key + ': not a recognized native actuator slot; refusing to remove it')
        if bindings:
            original_bindings[ref] = bindings
    expected, physical, models = _nets(circuit), _nets(circuit, True), _models(circuit)
    images = _firmware(circuit, source)
    groups = [selected[index:index + batch_size] for index in range(0, len(selected), batch_size)]
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.p86-controls-', dir=destination.parent))
    rows = []
    try:
        for index, refs in enumerate(groups):
            folder = stage / ('batch-%02d' % (index + 1))
            bundle = prepare_run(source, folder)
            prepared = Circuit.open(bundle['project'])
            with prepared.batch():
                for part in prepared.components():
                    removals = {key: None for key in _BINDINGS if key in part['properties']}
                    if removals:
                        prepared.update(part['ref'], properties=removals)
                prepared.bind_controls(*refs)
            output = prepared.save(folder / 'controls.pdsprj', portable=False)
            reopened = Circuit.open(output)
            if (_nets(reopened) != expected or _nets(reopened, True) != physical or
                    _models(reopened) != models or _firmware(reopened, output, portable=True) != images):
                raise RuntimeError('Control preparation changed topology, models or firmware')
            bound = {part['ref']: {key: part['properties'][key] for key in _BINDINGS
                                  if key in part['properties']}
                     for part in reopened.components() if any(key in part['properties'] for key in _BINDINGS)}
            if set(bound) != set(refs):
                raise RuntimeError('Unexpected remaining actuator bindings after preparation')
            slots = [value for item in bound.values() for value in item.values()]
            if len(slots) != 2 * len(refs) or len(set(slots)) != len(slots):
                raise RuntimeError('Prepared actuator bindings are not exclusive')
            final_folder = destination / folder.name
            # The outer staging-directory rename changes these absolute paths.
            bundle['project'] = str(final_folder / 'circuit.pdsprj')
            (folder / 'bundle.json').write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding='utf-8')
            rows.append(dict(index=index, controls=refs, project=str(final_folder / 'controls.pdsprj'),
                             project_relative=folder.name + '/controls.pdsprj', bindings=bound,
                             firmware=images, topology_and_models_preserved=True))
        if _sha(source) != digest:
            raise RuntimeError('Source changed while preparing control batches')
        result = dict(passed=True, scope='file_preparation_only', native_processes_launched=False,
                      source=str(source), source_sha256=digest, source_unchanged=True,
                      controls=selected, batch_size=batch_size, original_bindings=original_bindings, groups=rows,
                      limitation='Groups use independent project copies; more than five controls are not operated simultaneously')
        (stage / 'control-batches.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        _owned_stage(stage, destination.parent)
        if destination.exists():
            raise FileExistsError(destination)
        os.rename(stage, destination)
        return result
    finally:
        if stage.exists():
            _owned_stage(stage, destination.parent)
            shutil.rmtree(stage)


def decode_seven_segment(value, *, segment_active_low=False):
    """Decode one digital byte ordered A,B,C,D,E,F,G,DP; no native I/O."""
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError('Seven-segment value must be an integer byte')
    if type(segment_active_low) is not bool:
        raise ValueError('segment_active_low must be a boolean')
    normalized = value ^ (0xFF if segment_active_low else 0)
    code = normalized & 0x7F
    if code not in _SEGMENTS:
        raise ValueError('Unrecognized seven-segment pattern 0x%02X; check A..DP order and polarity' % code)
    return dict(character=_SEGMENTS[code], decimal_point=bool(normalized & 0x80),
                raw=value, normalized_code=normalized)


class DisplaySamplingError(RuntimeError):
    """A failed/incomplete digital display observation, with partial evidence."""
    def __init__(self, message, report):
        super().__init__(message)
        self.report = report


def _time(observation):
    if 'simulation_seconds' not in observation:
        raise ValueError('observe() returns simulation_seconds; actual_at belongs to scenario samples')
    value = observation['simulation_seconds']
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('A finite native simulation_seconds value is required')
    return float(value)


def read_display_frame(sim, *, segments, digits, digit_active_low=True, segment_active_low=False,
                       sample_seconds=0.002, max_samples=256, stable_frames=2,
                       max_native_seconds=0.5, timeout=30):
    """Reconstruct adjacent stable observation rounds, leaving the engine paused.

    Each round covers every digit at least once; two or more matching rounds
    are required. A round can span physical scan cycles. Small deterministic
    interval dither reduces fixed-period aliasing without claiming to eliminate
    every alias. Both sample count and actual native elapsed time are bounded.
    """
    from .simulation import validate_duration
    segment_refs = _refs(segments, 'segments')
    digit_refs = _refs(digits, 'digits')
    if len(segment_refs) not in (7, 8) or not 1 <= len(digit_refs) <= 32:
        raise ValueError('Use seven/eight A..G[,DP] probes and 1..32 ordered digit-select probes')
    if set(segment_refs) & set(digit_refs):
        raise ValueError('Segment and digit-select probes must be distinct')
    if any(type(value) is not bool for value in (digit_active_low, segment_active_low)):
        raise ValueError('Digit and segment polarity flags must be booleans')
    if type(stable_frames) is not int or not 2 <= stable_frames <= 32:
        raise ValueError('stable_frames must be an integer between 2 and 32')
    if type(max_samples) is not int or not stable_frames * len(digit_refs) <= max_samples <= 10000:
        raise ValueError('max_samples must cover all stable frames and be at most 10000')
    ticks = microseconds(sample_seconds, positive=True)
    bound = microseconds(max_native_seconds, positive=True) / 1e6
    validate_duration(ticks / 1e6, timeout)
    schedule = (ticks / 1e6, (ticks + max(1, ticks // 10) + 1) / 1e6)
    if max(schedule) > bound:
        raise ValueError('max_native_seconds is shorter than a sampling interval')
    report = dict(passed=False, backend='proteus_native_sdf',
                  meaning='stable_reconstructed_multiplexed_digital_frame',
                  atomic_instantaneous_frame=False, segments=segment_refs, digits=digit_refs,
                  digit_active_low=digit_active_low, segment_active_low=segment_active_low,
                  sample_schedule_seconds=list(schedule), samples=[], completed_frames=[],
                  stable_frames=0, requested_stable_frames=stable_frames,
                  max_samples=max_samples, max_native_seconds=bound,
                  window_start_seconds=None, window_end_seconds=None,
                  limitations=['Samples span a native time window and may miss intersample activity.',
                               'A reconstructed round can span several physical multiplexing cycles.',
                               'No voltage, brightness, current or physical-hardware measurement.'])
    in_flight = False
    try:
        paused = sim.pause()
        if paused.get('state') != 'paused':
            raise DisplaySamplingError('Initialize/run the simulation before display observation', report)
        start = _time(paused)
        report['window_start_seconds'] = start
        found, previous_frame, matches = {}, None, 0
        previous_time, requested = None, None
        for index in range(max_samples):
            observation = sim.observe(segment_refs + digit_refs)
            if observation.get('backend') != 'proteus_native_sdf':
                raise ValueError('Display observation requires the proteus_native_sdf backend')
            current = _time(observation)
            resolution = observation.get('time_resolution_seconds') or 0
            if type(resolution) not in (int, float) or not math.isfinite(resolution) or resolution < 0:
                raise ValueError('Invalid native clock resolution')
            if current < start or current - start > bound + resolution / 2 + 1e-9:
                raise DisplaySamplingError('Native display sampling exceeded its time window', report)
            if previous_time is not None:
                tolerance = min(0.0005, requested / 4)
                if current <= previous_time or abs(current - (previous_time + requested)) > tolerance + resolution / 2 + 1e-9:
                    raise DisplaySamplingError('Native time did not advance by the requested sampling interval', report)
            values = observation.get('probes', {})
            invalid = {ref: values.get(ref) for ref in segment_refs + digit_refs
                       if type(values.get(ref)) is not int or values[ref] not in (0, 1)}
            if invalid:
                report['rejected_probe_states'] = invalid
                raise ValueError('Display probes require known binary states: ' + repr(invalid))
            active = [i for i, ref in enumerate(digit_refs) if values[ref] == (0 if digit_active_low else 1)]
            row = dict(simulation_seconds=current, active_digits=active,
                       time_resolution_seconds=resolution,
                       probes={ref: values[ref] for ref in segment_refs + digit_refs})
            report['samples'].append(row)
            report['window_end_seconds'] = current
            if len(active) > 1:
                raise DisplaySamplingError('Multiple digit selects are active; cannot decode a unique digit', report)
            if active:
                normalized = sum((values[ref] ^ segment_active_low) << bit for bit, ref in enumerate(segment_refs))
                decoded = decode_seven_segment(normalized)
                slot, value = active[0], (decoded['character'], decoded['decimal_point'])
                row.update(digit=slot, character=value[0], decimal_point=value[1], segment_code=normalized)
                # A repeated slot changing inside an unfinished reconstruction
                # invalidates that round instead of mixing old and new digits.
                if slot in found and found[slot] != value:
                    found = {}
                found[slot] = value
                if len(found) == len(digit_refs):
                    frame = tuple(found[i] for i in range(len(digit_refs)))
                    text = ''.join(value[0] for value in frame)
                    points = [i for i, value in enumerate(frame) if value[1]]
                    report['completed_frames'].append(dict(text=text, decimal_points=points,
                                                          simulation_seconds=current))
                    matches = matches + 1 if frame == previous_frame else 1
                    previous_frame, found = frame, {}
                    report['stable_frames'] = matches
                    if matches >= stable_frames:
                        diagnostics = sim.diagnostics()
                        report['diagnostics'] = diagnostics
                        if not diagnostics.get('passed'):
                            raise DisplaySamplingError('Native diagnostics reported errors', report)
                        report.update(passed=True, text=text, decimal_points=points,
                                      simulation_seconds=current)
                        break
            if index + 1 >= max_samples:
                break
            step = schedule[index % len(schedule)]
            if current + step - start > bound + 1e-9:
                break
            sim.run_for(step, timeout=timeout, tolerance=min(0.0005, step / 4))
            previous_time, requested = current, step
        if not report['passed']:
            raise DisplaySamplingError('No stable complete display reconstruction within the sample/time bounds', report)
    except BaseException as error:
        in_flight = True
        report.update(passed=False, error=repr(error))
        if not isinstance(error, DisplaySamplingError):
            try:
                error.digital_report = report
            except Exception:
                pass
        if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit, DisplaySamplingError)):
            raise
        raise DisplaySamplingError(str(error), report) from error
    finally:
        try:
            final = sim.pause()
            report['paused_after_sampling'] = final
            if final.get('state') != 'paused':
                raise RuntimeError('Display observation did not leave the native engine paused')
            if report['window_end_seconds'] is not None and _time(final) != report['window_end_seconds']:
                raise RuntimeError('Native time changed after the last display observation')
        except BaseException as error:
            report.update(passed=False, pause_error=repr(error))
            if not in_flight:
                raise DisplaySamplingError('Could not pause after display observation', report) from error
    return report


def run_control_batches(project, destination, *, callback, controls=None, batch_size=5,
                        initialize_seconds=0.2, settle_seconds=0.02, install=None,
                        stop_on_failure=True):
    """Run callback(sim, ref) in independent groups; callbacks assert behavior.

    callback must return a JSON-serializable mapping with passed=True. Every case
    must advance actual native time. This is separate sequential batch coverage,
    not simultaneous operation of more than five controls. Exceptions and partial
    runs never pass; KeyboardInterrupt/SystemExit/GeneratorExit are re-raised.
    """
    from .simulation import Simulation, validate_duration
    from .scenario_runner import _write_report
    if not callable(callback):
        raise TypeError('callback must be callable as callback(sim, ref)')
    if type(batch_size) is not int or not 1 <= batch_size <= 5:
        raise ValueError('batch_size must be an integer between 1 and 5')
    initialize = microseconds(initialize_seconds, positive=True) / 1e6
    settle = microseconds(settle_seconds, positive=True) / 1e6
    validate_duration(initialize)
    validate_duration(settle)
    if type(stop_on_failure) is not bool:
        raise ValueError('stop_on_failure must be a boolean')
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    source = Path(project).resolve(strict=True)
    original = _sha(source)
    destination.mkdir(parents=True, exist_ok=False)
    report_path = destination / 'control-results.json'
    report = dict(passed=False, status='preparing', backend='proteus_native_sdf',
                  native_run_completed=False, source=str(source), source_sha256=original,
                  groups=[], cases_completed=0,
                  scope='Sequential independent control groups, not simultaneous operation beyond five controls')
    _write_report(report_path, report, first=True)
    pending_interruption = None

    def persist():
        try:
            _write_report(report_path, report)
        except BaseException as write_error:
            if pending_interruption is not None:
                # A disk/checkpoint failure must not turn Ctrl+C/SystemExit
                # into an ordinary failed return after owned-process cleanup.
                pending_interruption.native_checkpoint_error = repr(write_error)
                raise pending_interruption
            raise

    try:
        prepared = prepare_control_batches(source, destination / 'prepared', controls=controls, batch_size=batch_size)
        report.update(status='running', preparation=prepared)
        persist()
        for group in prepared['groups']:
            row = dict(index=group['index'], controls=group['controls'], passed=False, cases=[])
            report['groups'].append(row)
            sim, interrupted = None, False
            try:
                sim = Simulation.open(group['project'], destination / ('run-%02d' % (group['index'] + 1)), install=install)
                row['pid'] = sim.session.pid
                row['initialization'] = sim.run_for(initialize)
                for ref in group['controls']:
                    case = dict(ref=ref, passed=False)
                    row['cases'].append(case)
                    case['released_inputs'] = sim.interact(controls={item: 0 for item in group['controls']})
                    sim.run_for(settle)
                    case['before'] = sim.pause()
                    if case['before'].get('state') != 'paused':
                        raise RuntimeError('Control case requires a verified paused time: ' + ref)
                    before = _time(case['before'])
                    details = callback(sim, ref)
                    if not isinstance(details, Mapping):
                        raise RuntimeError('Control callback must return a mapping with passed=True: ' + ref)
                    case['result'] = json.loads(json.dumps(dict(details), ensure_ascii=False, allow_nan=False))
                    if details.get('passed') is not True:
                        raise RuntimeError('Control callback must return a mapping with passed=True: ' + ref)
                    case['after'] = sim.pause()
                    after = _time(case['after'])
                    if case['after'].get('state') != 'paused' or after <= before:
                        raise RuntimeError('Control case did not advance actual native time: ' + ref)
                    case['diagnostics'] = sim.diagnostics()
                    if not case['diagnostics'].get('passed'):
                        raise RuntimeError('Native diagnostics reported errors: ' + ref)
                    case['passed'] = True
                    report['cases_completed'] += 1
                    persist()
                row['passed'] = True
            except BaseException as error:
                row.update(passed=False, error=repr(error))
                if sim is None and getattr(error, 'owned_pid', None) is not None:
                    # A constructor can fail after launching PDS, before this
                    # scope receives a Simulation. The constructor cleans up
                    # its exact Popen; never recover by scanning/killing PIDs.
                    row.update(pid=error.owned_pid, startup_failure=True,
                               process_closed=getattr(error, 'process_closed', False))
                    for name in ('owned_startup_cleanup', 'owned_cleanup_error'):
                        if hasattr(error, name):
                            row[name] = getattr(error, name)
                if row['cases'] and not row['cases'][-1]['passed']:
                    row['cases'][-1]['error'] = repr(error)
                partial = getattr(error, 'report', getattr(error, 'digital_report', None))
                if partial is not None:
                    row['partial_observation'] = partial
                if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                    interrupted = True
                    pending_interruption = error
                    raise
            finally:
                closing_interruption = None
                if sim is not None:
                    try:
                        sim.close()
                    except BaseException as error:
                        row.update(passed=False, close_error=repr(error))
                        if not interrupted and isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                            closing_interruption = error
                    try:
                        if sim.session.process.poll() is None:
                            # This exact Popen belongs to Simulation.open above;
                            # never enumerate or target unrelated PDS processes.
                            row.update(passed=False, forced_owned_cleanup=True)
                            sim.session.process.terminate()
                            sim.session.process.wait(timeout=5)
                        row['process_closed'] = sim.session.process.poll() is not None
                    except BaseException as error:
                        row.update(passed=False, process_closed=False, cleanup_error=repr(error))
                        if not interrupted and isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                            closing_interruption = error
                    if not row['process_closed']:
                        row['passed'] = False
                if closing_interruption is not None:
                    pending_interruption = closing_interruption
                persist()
                if closing_interruption is not None:
                    raise closing_interruption
            if not row['passed'] and stop_on_failure:
                break
        complete = len(report['groups']) == len(prepared['groups']) and all(row['passed'] for row in report['groups'])
        report.update(passed=complete, native_run_completed=complete,
                      status='completed' if complete else 'failed')
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
            pending_interruption = error
        report.update(passed=False, native_run_completed=False,
                      status='interrupted' if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)) else 'failed',
                      error=repr(error))
        if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
            raise
    finally:
        try:
            report['source_unchanged'] = source.is_file() and _sha(source) == original
        except OSError as error:
            report.update(source_unchanged=False, source_check_error=repr(error))
        if not report['source_unchanged']:
            report.update(passed=False, native_run_completed=False, status='failed')
        persist()
    return report
