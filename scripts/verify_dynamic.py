"""Opt-in 30-part native button/debounce/LED-counter and digital-driver acceptance.

Uses independent assembled firmware and Proteus LOGICPROBE observations, never an
offline HEX interpreter. References/course files are not opened by this script.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from proteus86 import Circuit,Scenario,Simulation,prepare_run
from proteus86.inspection import netcheck
from proteus86.verification import verify_netlist
from proteus86.preview import render


def orient(c,ref,pin,direction):
    part=c._parts[c._index(ref)]
    for rotation in (0,90,180,270):
        if c._template(dict(part,rotation=rotation))['pin_directions'][pin]==direction:
            c.rotate(ref,rotation);return
    raise ValueError('Could not orient '+ref)


def fixture(directory):
    image=directory/'中文 固件'/'按键 计数.hex';image.parent.mkdir();shutil.copyfile(ROOT/'examples/key_counter.hex',image)
    c=Circuit();expected=[]
    with c.batch():
        c.add_mm('AT89C52','U1','AT89C52',0,0)
        c.set_property_visibility('U1',PROGRAM=False)
        c.set_properties('U1',PROGRAM=str(image),CLOCK='12MHz')
        c.add_mm('BUTTON','B1','KEY',60,-50)
        c.add_mm('RESISTOR','RP1','10k',40,-50)
        c.add_mm('LOGICPROBE','PI1','INPUT',80,-50)
        c.bind_controls('B1')
        for index in range(8):
            row=25-index*15.24
            r,d,p='R'+str(index+1),'D'+str(index+1),'P'+str(index)
            c.add_mm('RESISTOR',r,'330',-70,row);orient(c,r,'2',(1,0))
            c.add_mm('LED-YELLOW',d,'LED'+str(index+1),-90,row);orient(c,d,'K',(1,0))
            c.add_mm('LOGICPROBE',p,'BIT'+str(index),-50,row)
            c.connect_net('U1.'+str(index+1),r+'.2',p+'.D0')
            c.connect_net(r+'.1',d+'.K');c.add_terminal('power','VCC',d+'.A')
            expected.extend([['U1.'+str(index+1),r+'.2',p+'.D0'],[r+'.1',d+'.K'],[d+'.A','VCC']])
        for index in (1,2):
            ref='C'+str(index);c.add_mm('CAPACITOR',ref,'100n',40+(index-1)*25.4,40)
            c.add_terminal('power','VCC',ref+'.2');c.add_terminal('ground','GND',ref+'.1')
            expected.extend([[ref+'.2','VCC'],[ref+'.1','GND']])
        c.connect_net('U1.12','B1.1','RP1.2','PI1.D0')
        c.add_terminal('ground','GND','B1.2');c.add_terminal('power','VCC','RP1.1')
        c.add_terminal('power','VCC','U1.31');c.add_terminal('ground','GND','U1.9')
        expected.extend([['U1.12','B1.1','RP1.2','PI1.D0'],['B1.2','GND'],['RP1.1','VCC'],['U1.31','VCC'],['U1.9','GND']])
        c.configure_power({'GND':0,'VCC':5})
        c.arrange_modules({
            'LED resistor array':dict(rows=[['D'+str(i+1),'R'+str(i+1)] for i in range(8)],origin_mm=[-100,25],pitch_mm=[25.4,15.24]),
            'output probes':dict(rows=[['P'+str(i)] for i in range(8)],origin_mm=[-50,30.08],pitch_mm=[20,15.24]),
            'input':dict(rows=[['RP1','B1']],origin_mm=[40,-60],pitch_mm=[25.4,15.24]),
            'input probe':dict(rows=[['PI1']],origin_mm=[90,-45],pitch_mm=[20,15.24]),
            'supply':dict(rows=[['C1','C2']],origin_mm=[40,40],pitch_mm=[25.4,15.24])})
    c.tidy_labels();c.fit_sheet()
    source=c.save(directory/'计数 电路.pdsprj')
    assert len(c.components())==30
    assert netcheck(source,expected)['passed']
    render(source,source.with_suffix('.svg'))
    return source,expected


def main():
    directory=ROOT/'artifacts'/('dynamic-acceptance-'+uuid.uuid4().hex[:8]);directory.mkdir()
    results=[]
    source,expected=fixture(directory);before=hashlib.sha256(source.read_bytes()).hexdigest()
    # Prove ordinary resources survive relocation before launching native Proteus.
    shutil.copytree(source.parent/'resources',directory/'moved folder'/'resources')
    moved=directory/'moved folder'/'moved.pdsprj';shutil.copyfile(source,moved)
    package=prepare_run(moved,directory/'portable_preflight')
    print('Native 30-part fixture and copied Chinese/space resources',flush=True)
    sim=Simulation.open(moved,directory/'native_counter')
    row=dict(name='button_debounce_counter',source=str(source),source_sha256=before,pid=sim.session.pid,
             portable_preflight=package,file_netcheck=netcheck(source,expected))
    try:
        sim.run_for(.02)
        row['input_initial']=sim.observe(['PI1'])
        assert row['input_initial']['probes']['PI1']==1
        sim.press('B1');sim.run_for(.005)
        row['input_pressed']=sim.observe(['PI1']);assert row['input_pressed']['probes']['PI1']==0
        sim.release('B1');sim.run_for(.05)
        row['input_released']=sim.observe(['PI1']);assert row['input_released']['probes']['PI1']==1
        scene=Scenario().bounce('B1',at=.04,intervals=[.01]*4).bounce('B1',at=.22,intervals=[.01]*4,state=0).hold('B1',at=.36,seconds=.36)
        probes=['P'+str(i) for i in range(8)]
        print('Running bounce, release and long-hold scenario',flush=True)
        result=sim.run_scenario(scene,probes=probes,until=.8,sample_every=.01,
                               expected_sequences={'P0':[1,0,1],'P1':[1,0]},
                               expected_changes={'P0':2,'P1':{'falling':1}},
                               expected_words=['11111111','01111111','10111111'])
        row['scenario']=result
        row['passed']=result['passed']
        row['native_netlist']=verify_netlist(Circuit.open(sim.session.project),sim.session.netlist())
        sim.stop();sim.session.save()
        row['native_save_python_reopen']=Circuit.open(sim.session.project).nets()==Circuit.open(source).nets()
        assert row['native_save_python_reopen']
    except Exception as error:row['passed']=False;row['error']=type(error).__name__+': '+str(error)
    finally:
        sim.close();row['process_closed']=sim.session.process.poll() is not None
        row['source_unchanged']=hashlib.sha256(source.read_bytes()).hexdigest()==before
        results.append(row);(directory/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Counter result:',row['passed'],row.get('error',row.get('scenario',{}).get('error')),flush=True)
    c=Circuit()
    with c.batch():
        c.add_mm('LOGICSTATE','S1','INPUT',0,0);c.add_mm('LOGICPROBE','P1','OUTPUT',25.4,0,rotation=180)
        c.connect_net(('S1',c.pins('S1')[0]['name']),('P1',c.pins('P1')[0]['name']))
        c.bind_controls('S1');c.arrange_labels()
    logic=c.save(directory/'logic.pdsprj');logic_hash=hashlib.sha256(logic.read_bytes()).hexdigest()
    sim=Simulation.open(logic,directory/'native_logic');row=dict(name='logicstate_native',pid=sim.session.pid,passed=False)
    try:
        sim.run_for(.01);states=[sim.observe(['P1'])]
        for value in (True,False):
            sim.set_switch('S1',value);sim.run_for(.01);states.append(sim.observe(['P1']))
        row['states']=states;assert [s['probes']['P1'] for s in states]==[0,1,0]
        row['diagnostics']=sim.diagnostics();row['passed']=row['diagnostics']['passed']
    except Exception as error:row['error']=str(error)
    finally:
        sim.close();row['process_closed']=sim.session.process.poll() is not None
        row['source_unchanged']=hashlib.sha256(logic.read_bytes()).hexdigest()==logic_hash
        results.append(row);(directory/'result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Record:',directory/'result.json',flush=True)
    if not all(r['passed'] and r['process_closed'] and r['source_unchanged'] for r in results):raise SystemExit(1)


if __name__=='__main__':main()
