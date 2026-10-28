"""Generate independent MCU simulation fixtures without starting Proteus.

The checked-in HEX was compiled from examples/blink8051.a51 with Keil A51.
Proteus simulation must still be started and verified in the real application.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from proteus86 import from_design, parse_design, wiringcheck
from proteus86.inspection import netcheck
from proteus86.preview import render


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='A new output directory; existing directories are preserved')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    firmware = ROOT / 'examples/blink8051.hex'
    (output / 'firmware').mkdir()
    with (output / 'firmware/blink8051.hex').open('xb') as stream:
        stream.write(firmware.read_bytes())
    for name in ('mcu_complex', 'controller_complex'):
        design = parse_design((ROOT / 'proteus86/examples' / (name + '.txt')).read_text(encoding='utf-8'))
        circuit = from_design(design)
        with circuit.batch():
            circuit.set_properties('U1', PROGRAM=r'firmware\blink8051.hex', CLOCK='12MHz')
            circuit.set_property_visibility('U1', PROGRAM=False, CLOCK=False)
            circuit.configure_power({'GND': 0, 'VCC': 5})
        circuit.tidy_labels()
        project = circuit.save(output / (name + '_run86.pdsprj'), title='Python runtime ' + name)
        topology, geometry = netcheck(project, design['nets']), wiringcheck(project)
        if not topology['passed'] or not geometry['passed']:
            raise RuntimeError(json.dumps(dict(topology=topology, geometry=geometry)))
        render(project, project.with_suffix('.svg'))
        print(json.dumps(dict(project=str(project), components=len(design['parts']),
                              expected_nets=topology['expected_nets'], warnings=geometry['warnings']),
                         ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
