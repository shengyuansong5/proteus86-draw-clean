"""Opt-in native acceptance of the delivered 03/04/05 coursework firmware.

Creates private, instrumented copies with BUTTON controls and eight LOGICPROBEs.
The delivered circuits/firmware are read-only. Checks the selected runtime
manifest, actual native time and SDF readback; never uses an offline ISA.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PROBES = ['Q' + str(i) for i in range(8)]
PROGRAMS = ('03_KeyModes', '04_Debounce', '05_Interactive')
PROFILES = ('作业2', '实验1课前准备')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def canonical(circuit, remap=False, exclude_probes=False):
    groups = []
    for net in circuit.nets():
        group = []
        for ref, pin in net:
            if exclude_probes and ref in PROBES:
                continue
            if remap and ref in ('K0', 'K1'):
                pin = {'1': 'COM', '2': 'NO'}.get(pin, pin)
            group.append((ref, pin))
        if group:
            groups.append(sorted(group))
    return sorted(groups)


def firmware(circuit, project):
    rows = []
    for part in circuit.components():
        program = part['properties'].get('PROGRAM')
        if program:
            path = (Path(project).parent / program).resolve()
            rows.append(dict(ref=part['ref'], clock=part['properties'].get('CLOCK'),
                             path=str(path), sha256=sha(path)))
    if len(rows) != 1 or rows[0]['ref'] != 'U1':
        raise AssertionError('This coursework fixture requires exactly one U1 firmware image')
    return rows[0]


def instrument(source, destination, board):
    from proteus86 import Circuit, wiringcheck
    from proteus86.inspection import netcheck
    circuit = Circuit.open(source)
    before = canonical(circuit)
    image = firmware(circuit, source)
    expected_parts = 30 if board else 37
    assert len(circuit.components()) == expected_parts
    started = time.perf_counter()
    with circuit.batch():
        for ref in ('K0', 'K1'):
            old = next(p for p in circuit.components() if p['ref'] == ref)
            assert old['device'] == 'SW-SPST', (ref, old['device'])
            connections = [w for w in circuit.connections()
                           if (ref, 'COM') in (w['first'], w['second'])]
            assert len(connections) == 1, ref
            wire = connections[0]
            other = wire['second'] if wire['first'] == (ref, 'COM') else wire['first']
            labels = [label['text'] for label in wire.get('labels', [])]
            assert len(labels) == 1, ref
            for terminal in circuit.terminals():
                if terminal.get('pin') and terminal['pin'][0] == ref:
                    circuit.delete_terminal(terminal['id'])
            circuit.delete_component(ref)
            circuit.add_mm('BUTTON', ref, ref, old['position']['x'] / 100000,
                           old['position']['y'] / 100000)
            part = circuit._parts[circuit._index(ref)]
            angle = next(a for a in (0, 90, 180, 270)
                         if circuit._template(dict(part, rotation=a))['pin_directions']['1'] == (0, 1))
            circuit.update(ref, rotation=angle)
            circuit.connect((ref, '1'), other)
            circuit.label_wire((ref, '1'), other, labels[0])
            circuit.add_terminal('ground', 'GND', (ref, '2'))
        circuit.bind_controls('K0', 'K1')
        for i, ref in enumerate(PROBES):
            circuit.add_mm('LOGICPROBE', ref, 'BIT' + str(i), -100 + i * 30.48, 180)
            circuit.add_terminal('label', 'LED' + str(i + 1) if board else 'P0_' + str(i), ref + '.D0')
        # Native source labels are retained. The probe row is outside all modules.
        circuit.routing_options = dict(circuit.routing_options, avoid_labels=False)
    assert canonical(circuit, remap=True, exclude_probes=True) == before
    circuit.fit_sheet()
    expected = canonical(circuit)
    circuit.save(destination)
    reopened = Circuit.open(destination)
    assert canonical(reopened) == expected
    assert canonical(reopened, remap=True, exclude_probes=True) == before
    copied = firmware(reopened, destination)
    assert copied['sha256'] == image['sha256'] and copied['clock'] == image['clock']
    topology = netcheck(destination, [g for g in expected if len(g) > 1])
    geometry = wiringcheck(destination)
    assert topology['passed'] and geometry['passed'], (topology, geometry)
    return dict(source_sha256=sha(source), instrumented_sha256=sha(destination),
                original_components=expected_parts, instrumented_components=expected_parts + 8,
                equivalent_component_pin_topology=True, saved_reopen_topology_equal=True,
                firmware=image, copied_firmware=copied, file_netcheck=topology,
                wiringcheck=geometry, preparation_seconds=time.perf_counter() - started,
                input_model='SW-SPST replaced by BUTTON only in verification copy',
                observation='LOGICPROBE at LED driver nets; original LEDs retained',
                routing_scope='0.7 batch routes new control/probe connections; retained source paths stay retained')


def make_scene(name):
    from proteus86 import Scenario
    if name == '03_KeyModes':
        scene = (Scenario().press('K0', at=.1).release('K0', at=.6)
                 .press('K1', at=.8).release('K1', at=1.4)
                 .press('K0', at=1.6).press('K1', at=1.6)
                 .release('K0', at=2).release('K1', at=2))
        return scene, 2.2, .05
    if name == '04_Debounce':
        # Both isolated 10 ms pulses must be rejected. Real press/release bounce
        # toggles every 10 ms before settling, followed by a second 600 ms hold.
        scene = (Scenario().hold('K0', at=.02, seconds=.01)
                 .hold('K0', at=.05, seconds=.01)
                 .bounce('K0', at=.1, intervals=[.01] * 4)
                 .bounce('K0', at=.65, intervals=[.01] * 4, state=0)
                 .hold('K0', at=.85, seconds=.6))
        # 20 ms sampling also observes the isolated pulses; all event gaps >=10 ms.
        return scene, 1.6, .02
    if name == '05_Interactive':
        scene = (Scenario().hold('K0', at=.1, seconds=.4)
                 .hold('K1', at=.7, seconds=.5)
                 .hold('K1', at=1.4, seconds=.5)
                 .hold('K1', at=2.1, seconds=.5))
        return scene, 3.3, .025
    raise ValueError('Unknown coursework program: ' + name)


def on_mask(sample, board):
    values = [sample['probes'][ref] for ref in PROBES]
    if any(type(value) is not int or value not in (0, 1) for value in values):
        raise ValueError('Nonbinary/missing probe reading')
    return sum((value if board else 1 - value) << i for i, value in enumerate(values))


def evaluate(name, samples, board):
    pairs = [(s['actual_at'], on_mask(s, board)) for s in samples]
    sequence, changes = [], []
    for at, mask in pairs:
        if not sequence or mask != sequence[-1]:
            sequence.append(mask)
            changes.append((at, mask))
    checks, details = {}, {}

    def window(start, end):
        return [mask for at, mask in pairs if start - 1e-7 <= at <= end + 1e-7]

    def constant(start, end, mask):
        values = window(start, end)
        return bool(values) and all(value == mask for value in values)

    if name == '03_KeyModes':
        checks['idle'] = constant(.02, .08, 0)
        values = window(.18, .57)
        checks['K0_running_led'] = (bool(values) and len(set(values)) >= 2
                                    and all(mask and not mask & (mask - 1) for mask in values))
        checks['K1_flash'] = set(window(.9, 1.37)) == {0, 255}
        checks['both_held_all_on'] = constant(1.7, 1.97, 255)
        checks['idle_after_release'] = constant(2.1, 2.2, 0)
    elif name == '04_Debounce':
        checks['short_10ms_pulses_rejected'] = constant(0, .09, 1)
        checks['two_complete_clicks_only'] = sequence == [1, 2, 4]
        checks['first_long_hold_no_repeats'] = constant(.2, .64, 1)
        checks['second_600ms_hold_no_repeats'] = constant(.9, 1.44, 2)
        checks['bounce_did_not_add_moves'] = len(changes) == 3
        checks['first_release_has_one_response'] = constant(.74, .84, 2)
        checks['second_release_has_one_response'] = constant(1.5, 1.6, 4)
        details['accepted_clicks'] = len(changes) - 1
    elif name == '05_Interactive':
        checks['single_lit_bit'] = bool(pairs) and all(mask and not mask & (mask - 1) for _, mask in pairs)
        indexes = [(at, mask.bit_length() - 1) for at, mask in changes]
        forward, reverse = [], []
        for (a, i), (b, j) in zip(indexes, indexes[1:]):
            if .03 < a and b < .48:
                forward.append((j - i) % 8 == 1)
            if .57 < a:
                reverse.append((j - i) % 8 == 7)
        checks['forward_while_K0_held'] = bool(forward) and all(forward)
        checks['one_direction_change_after_release'] = len(reverse) >= 12 and all(reverse)
        periods = {}
        # Each speed window includes most of the next 500 ms key hold. A
        # repeating or press-triggered speed cycle must fail these observations.
        for label, start, end, target, minimum in (
                ('normal_during_first_speed_hold', .05, 1.18, .15, 4),
                ('slow_during_second_speed_hold', 1.26, 1.88, .3, 1),
                ('fast_during_third_speed_hold', 1.96, 2.58, .075, 5),
                ('normal_after_third_release', 2.66, 3.3, .15, 2)):
            times = [at for at, _ in changes if start <= at <= end]
            intervals = [round(b - a, 6) for a, b in zip(times, times[1:])]
            periods[label] = dict(expected_seconds=target, observed_seconds=intervals)
            checks[label] = len(intervals) >= minimum and all(abs(value - target) <= .030001 for value in intervals)
        details['periods'] = periods
        details['direction_checks'] = dict(forward_steps=len(forward), reverse_steps=len(reverse))
    else:
        raise ValueError('Unknown coursework program: ' + name)
    return dict(passed=bool(samples) and all(checks.values()), checks=checks, details=details,
                compressed_on_masks=sequence, changes=changes,
                coverage='sampled native digital levels; not voltage/brightness or continuous pulse capture')


def audit_native(circuit, sdf):
    from proteus86.verification import verify_netlist
    result = verify_netlist(circuit, sdf)
    expected = [set(tuple(pin) for pin in group) for group in circuit.nets()]
    actual, power, unmapped = [], set(), []
    for net in sdf['nets']:
        group = set()
        for pin in net['pins']:
            try:
                endpoint = circuit._endpoint((pin['ref'], pin['pin']))
            except (ValueError, KeyError):
                assert pin['kind'] == 'PP', pin
                unmapped.append(pin)
                continue
            group.add(endpoint)
            if pin['kind'] == 'PP':
                power.add(endpoint)
        if group:
            actual.append(group)
    normalize = lambda groups: {frozenset(group - power) for group in groups if group - power}
    assert normalize(expected) == normalize(actual), 'Full non-power native pin partition differs'
    return dict(result, full_known_nonpower_pin_partition_equal=True,
                native_power_pins=sorted(power), implicit_power_pins=unmapped)


def timing_checks(scene, report, until, step):
    requested = sorted(scene.actions, key=lambda action: action['at'])
    actual = report['actions']
    action_ok = len(requested) == len(actual) and all(
        a['ref'] == b['ref'] and a['state'] == b['state']
        and b['backend'] == 'proteus_native_sdf' and abs(a['at'] - b['actual_at']) <= .003001
        for a, b in zip(requested, actual))
    samples = report['samples']
    sample_ok = len(samples) == round(until / step) + 1 and all(
        sample['backend'] == 'proteus_native_sdf'
        and abs(sample['requested_at'] - sample['actual_at']) <= .003001 for sample in samples)
    errors = [abs(s['requested_at'] - s['actual_at']) for s in samples]
    return dict(passed=bool(action_ok and sample_ok), action_readbacks=len(actual), samples=len(samples),
                all_action_states_and_times_match=action_ok, all_sample_times_match=sample_ok,
                maximum_sample_timing_error_seconds=max(errors, default=None),
                actual_native_start_seconds=report.get('base_seconds'),
                actual_native_end_seconds=samples[-1]['simulation_seconds'] if samples else None)


def close_owned(sim, row):
    if sim is None:
        return
    try:
        sim.close()
        row['graceful_close'] = True
    except Exception as error:
        row['cleanup_error'] = str(error)
        row['graceful_close'] = False
        if sim.session.process.poll() is None:
            sim.session.process.terminate()
            sim.session.process.wait(timeout=5)
    row['process_closed'] = sim.session.process.poll() is not None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--temp-dir', type=Path, required=True)
    parser.add_argument('--runtime-record', '--speed-record', dest='speed_record', type=Path,
                        default=ROOT / 'docs/validation/v0.8.3.json',
                        help='Acceptance manifest for this exact runtime; historical manifests are preserved')
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    directory, temporary = args.output_dir.resolve(), args.temp_dir.resolve()
    directory.relative_to(ROOT)
    if source_root == directory or source_root in directory.parents:
        raise ValueError('Put evidence outside the delivered coursework tree')
    if directory.drive.upper() != 'D:' or temporary.drive.upper() != 'D:' or not str(temporary).isascii():
        raise ValueError('Use a fresh D-drive output directory and an ASCII D-drive TEMP directory')
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(temporary)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True
    tempfile.tempdir = str(temporary)
    directory.mkdir()
    from proteus86 import Circuit, Simulation, __version__
    record = read(args.speed_record)
    measured_runtime = [item for item in record['code_manifest']
                        if item['path'].endswith('.py') and not item['path'].startswith('tests/')]
    changed = [item['path'] for item in measured_runtime if sha(ROOT / item['path']) != item['sha256']]
    if changed:
        raise RuntimeError('Runtime differs from ' + str(args.speed_record) + ': ' + ', '.join(changed)
                           + '; select the acceptance record for this runtime with --runtime-record')
    report = dict(version=__version__, started_utc=datetime.now(timezone.utc).isoformat(), passed=False,
                  backend='proteus_native_sdf', offline_isa_executor_used=False,
                  exact_measured_runtime_code_unchanged=True, runtime_manifest=measured_runtime,
                  source_root=str(source_root), temp_directory=str(temporary), script_sha256=sha(__file__),
                  source_record=dict(path=str(args.speed_record.resolve()), sha256=sha(args.speed_record)),
                  results=[], limitations=[
                      'Sampled digital states may miss intersample pulses; not voltage/current/LED brightness.',
                      'SW-SPST replaced by BUTTON in private copies; firmware and component-pin nets preserved.',
                      'Tests cover these two coursework profiles and three supplied programs, not arbitrary circuits.',
                      'Source saved paths retained; new control/probe connections use optimized 0.7 routing.'])

    def publish():
        (directory / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    publish()
    # Prepare and validate all six files before any native launch.
    for profile in PROFILES:
        for name in PROGRAMS:
            source = source_root / profile / 'Proteus' / (name + '.pdsprj')
            folder = directory / (('course30' if profile.startswith('实验') else 'course37') + '_' + name)
            folder.mkdir()
            project = folder / 'instrumented.pdsprj'
            print('Prepare:', profile, name, flush=True)
            row = dict(profile=profile, program=name, source=str(source), project=str(project), passed=False)
            report['results'].append(row)
            row['preparation'] = instrument(source, project, profile.startswith('实验'))
            publish()
    for row in report['results']:
        source, project = Path(row['source']), Path(row['project'])
        folder, sim = project.parent, None
        started = time.perf_counter()
        print('Native scenario:', row['profile'], row['program'], flush=True)
        try:
            sim = Simulation.open(project, folder / 'run')
            row['pid'] = sim.session.pid
            circuit = Circuit.open(sim.session.project)
            expected = canonical(circuit)
            row['native_netlist_before'] = audit_native(circuit, sim.session.export_netlist(folder / 'before.sdf'))
            row['run_firmware'] = firmware(circuit, sim.session.project)
            assert row['run_firmware']['sha256'] == row['preparation']['firmware']['sha256']
            assert row['run_firmware']['clock'] == row['preparation']['firmware']['clock']
            row['warmup'] = sim.run_for(.2)
            row['initial_controls'] = sim.controls()
            assert all(p['state'] == 0 and p['bound'] for p in row['initial_controls'])
            scene, until, step = make_scene(row['program'])
            options = {}
            if row['program'] == '04_Debounce':
                words = ['10000000', '01000000', '00100000']
                if not row['profile'].startswith('实验'):
                    words = [''.join('1' if bit == '0' else '0' for bit in word) for word in words]
                options['expected_words'] = words
            scenario = sim.run_scenario(scene, probes=PROBES, until=until, sample_every=step, **options)
            row['scenario'] = scenario
            row['evaluation'] = evaluate(row['program'], scenario['samples'], row['profile'].startswith('实验'))
            row['native_timing'] = timing_checks(scene, scenario, until, step)
            assert scenario['passed'] and scenario['native_run_completed'], scenario.get('error', scenario.get('evaluation'))
            assert scenario['backend'] == 'proteus_native_sdf' and scenario['offline_isa_executor_used'] is False
            assert row['evaluation']['passed'] and row['native_timing']['passed'], row['evaluation']
            row['native_netlist_after'] = audit_native(circuit, sim.session.export_netlist(folder / 'after.sdf'))
            sim.stop()
            sim.session.save()
            reopened = Circuit.open(sim.session.project)
            row['native_saved_python_reopen_topology_equal'] = canonical(reopened) == expected
            assert row['native_saved_python_reopen_topology_equal']
            assert firmware(reopened, sim.session.project)['sha256'] == row['run_firmware']['sha256']
            row['native_saved_project_sha256'] = sha(sim.session.project)
            row['passed'] = True
        except Exception as error:
            row['error'] = type(error).__name__ + ': ' + str(error)
            row['traceback'] = traceback.format_exc()
            if hasattr(error, 'owned_pid'):
                row.update(pid=error.owned_pid, process_closed=error.process_closed)
        finally:
            close_owned(sim, row)
            row['source_unchanged'] = sha(source) == row['preparation']['source_sha256']
            row['instrumented_input_unchanged'] = sha(project) == row['preparation']['instrumented_sha256']
            image = row['preparation']['firmware']
            row['source_firmware_unchanged'] = sha(image['path']) == image['sha256']
            row['wall_seconds'] = time.perf_counter() - started
            row['passed'] = bool(row['passed'] and row.get('graceful_close') and row.get('process_closed')
                                 and row['source_unchanged'] and row['instrumented_input_unchanged']
                                 and row['source_firmware_unchanged'])
            publish()
        print('Completed:', row['profile'], row['program'], row['passed'],
              row.get('error', row.get('evaluation', {}).get('checks')), flush=True)
    report['finished_utc'] = datetime.now(timezone.utc).isoformat()
    report['passed'] = len(report['results']) == 6 and all(row['passed'] for row in report['results'])
    report['all_owned_processes_closed'] = all(row.get('process_closed') for row in report['results'])
    publish()
    print('RECORD:', directory / 'result.json', 'passed:', report['passed'], flush=True)
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
