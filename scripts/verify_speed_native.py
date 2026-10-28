"""Native acceptance of the exact projects from the 0.7 file-speed record.

Opt-in: owns its PDS processes, preserves sources, writes only a fresh D folder.
This checks editor/netlist/save compatibility, not simulation behavior.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def canonical_nets(circuit):
    return sorted(sorted(tuple(pin) for pin in group) for group in circuit.nets())


def components(circuit):
    return {p['ref']: (p['device'], p['value'], p['position'], p['rotation_raw']) for p in circuit.components()}


def sdf_signature(sdf):
    # Generated net names may be renumbered. Component pins and named terminal
    # membership must remain identical, including dangling and hidden power pins.
    nets = sorted((sorted((p['ref'], p['pin'], p['kind']) for p in net['pins']),
                   sorted((t['name'], t['kind']) for t in net['terminals'])) for net in sdf['nets'])
    return dict(parts=sdf['parts'], nets=nets)


def geometry(project):
    from proteus86._codec.net_objects import decode_net_objects
    from proteus86.routing import clean
    decoded = decode_net_objects(project)
    wires = []
    for wire in decoded['wires']:
        points = tuple(clean(wire['points']))
        wires.append(min(points, points[::-1]))
    return dict(wires=sorted(wires), junctions=sorted(tuple(x['position']) for x in decoded['junctions']))


def capture(session, destination):
    from PIL import ImageGrab
    from proteus86._codec import proteus_native as native
    window = session._wait(session._ready)
    hwnd = window['hwnd']
    width = min(1600, native.u.GetSystemMetrics(0) - 50)
    height = min(1000, native.u.GetSystemMetrics(1) - 100)
    native.u.SetWindowPos(hwnd, 0, 20, 20, width, height, 0x14)
    native.u.ShowWindow(hwnd, 4)
    time.sleep(.4)
    ImageGrab.grab(window=hwnd).save(destination)
    return dict(file=str(destination), sha256=sha(destination), native_editor=True,
                simulation_executed=False)


def close_owned(session, phase):
    if session is None:
        return
    try:
        session.close()
        phase['graceful_close'] = True
    except Exception as error:
        phase['close_error'] = str(error)
        phase['graceful_close'] = False
        if session.process.poll() is None:
            session.process.terminate()
            session.process.wait(timeout=5)
    phase['process_closed'] = session.process.poll() is not None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', type=Path, required=True, help='Exact historical runtime/fixture manifest supplied by the caller')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--temp-dir', type=Path, required=True)
    parser.add_argument('--include-course', action='store_true')
    parser.add_argument('--screenshots', action='store_true')
    args = parser.parse_args()
    directory, temporary = args.output_dir.resolve(), args.temp_dir.resolve()
    if directory.drive.upper() != 'D:' or temporary.drive.upper() != 'D:' or not str(temporary).isascii():
        raise ValueError('Use a fresh D-drive output folder and an ASCII D-drive temp folder')
    directory.relative_to(ROOT)
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(temporary)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True
    tempfile.tempdir = str(temporary)
    directory.mkdir()

    from proteus86 import Circuit, Session, wiringcheck, __version__
    from proteus86.inspection import netcheck
    from proteus86.preview import render
    from proteus86.repair import check_pin_order
    from proteus86.verification import verify_netlist
    record = read(args.record)
    for item in record['code_manifest']:
        if item['path'].endswith('.py') and not item['path'].startswith('tests/'):
            assert sha(ROOT/item['path']) == item['sha256'], 'Measured runtime changed: '+item['path']
    targets = [dict(name=Path(r['project']).stem, **r) for r in record['native']['prepared_targets']]
    if args.include_course:
        for row in record['course_file_regression']:
            targets.append(dict(name='course'+str(row['components']), project=row['project'],
                                sha256=sha(row['project']), components=row['components']))
    results = []
    started = time.perf_counter()
    summary = dict(version=__version__, source_record=str(args.record.resolve()),
                   temp_directory=str(temporary), simulation_executed=False, results=results)
    for target in targets:
        source = Path(target['project']);digest = sha(source)
        assert digest == target['sha256'], 'Prepared project changed: '+str(source)
        folder = directory/target['name'];folder.mkdir()
        project = folder/'native-save.pdsprj'
        shutil.copyfile(source, project)
        for resource in ('resources', 'firmware'):
            if (source.parent/resource).is_dir():
                shutil.copytree(source.parent/resource, folder/resource)
        before = Circuit.open(project)
        expected, before_parts, before_geometry = canonical_nets(before), components(before), geometry(project)
        row = dict(name=target['name'], components=target['components'], source=str(source),
                   source_sha256=digest, project=str(project), passed=False, phases=[])
        results.append(row)
        sdf_before = None
        print('Native open/save:', target['name'], flush=True)
        try:
            session = None
            phase = dict(name='initial_open_save', process_closed=False)
            row['phases'].append(phase)
            try:
                session = Session(project);phase['pid'] = session.pid
                sdf_path = folder/'before-save.sdf'
                sdf_before = session.export_netlist(sdf_path)
                phase['native_netlist'] = verify_netlist(before, sdf_before)
                phase['sdf'] = dict(path=str(sdf_path), sha256=sha(sdf_path))
                if args.screenshots:
                    row['screenshot'] = capture(session, folder/'native-editor.png')
                session.save()
                row['native_save_backup'] = str(session.last_backup)
                row['saved_sha256'] = sha(project)
            except Exception as error:
                if hasattr(error, 'owned_pid'):
                    phase.update(pid=error.owned_pid, process_closed=error.process_closed)
                raise
            finally:
                close_owned(session, phase)
            assert phase.get('graceful_close') and phase['process_closed'], phase
            reopened = Circuit.open(project)
            row['python_reopen_topology_equal'] = canonical_nets(reopened) == expected
            row['component_geometry_values_equal'] = components(reopened) == before_parts
            row['wire_and_junction_geometry_equal'] = geometry(project) == before_geometry
            row['file_netcheck'] = netcheck(project, [g for g in expected if len(g) > 1])
            row['wiringcheck'] = wiringcheck(project)
            row['pin_order'] = check_pin_order(project)
            render(project, folder/'native-saved.svg')
            assert row['python_reopen_topology_equal'] and row['component_geometry_values_equal']
            assert row['wire_and_junction_geometry_equal'], 'Native save changed wire/junction geometry'
            assert row['file_netcheck']['passed'] and row['wiringcheck']['passed'] and row['pin_order']['passed']

            print('Native fresh reopen:', target['name'], flush=True)
            phase = dict(name='fresh_reopen', process_closed=False)
            row['phases'].append(phase)
            session = None
            saved_digest = sha(project)
            try:
                session = Session(project);phase['pid'] = session.pid
                sdf_path = folder/'after-fresh-reopen.sdf'
                sdf_after = session.export_netlist(sdf_path)
                phase['native_netlist'] = verify_netlist(reopened, sdf_after)
                phase['sdf'] = dict(path=str(sdf_path), sha256=sha(sdf_path))
                row['full_native_pin_partition_and_properties_equal'] = sdf_signature(sdf_after) == sdf_signature(sdf_before)
                assert row['full_native_pin_partition_and_properties_equal'], 'Native SDF changed across fresh reopen'
            except Exception as error:
                if hasattr(error, 'owned_pid'):
                    phase.update(pid=error.owned_pid, process_closed=error.process_closed)
                raise
            finally:
                close_owned(session, phase)
            assert phase.get('graceful_close') and phase['process_closed'], phase
            row['fresh_reopen_did_not_modify_saved_file'] = sha(project) == saved_digest
            assert row['fresh_reopen_did_not_modify_saved_file']
            row['passed'] = True
        except Exception as error:
            row['error'] = type(error).__name__+': '+str(error)
            row['traceback'] = traceback.format_exc()
        finally:
            row['source_unchanged'] = sha(source) == digest
            row['passed'] = row['passed'] and row['source_unchanged']
            summary['native_wall_seconds'] = round(time.perf_counter()-started, 3)
            summary['passed'] = len(results) == len(targets) and all(r['passed'] for r in results)
            (directory/'result.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        print('PASS' if row['passed'] else 'FAIL', target['name'], row.get('error', ''), flush=True)
    print('Record:', directory/'result.json', flush=True)
    if not summary['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
