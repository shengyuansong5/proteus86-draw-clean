"""Native simulation acceptance. Explicitly launches independent Proteus processes."""
import hashlib
import json
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from proteus86 import Simulation,simulate,Circuit

directory=ROOT/'artifacts'/('simulation-acceptance-'+uuid.uuid4().hex[:8])
directory.mkdir()
results=[]
for name in ('mcu_complex','controller_complex'):
    source=ROOT/'output/runtime_v04'/(name+'_run86.pdsprj')
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    print('Native simulation:',name,flush=True)
    with Simulation.open(source,directory/name) as sim:
        states=[sim.start(),sim.pause()]
        frozen=sim.status()['simulation_seconds']
        assert sim.status()['simulation_seconds']==frozen
        states.append(sim.start())
        states.append(sim.run_for(1))
        states.append(sim.run_for(.25))
        log=sim.diagnostics()
        assert log['passed'] and not log['warnings'],log
        assert any('Read total of 39 bytes' in row['text'] for row in log['entries']),log
        if name=='mcu_complex':
            tiny=directory/'loop.hex';tiny.write_text(':0200000080FE80\n:00000001FF\n')
            reloaded=sim.load_firmware('U1',tiny)
            states.append(sim.run_for(.25))
            changed=sim.diagnostics()
            assert changed['passed'] and any('Read total of 2 bytes' in row['text'] for row in changed['entries']),changed
            sim.load_firmware('U1',ROOT/'examples/blink8051.hex')
            states.append(sim.run_for(.25))
            restored=sim.diagnostics()
            assert any('Read total of 39 bytes' in row['text'] for row in restored['entries'])
        states.append(sim.stop())
        result=dict(name=name,pid=sim.session.pid,states=states,diagnostics=log,passed=True,source_sha256=before)
        if name=='mcu_complex':
            result['firmware_reload']=dict(loaded=reloaded,two_byte_diagnostics=changed,restored_diagnostics=restored)
    result['process_closed']=sim.session.process.poll() is not None
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before
    results.append(result)
    (directory/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS',name,flush=True)

source=ROOT/'output/runtime_v04/controller_complex_run86.pdsprj'
c=Circuit.open(source);c.update('K1',value='RELAY')
broken=c.save(directory/'bad-relay.pdsprj')
negative=simulate(broken,directory/'negative',duration=.25,
                  firmware={'U1':ROOT/'examples/blink8051.hex'})
assert not negative['passed'] and negative['diagnostics']['errors'] and negative['process_closed'],negative
results.append(dict(name='bad_relay_detected',passed=True,native_result=negative))
(directory/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print('PASS bad relay native diagnostics',flush=True)
print('Record:',directory/'result.json',flush=True)
