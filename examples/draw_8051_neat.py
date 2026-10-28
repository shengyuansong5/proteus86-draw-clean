"""A repeatable 25-part 8051 layout: separate modules and eight ordered lanes.

Example profile only: it validates the expected refs/devices before editing.
Uses supported Circuit APIs; never edits teacher/classmate files or launches UI.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def topology(circuit):
    return sorted(sorted(group) for group in circuit.nets())


def arrange(circuit):
    from proteus86 import mm
    required={'U1':'AT89C52','X1':'CRYSTAL','CX1':'CAPACITOR','CX2':'CAPACITOR',
              'CR1':'CAPACITOR','RR1':'RESISTOR','SW1':'SW-SPST','CD1':'CAPACITOR','CD2':'CAPACITOR'}
    required.update({'D'+str(i):'LED-YELLOW' for i in range(1,9)})
    required.update({'R'+str(i):'RESISTOR' for i in range(1,9)})
    actual={part['ref']:part['device'] for part in circuit.components()}
    if actual!=required:raise ValueError('This example layout requires the unchanged 25-part mcu_complex fixture')
    before=topology(circuit)

    def pin_at(ref,pin,x,y):
        part=circuit._parts[circuit._index(ref)]
        offset=circuit._template(part)['pin_offsets'][pin]
        circuit.update(ref,x=mm(x)-offset[0],y=mm(y)-offset[1])

    def orient(ref,pin,direction):
        # Fresh library templates and imported templates have different base
        # orientations. Select by the actual pin exit rather than a fixed angle.
        part=circuit._parts[circuit._index(ref)]
        angle=next(angle for angle in (0,90,180,270)
                   if circuit._template(dict(part,rotation=angle))['pin_directions'][pin]==direction)
        circuit.update(ref,rotation=angle)

    def label_at(ref,x,y):
        part=circuit._parts[circuit._index(ref)]
        circuit.update(ref,label_offsets={'reference':(mm(x)-part['x'],mm(y)-part['y']),
            'value':(mm(x)-part['x'],mm(y-5.08)-part['y']),
            'device':(mm(x)-part['x'],mm(y-5.08)-part['y'])})

    with circuit.batch():
        circuit.update('U1',x=0,y=0)
        for i in range(8):
            led,resistor='D'+str(i+1),'R'+str(i+1)
            orient(led,'K',(1,0));pin_at(led,'K',-116.84,-55.88-i*10.16)
            orient(resistor,'2',(1,0));pin_at(resistor,'1',-91.44,-55.88-i*10.16)
        orient('X1','1',(0,1));pin_at('X1','1',-30.48,-5.08)
        for ref,y in [('CX1',-2.54),('CX2',-17.78)]:
            orient(ref,'2',(1,0));pin_at(ref,'2',-45.72,y)
        orient('CR1','1',(0,-1));pin_at('CR1','1',-71.12,-22.86)
        orient('RR1','2',(0,1));pin_at('RR1','2',-71.12,-27.94)
        orient('SW1','COM',(1,0));pin_at('SW1','COM',-78.74,-25.4)
        for ref,x in [('CD1',60.96),('CD2',86.36)]:
            orient(ref,'2',(0,1));pin_at(ref,'2',x,-5.08)
        circuit.arrange_labels()
        for ref,x,y in [('CX1',-53.34,5.08),('CX2',-53.34,-10.16),
                        ('SW1',-91.44,-33.02),('CR1',-83.82,-12.7)]:
            label_at(ref,x,y)
        for i in range(8):
            # Put both texts in one row above each branch rather than stacking
            # them into the adjacent row's symbol. Preserve all model values.
            for ref,x1,x2 in [('D'+str(i+1),7.62,15.24),('R'+str(i+1),5.08,12.7)]:
                circuit.update(ref,label_offsets={'reference':(mm(x1),mm(2.54)),
                    'value':(mm(x2),mm(2.54)),'device':(mm(x2),mm(2.54))})
        circuit.arrange_terminals(reposition=True)
        # Sideways power/ground glyphs introduced small three-bend hairpins.
        # Keep these reset-module terminals aligned with their vertical pins.
        for ref,pin,dy in [('RR1','1',-5.08),('CR1','2',12.7)]:
            terminal=next(t for t in circuit._terminals if t.get('pin')==(ref,pin))
            tip=next(p['position'] for p in circuit.pins(ref) if p['name']==pin)
            circuit.update_terminal(terminal['id'],position=(tip[0],tip[1]+mm(dy)),rotation=0)
        circuit.autoroute()
        # Ordered lanes fan out in pin order. They avoid crossing neighboring
        # output lanes and stay below the separate clock/reset region.
        for i in range(8):
            ref='R'+str(i+1)
            first=next(pin for pin in circuit.pins(ref) if pin['name']=='2')['position']
            second=next(pin for pin in circuit.pins('U1') if pin['number']==str(i+1))['position']
            lane=mm(-60.96+i*7.62)
            circuit.set_route((ref,'2'),('U1',str(i+1)),[first,(lane,first[1]),(lane,second[1]),second])
    circuit.tidy_labels(max_shift_mm=15.24)
    if topology(circuit)!=before:raise RuntimeError('Layout changed requested pin connectivity')
    return circuit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--source',type=Path)
    args=parser.parse_args()
    directory=args.output_dir.resolve();directory.relative_to(ROOT)
    if directory.drive.upper()!='D:':raise ValueError('Use a new D-drive workspace output directory')
    directory.mkdir();temporary=directory/'tmp';temporary.mkdir()
    os.environ['TEMP']=os.environ['TMP']=str(temporary)
    os.environ['PYTHONDONTWRITEBYTECODE']='1';sys.dont_write_bytecode=True;tempfile.tempdir=str(temporary)
    from proteus86 import Circuit,from_design,wiringcheck,wire_quality
    from proteus86.inspection import netcheck
    from proteus86.preview import render
    if args.source:
        circuit=Circuit.open(args.source)
        digest=hashlib.sha256(args.source.read_bytes()).hexdigest()
    else:
        circuit=from_design((ROOT/'proteus86/examples/mcu_complex.txt').read_text(encoding='utf-8'))
        circuit.bind_firmware('U1',ROOT/'examples/blink8051.hex',visible=False)
        digest=None
    before=circuit.save(directory/'before.pdsprj')
    expected=topology(circuit)
    models=lambda c:{p['ref']:(p['device'],p['value'],p['properties']) for p in c.components()}
    model_before=models(circuit)
    render(before,directory/'before.svg')
    arrange(circuit);circuit.fit_sheet()
    after=circuit.save(directory/'after.pdsprj')
    reopened=Circuit.open(after)
    assert topology(reopened)==expected and models(reopened)==model_before
    topology_check=netcheck(after,[group for group in expected if len(group)>1]);geometry=wiringcheck(after)
    assert topology_check['passed'] and geometry['passed']
    render(after,directory/'after.svg')

    before_quality,after_quality=wire_quality(before),wire_quality(after)
    assert after_quality['passed'],after_quality
    def metrics(path,quality):
        return dict(crossings=len(quality['crossings']),overlaps=len(quality['overlaps']),
                    near_parallel=len(quality['near_parallel']),straight_wires=quality['straight_wires'],
                    wire_length_mm=quality['wire_length_mm'],bends=quality['bends'],
                    warnings=len(wiringcheck(path)['warnings']))
    if args.source:assert hashlib.sha256(args.source.read_bytes()).hexdigest()==digest
    report=dict(passed=True,before=str(before),after=str(after),source=str(args.source) if args.source else None,
                source_unchanged=True,topology_equal=True,models_equal=True,netcheck=topology_check,wiringcheck=geometry,
                metrics=dict(before=metrics(before,before_quality),after=metrics(after,after_quality)),
                wire_quality=dict(before=before_quality,after=after_quality),
                layout_spacing_mm=dict(led_rows=10.16,output_lanes=7.62),label_report=circuit.label_report,
                native_verified=False,scope='Explicit example profile; no universal automatic layout guarantee')
    (directory/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report['metrics']),flush=True)
    print('RECORD',directory/'result.json',flush=True)


if __name__=='__main__':main()
