"""Acceptance of the saved-file pipeline; Proteus is used only as an oracle."""
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from proteus86 import Circuit,Session,from_design,parse_design,route_file
from proteus86.inspection import netcheck
from proteus86.preview import render
from proteus86.verification import verify_netlist

directory=ROOT/'artifacts'/('file-pipeline-'+uuid.uuid4().hex[:8])
directory.mkdir()
results=[]


def native_check(name,circuit,project):
    print('Native check:',name,flush=True)
    started=time.perf_counter()
    session=Session(project)
    try:
        actual=session.export_netlist(directory/(name+'.sdf'))
        report=dict(name=name,project=str(project),**verify_netlist(circuit,actual))
        session.close()
        report['native_check_seconds']=round(time.perf_counter()-started,3)
        return report
    finally:
        if session.process.poll() is None:
            session.process.terminate();session.process.wait(timeout=5)


for name in ('parallel','mcu_auto'):
    text=(ROOT/'proteus86/examples'/(name+'.txt')).read_text()
    design=parse_design(text)
    started=time.perf_counter()
    placed=from_design(design,route=False)
    source=placed.save(directory/(name+'-placed.pdsprj'))
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    project=route_file(source,directory/(name+'-routed.pdsprj'),design['nets'])
    routed=Circuit.open(project)
    assert routed.components()==placed.components()
    assert hashlib.sha256(source.read_bytes()).hexdigest()==source_hash
    checked=netcheck(project,design['nets']);assert checked['passed'],checked
    render(project,directory/(name+'.svg'))
    file_seconds=time.perf_counter()-started
    report=native_check(name,routed,project)
    report.update(file_pipeline_seconds=round(file_seconds,3),offline_netcheck=checked,source_unchanged=True,placement_unchanged=True)
    results.append(report)
    (directory/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS',name,'file workflow',round(file_seconds,3),'seconds',flush=True)

c=Circuit()
devices=[('1N4007','DIODE'),('2N2222',None),('RELAY',None),('ULN2003A',None),('ATMEGA328P',None),('LOGICSTATE',None),('SW-SPST',None),('CRYSTAL','DEVICE')]
with c.batch():
    for index,(device,library) in enumerate(devices):
        c.add_mm(device,'U'+str(index+1),device,index*100,0,library=library)
    c.arrange_labels()
project=c.save(directory/'device-imports.pdsprj')
report=native_check('device-imports',c,project)
report['devices']=[device for device,library in devices]
results.append(report)
(directory/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print('Acceptance record:',directory/'result.json',flush=True)
