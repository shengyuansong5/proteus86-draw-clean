"""Opt-in native layout/endpoint-order acceptance; owns every launched process.

Creates fresh copies in a D-drive workspace directory. Does not simulate or edit
coursework. Screenshots are captured only from the owned native editor window.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def route_fixture(directory):
    from proteus86 import Circuit, mm
    c = Circuit()
    with c.batch():
        for row, (method, reverse) in enumerate((('connect', False), ('connect', True),
                ('set_route', False), ('set_route', True), ('auto', True))):
            first, second = 'R'+str(row*2+1), 'R'+str(row*2+2)
            c.add_mm('RESISTOR', first, '1k', 0, -row*30.48)
            c.add_mm('RESISTOR', second, '2k', 50.8, 12.7-row*30.48)
            a = next(p['position'] for p in c.pins(first) if p['name']=='2')
            b = next(p['position'] for p in c.pins(second) if p['name']=='1')
            points = [a, (mm(31.75), a[1]), (mm(31.75), b[1]), b]
            endpoints = (first+'.2', second+'.1')
            if method == 'set_route':
                c.connect(*endpoints)
            if reverse:
                endpoints, points = endpoints[::-1], points[::-1]
            if method == 'auto':
                c.connect(*endpoints)
            else:
                getattr(c, method)(*endpoints, points=points)
        c.arrange_labels()
    c.fit_sheet()
    return c.save(directory/'route-orders.pdsprj')


def models(circuit):
    return {p['ref']:(p['device'],p['value'],p['properties'],p['position'],p['rotation_raw'])
            for p in circuit.components()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layout-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--temp-dir', type=Path, required=True)
    parser.add_argument('--screenshots', action='store_true')
    parser.add_argument('--targets', nargs='+', choices=('before25','ordered25','route-orders10','controller42'))
    args = parser.parse_args()
    if args.targets and 'ordered25' in args.targets and 'before25' not in args.targets:
        parser.error('ordered25 also requires before25 for the native topology/property comparison')
    directory, temporary = args.output_dir.resolve(), args.temp_dir.resolve()
    directory.relative_to(ROOT)
    if directory.drive.upper()!='D:' or temporary.drive.upper()!='D:' or not str(temporary).isascii():
        raise ValueError('Use a fresh D workspace directory and ASCII D TEMP')
    temporary.mkdir(parents=True,exist_ok=True)
    os.environ['TEMP']=os.environ['TMP']=str(temporary)
    os.environ['PYTHONDONTWRITEBYTECODE']='1';sys.dont_write_bytecode=True;tempfile.tempdir=str(temporary)
    directory.mkdir()
    from proteus86 import Circuit, Session, from_design, wiringcheck, wire_quality, __version__
    from proteus86.inspection import netcheck
    from proteus86.repair import check_pin_order
    from scripts.verify_course_dynamic import audit_native
    from scripts.verify_speed_native import capture, close_owned, geometry, sdf_signature
    from examples.draw_8051_neat import topology
    report = dict(version=__version__,passed=False,simulation_executed=False,results=[],
                  script_sha256=sha(__file__),temp_directory=str(temporary))
    manifest = {str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'proteus86').rglob('*.py'))}
    report['runtime_manifest']=manifest
    def publish():
        (directory/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

    mixed = from_design((ROOT/'proteus86/examples/controller_complex.txt').read_text(encoding='utf-8'))
    mixed.bind_firmware('U1',ROOT/'examples/blink8051.hex',visible=False)
    mixed_path = mixed.save(directory/'controller42.pdsprj')
    routes = route_fixture(directory)
    targets = [('before25', args.layout_dir/'before.pdsprj'),
               ('ordered25', args.layout_dir/'after.pdsprj'),
               ('route-orders10', routes), ('controller42', mixed_path)]
    if args.targets:
        targets=[target for target in targets if target[0] in args.targets]
    before_signature = None
    for name, source in targets:
        source=source.resolve();digest=sha(source)
        folder=directory/name;folder.mkdir()
        project=Circuit.open(source).save(folder/'native-save.pdsprj')
        original=Circuit.open(project)
        expected, original_models, original_geometry = topology(original),models(original),geometry(project)
        row=dict(name=name,source=str(source),source_sha256=digest,project=str(project),
                 components=len(original.components()),passed=False,phases=[])
        report['results'].append(row);publish()
        initial_sdf=None
        try:
            for stage in ('save', 'fresh_reopen'):
                print('Native:',name,stage,flush=True)
                phase=dict(name=stage,passed=False);row['phases'].append(phase);session=None
                try:
                    session=Session(project);phase['pid']=session.pid;publish()
                    sdf=session.export_netlist(folder/(stage+'.sdf'))
                    phase['native_netlist']=audit_native(Circuit.open(project),sdf)
                    if stage=='save':
                        initial_sdf=sdf
                        if args.screenshots and name in ('before25','ordered25'):
                            phase['screenshot']=capture(session,folder/'native-editor.png')
                        session.save();phase['native_backup']=str(session.last_backup)
                    else:
                        assert sdf_signature(sdf)==sdf_signature(initial_sdf),'Native SDF changed across reopen'
                        phase['full_native_partition_properties_equal']=True
                    phase['passed']=True
                except Exception as error:
                    if hasattr(error,'owned_pid'):
                        phase.update(pid=error.owned_pid,process_closed=error.process_closed)
                    raise
                finally:
                    close_owned(session,phase);publish()
                assert phase.get('process_closed') and phase.get('graceful_close'),phase
                reopened=Circuit.open(project)
                assert topology(reopened)==expected and models(reopened)==original_models
                assert geometry(project)==original_geometry,'Native save changed wire geometry'
                row['netcheck']=netcheck(project,[g for g in expected if len(g)>1])
                row['wiringcheck']=wiringcheck(project);row['pin_order']=check_pin_order(project)
                row['wire_quality']=wire_quality(project)
                assert row['netcheck']['passed'] and row['wiringcheck']['passed'] and row['pin_order']['passed']
                if name=='ordered25':
                    assert row['wire_quality']['passed'],row['wire_quality']
            if name=='before25':
                before_signature=sdf_signature(initial_sdf)
            if name=='ordered25':
                assert before_signature==sdf_signature(initial_sdf),'Layout changed native properties/connectivity'
                row['before_after_native_partition_properties_equal']=True
            row.update(passed=True,native_save_python_reopen=True,geometry_preserved=True)
        except Exception as error:
            row.update(error=type(error).__name__+': '+str(error),traceback=traceback.format_exc())
        row['source_unchanged']=sha(source)==digest
        print('Completed:',name,row['passed'],row.get('error',''),flush=True);publish()
    report['runtime_unchanged']=all(sha(ROOT/name)==digest for name,digest in manifest.items())
    report['passed']=report['runtime_unchanged'] and all(r['passed'] and r['source_unchanged'] for r in report['results'])
    publish();print('RECORD',directory/'result.json',flush=True)
    if not report['passed']:
        raise SystemExit(1)


if __name__=='__main__':
    main()
