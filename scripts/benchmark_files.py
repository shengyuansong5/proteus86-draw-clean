"""Measure the verified file pipeline; never starts Proteus or overwrites results."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from proteus86 import __version__, from_design, parse_design, Circuit, wiringcheck
from proteus86.inspection import netcheck
from proteus86.preview import render


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeat', type=int, default=3, choices=range(1, 11))
    args = parser.parse_args()
    directory = ROOT / 'artifacts' / ('benchmark-' + uuid.uuid4().hex[:8])
    directory.mkdir()
    rows = []
    with patch('subprocess.Popen', side_effect=AssertionError('File benchmark tried to launch an application')):
        for name in ('mcu_complex', 'controller_complex'):
            design = parse_design((ROOT / 'proteus86/examples' / (name + '.txt')).read_text(encoding='utf-8'))
            for i in range(args.repeat):
                start = time.perf_counter()
                circuit = from_design(design)
                generated = time.perf_counter()
                project = circuit.save(directory / (name + '-' + str(i) + '.pdsprj'))
                assert netcheck(project, design['nets'])['passed']
                geometry = wiringcheck(project)
                assert geometry['passed']
                render(project, project.with_suffix('.svg'))
                checked = time.perf_counter()
                source_hash = hashlib.sha256(project.read_bytes()).digest()
                edited = Circuit.open(project)
                with edited.batch():
                    edited.update('R1', value='680')
                    edited.set_properties('U1', PROGRAM=r'firmware\blink8051.hex', CLOCK='12MHz')
                result = edited.save(project.with_name(project.stem + '-edited.pdsprj'))
                assert netcheck(result, design['nets'])['passed']
                assert hashlib.sha256(project.read_bytes()).digest() == source_hash
                row = dict(name=name,iteration=i,project=str(project),
                           generation_seconds=round(generated-start, 4),
                           pipeline_seconds=round(checked-start, 4),
                           edit_save_check_seconds=round(time.perf_counter()-checked, 4),
                           layout_attempts=circuit.layout_attempts,warnings=geometry['warnings'])
                rows.append(row)
                print(json.dumps(row), flush=True)
    report = dict(version=__version__,subprocess_launch_blocked=True,rows=rows,
                  medians={name: {metric: statistics.median(r[metric] for r in rows if r['name']==name)
                                  for metric in ('generation_seconds','pipeline_seconds','edit_save_check_seconds')}
                           for name in ('mcu_complex','controller_complex')})
    path = directory / 'result.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Record:', path, flush=True)


if __name__ == '__main__':
    main()
