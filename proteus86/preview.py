"""SVG geometry preview from the saved file, requiring no GUI or plot library."""
import html
import struct
from pathlib import Path

from .api import Circuit
from ._codec.net_objects import decode_net_objects


def svg(project):
    c = Circuit.open(project)
    decoded = decode_net_objects(project)
    points = [pin['position'] for part in c.components() for pin in c.pins(part['ref'])]
    points += [point for wire in decoded['wires'] for point in wire['points']]
    points += [tuple(item['position']) for item in decoded['junctions']]
    if not points:
        points = [(0, 0), (1000000, 1000000)]
    left, right = min(p[0] for p in points)/100000 - 12, max(p[0] for p in points)/100000 + 26
    bottom, top = min(p[1] for p in points)/100000 - 12, max(p[1] for p in points)/100000 + 16
    width, height = right-left, top-bottom
    elements = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{left:g} {-top:g} {width:g} {height:g}" width="1200" height="{max(250,round(1200*height/width))}">',
                '<rect x="-21475" y="-21475" width="42950" height="42950" fill="#fbfcf8"/>',
                '<g stroke-linecap="round" stroke-linejoin="round">']
    def point(p):
        return f'{p[0]/100000:g},{-p[1]/100000:g}'
    for wire in decoded['wires']:
        elements.append('<polyline points="'+' '.join(point(p) for p in wire['points'])+'" fill="none" stroke="#21734c" stroke-width="0.3"/>')
        for label in wire['labels']:
            p = label['position']
            elements.append(f'<text x="{p[0]/100000:g}" y="{-p[1]/100000-1:g}" fill="#21734c" font-size="2.8">{html.escape(label["text"])}</text>')
    for node in decoded['junctions']:
        x,y=node['position']
        elements.append(f'<circle cx="{x/100000:g}" cy="{-y/100000:g}" r="0.6" fill="#21734c"/>')
    for part in c._parts:
        template = c._template(part)
        bounds = template.get('body_bounds')
        if bounds:
            x0,y0,x1,y1=bounds
            if x0 == x1:x0-=127000;x1+=127000
            if y0 == y1:y0-=127000;y1+=127000
            elements.append(f'<rect x="{(part["x"]+x0)/100000:g}" y="{-(part["y"]+y1)/100000:g}" width="{(x1-x0)/100000:g}" height="{(y1-y0)/100000:g}" fill="#fbfcf8" stroke="#9d3535" stroke-width="0.35"/>')
        for pin in c.pins(part['ref']):
            p=pin['position'];direction=pin['direction']
            root=(p[0]-direction[0]*254000,p[1]-direction[1]*254000)
            elements.append(f'<polyline points="{point(p)} {point(root)}" fill="none" stroke="#9d3535" stroke-width="0.25"/>')
            if len(template['pins'])>4:
                elements.append(f'<text x="{p[0]/100000:g}" y="{-p[1]/100000-0.6:g}" font-size="1.5" fill="#777">{html.escape(pin["number"] or pin["name"])}</text>')
        for index, name in enumerate(('reference','value')):
            x,y=struct.unpack_from('<ii',template['text_tails'][index])
            x+=part['x']-template['x'];y+=part['y']-template['y']
            text=part['ref'] if index==0 else part['value']
            elements.append(f'<text x="{x/100000:g}" y="{-y/100000:g}" font-family="Arial,sans-serif" font-size="{3.2 if index==0 else 2.5}" fill="#272c33">{html.escape(text)}</text>')
    for term in decoded['terminals']:
        # This preview shows electrical contact and label, not a replacement for the native symbol renderer.
        p=term['contact']
        elements.append(f'<circle cx="{p[0]/100000:g}" cy="{-p[1]/100000:g}" r="0.8" fill="#2563a1"/>')
        name=term.get('name') or ('GND' if 'GROUND' in str(term.get('symbol','')) else '')
        if name:
            elements.append(f'<text x="{p[0]/100000+1:g}" y="{-p[1]/100000-1:g}" font-size="2.8" fill="#2563a1">{html.escape(name)}</text>')
    elements += ['</g>','</svg>']
    return '\n'.join(elements)


def render(project, destination, *, overwrite=False):
    destination=Path(destination)
    if destination.suffix.lower()!='.svg':
        raise ValueError('Geometry preview destination must end in .svg')
    data=svg(project)
    destination.parent.mkdir(parents=True,exist_ok=True)
    if overwrite and destination.exists():
        raise ValueError('Use a new preview filename to retain the existing artifact')
    with destination.open('x',encoding='utf-8') as stream:
        stream.write(data)
    return destination.resolve()
