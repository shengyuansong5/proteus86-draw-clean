"""Complex file generation, editing and optional native Proteus acceptance."""
import argparse
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from proteus86 import Circuit, from_design, parse_design
from proteus86.geometry import wiringcheck
from proteus86.inspection import netcheck
from proteus86.preview import render
from proteus86.repair import check_pin_order


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--native', action='store_true', help='Open independent hidden Proteus instances and export real SDF')
    args = parser.parse_args()
    directory = ROOT / 'artifacts' / ('complex-' + uuid.uuid4().hex[:8])
    directory.mkdir()
    results = []
    for name in ('mcu_complex', 'controller_complex'):
        print('Building:', name, flush=True)
        start = time.perf_counter()
        text = (ROOT / 'proteus86/examples' / (name + '.txt')).read_text()
        design = parse_design(text)
        c = from_design(design)
        c.configure_power({'GND': 0, 'VCC': 5})
        project = c.save(directory / (name + '.pdsprj'), title='Python ' + name)
        topology = netcheck(project, design['nets'])
        geometry = wiringcheck(project)
        pins = check_pin_order(project)
        assert topology['passed'] and geometry['passed'] and pins['passed']
        preview = render(project, project.with_suffix('.svg'))
        result = dict(name=name, project=str(project), preview=str(preview),
                      sha256=hashlib.sha256(project.read_bytes()).hexdigest(),
                      file_seconds=round(time.perf_counter() - start, 3),
                      layout_attempts=c.layout_attempts, topology=topology, geometry=geometry, pin_order=pins)
        if name == 'mcu_complex':
            before = project.read_bytes()
            edited = Circuit.open(project)
            with edited.batch():
                edited.update('R1', value='680')
                edited.rename('R2', 'R_OUT2')
                cd2 = next(part for part in edited.components() if part['ref'] == 'CD2')['position']
                edited.move_mm('CD2', cd2['x'] / 100000 + 5.08, cd2['y'] / 100000)
                edited.arrange_labels()
                edited.arrange_terminals(reposition=True)
                edited.autoroute()
            edited.fit_sheet()
            edited_project = edited.save(directory / 'mcu_complex_edited.pdsprj')
            expected = [[pin.replace('R2.', 'R_OUT2.') for pin in group] for group in design['nets']]
            assert netcheck(edited_project, expected)['passed']
            assert wiringcheck(edited_project)['passed']
            assert project.read_bytes() == before
            result['edited_project'] = str(edited_project)
            result['source_unchanged'] = True
        if args.native:
            from proteus86 import Session
            from proteus86.verification import verify_netlist
            for native_name, native_project in [(name, project)] + ([('mcu_complex_edited', edited_project)] if name == 'mcu_complex' else []):
                print('Native acceptance:', native_name, flush=True)
                native_copy = directory / (native_name + '-native-save.pdsprj')
                original_bytes = native_project.read_bytes()
                with native_copy.open('xb') as target:
                    target.write(original_bytes)
                before_native = Circuit.open(native_copy)
                session = Session(native_copy)
                try:
                    sdf = session.export_netlist(directory / (native_name + '.sdf'))
                    native_report = verify_netlist(before_native, sdf)
                    session.save()
                    session.close()
                    reopened = Circuit.open(native_copy)
                    assert reopened.nets() == before_native.nets()
                    before_parts = {part['ref']: (part['device'], part['value'], part['position'], part['rotation_raw'])
                                    for part in before_native.components()}
                    after_parts = {part['ref']: (part['device'], part['value'], part['position'], part['rotation_raw'])
                                   for part in reopened.components()}
                    assert before_parts == after_parts
                    assert native_project.read_bytes() == original_bytes
                    native_report.update(native_saved_project=str(native_copy), native_save_python_reopen=True,
                                         component_geometry_unchanged=True, source_unchanged=True,
                                         saved_sha256=hashlib.sha256(native_copy.read_bytes()).hexdigest())
                    result.setdefault('native', {})[native_name] = native_report
                finally:
                    if session.process.poll() is None:
                        session.process.terminate()
                        session.process.wait(timeout=5)
        results.append(result)
        (directory / 'result.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print('PASS', name, result['file_seconds'], 'file seconds', flush=True)
    print('Record:', directory / 'result.json', flush=True)


if __name__ == '__main__':
    main()
