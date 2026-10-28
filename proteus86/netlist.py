"""Convert Protel NETLIST 2.0 into a coordinate-free Proteus 8.6 design."""
import re
import shlex


def parse_protel(text):
    if not text.lstrip('\ufeff \r\n').upper().startswith('PROTEL NETLIST 2.0'):
        raise ValueError('Expected PROTEL NETLIST 2.0')
    parts, nets, block, net, pending = [], [], None, None, None
    keys = {'DESIGNATOR', 'FOOTPRINT', 'PARTTYPE', 'VALUE', 'DESCRIPTION'}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.upper().startswith('PROTEL NETLIST'):
            continue
        if line == '[':
            if block is not None or net is not None:raise ValueError('Nested Protel block')
            block, pending = {}, None
        elif line == ']':
            if block is None or not block.get('DESIGNATOR'):raise ValueError('Malformed Protel component')
            parts.append(block);block=None
        elif line == '(':
            if block is not None or net is not None:raise ValueError('Nested Protel net')
            net={'name':None,'pins':[]}
        elif line == ')':
            if net is None or not net['name'] or not net['pins']:raise ValueError('Malformed Protel net')
            nets.append(net);net=None
        elif block is not None:
            if pending:
                block[pending]=line;pending=None
            elif line.upper() in keys:
                pending=line.upper()
        elif net is not None:
            if net['name'] is None:
                net['name']=line
            else:
                ref,separator,pin=line.split()[0].rpartition('-')
                if not separator or not ref or not pin:raise ValueError('Malformed Protel pin: '+line)
                net['pins'].append((ref,pin))
    if block is not None or net is not None:raise ValueError('Truncated Protel netlist')
    refs={part['DESIGNATOR'] for part in parts}
    if not parts or len(refs)!=len(parts):raise ValueError('Missing or duplicate Protel components')
    if any(ref not in refs for net in nets for ref,pin in net['pins']):raise ValueError('Protel net references an unknown component')
    return parts,nets


def protel_to_design(text, *, device_field='PARTTYPE', device_map=None):
    if device_field not in ('PARTTYPE','FOOTPRINT'):raise ValueError('Choose PARTTYPE or FOOTPRINT for the device field')
    parts,nets=parse_protel(text)
    mapping=device_map or {}
    lines=['[parts]']
    for part in parts:
        device=part.get(device_field)
        if not device:raise ValueError('Missing '+device_field+' for '+part['DESIGNATOR'])
        device=mapping.get(device,device)
        value=part.get('VALUE') or part.get('PARTTYPE') or device
        lines.append(' '.join((part['DESIGNATOR'],shlex.quote(device),shlex.quote(value))))
    lines+=['','[terms]']
    for net in nets:
        name=net['name']
        if ',' in name or not name.isascii():raise ValueError('Design net names must be ASCII and cannot contain commas')
        kind='GROUND' if re.search(r'^(?:[AD]?GND|VSS|0)$',name,re.I) else 'POWER' if re.search(r'^(?:VCC|VDD|VBAT|VBUS|\+?\d+V)',name,re.I) else 'LABEL'
        lines.append(shlex.quote(name)+' '+kind)
    lines+=['','[nets]']
    lines += [','.join([ref+'.'+pin for ref,pin in net['pins']]+[net['name']]) for net in nets]
    result='\n'.join(lines)+'\n'
    from .design import parse_design
    parse_design(result)
    return result
