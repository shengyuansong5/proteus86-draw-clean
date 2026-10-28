"""Conservative, same-length repair of native CDB pin declaration order."""
import struct

from ._codec.proteus_project import Project, _cdb_entity_table_offset, _lp, _need
from ._codec.pin_geometry import symbol_pins
from ._codec.component_codec import _short


def _pin_tables(project):
    data=project._cdb
    start=_cdb_entity_table_offset(data)
    count=struct.unpack_from('<I',data,start)[0]
    position=start+4
    for _ in range(count):
        _need(position+16<=len(data),'Truncated entity header')
        position+=16
        ref,_,position=_lp(data,position)
        n=struct.unpack_from('<I',data,position)[0];position+=4
        _need(n<=256,'Oversized entity pin list')
        left=position;pins=[]
        for _ in range(n):
            name,_,position=_lp(data,position);number,_,position=_lp(data,position)
            pins.append((name,number))
        yield ref,left,position,pins
        position+=12


def check_pin_order(project):
    p=project if isinstance(project,Project) else Project(project)
    issues=[]
    for ref,left,right,pins in _pin_tables(p):
        if ref not in p._components:
            continue
        desired=[pin['name'] for pin in symbol_pins(p._dsn,p._components[ref]['symbol'])]
        actual=[name for name,number in pins]
        _need(len(actual)==len(set(actual)) and set(actual)==set(desired),'CDB pins and symbol names disagree: '+ref)
        if actual!=desired:
            issues.append({'ref':ref,'actual':actual,'expected':desired,'start':left,'end':right})
    return {'passed':not issues,'issues':issues}


def fix_pin_order(source,destination):
    """Reorder CDB name/number pairs only; retain DSN and every other member."""
    p=Project(source)
    report=check_pin_order(p)
    tables={ref:(left,right,pins) for ref,left,right,pins in _pin_tables(p)}
    for issue in report['issues']:
        left,right,pins=tables[issue['ref']]
        numbers=dict(pins)
        data=b''.join(_short(name)+_short(numbers[name]) for name in issue['expected'])
        _need(len(data)==right-left,'Pin-order repair would change member offsets')
        p._cdb[left:right]=data
    _need(check_pin_order(p)['passed'],'Pin-order repair failed validation')
    path=p.save(destination)
    return {'project':str(path),'repaired_components':[issue['ref'] for issue in report['issues']]}
