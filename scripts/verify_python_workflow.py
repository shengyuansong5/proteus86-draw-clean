"""End-to-end native validation without Computer Use or screen coordinates."""
import json
import sys
import time
import uuid
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from proteus86 import Circuit, Session, from_spec
from proteus86.verification import verify_netlist

directory = ROOT / 'artifacts' / ('python-workflow-' + uuid.uuid4().hex[:8])
directory.mkdir()
results = []
parser = argparse.ArgumentParser()
parser.add_argument('--only', nargs='+')
args = parser.parse_args()


def validate(name, circuit, *, edit=False):
    if args.only and name not in args.only:
        return
    project = circuit.save(directory / (name + '.pdsprj'), title='Python workflow ' + name)
    started = time.perf_counter()
    print('Checking', name, flush=True)
    session = Session(project)
    try:
        netlist = session.export_netlist(directory / (name + '.sdf'))
        result = dict(name=name, pid=session.pid, project=str(project), **verify_netlist(circuit, netlist))
        if edit:
            actual = session.set_properties('R1', VALUE='22k')
            assert actual['value'] == '22k'
            session.save()
            result['native_adi_value'] = actual['value']
        session.close()
        reopened = Circuit.open(project)
        result['reopened_parts'] = len(reopened.components())
        result['elapsed_seconds'] = round(time.perf_counter() - started, 3)
        results.append(result)
        (directory / 'result.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print('PASS', name, result['elapsed_seconds'], 'seconds', flush=True)
    finally:
        if session.process.poll() is None:
            # No user's process is attached to this session. Preserve its project.
            session.process.terminate()
            session.process.wait(timeout=5)


for name in ('rc', 'led', 'mcu'):
    spec = json.loads((ROOT / 'proteus86/examples' / (name + '.json')).read_text(encoding='utf-8'))
    validate(name, from_spec(spec), edit=name == 'rc')

c = Circuit()
with c.batch():
    c.add_mm('RESISTOR', 'R1', '1k', 0, 0)
    c.add_mm('RESISTOR', 'R2', '2k', 50.8, 0)
    c.add_mm('CAPACITOR', 'C_BLOCK1', '100n', 25.4, 5.08)
    c.connect('R1.2', 'R2.1')
    c.label_wire('R1.2', 'R2.1', 'ROUTED_SENSE')
validate('obstacle_wire_label', c)

c = Circuit()
with c.batch():
    for i in range(8):
        c.add_mm('CAPACITOR', 'C' + str(i + 1), '1u', i * 25.4, 0)
    c.connect_net(*['C' + str(i) + '.1' for i in range(1, 9)])
    c.connect_net(*['C' + str(i) + '.2' for i in range(1, 9)], name='VCC')
validate('eight_cap_bus', c)

print('Native workflow record:', directory / 'result.json', flush=True)
