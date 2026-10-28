"""Saved-file geometry checks, whole-diagram translation and sheet fitting."""
import copy
import math
import struct
import tempfile
from pathlib import Path

from ._codec.proteus_project import _need
from ._codec.net_objects import decode_net_objects
from .routing import Rectangle, collinear_overlap


def sheet_size(circuit):
    root = circuit._root
    _need(circuit._body == root + 47 and circuit._dsn[root + 35:root + 47] == b'OBJECT DATA\0',
          'Unknown sheet-size header layout')
    width, height = struct.unpack_from('<ii', circuit._dsn, root + 25)
    _need(width > 0 and height > 0, 'Invalid sheet dimensions')
    return width, height


def text_box(text, position, owner='', *, reference=False):
    x, y = position
    width = max(127000, len(text) * (170000 if reference else 140000))
    return Rectangle(x - 63500, y - 63500, x + width + 63500, y + 320000, owner)


def geometry(circuit, decoded):
    """Return conservative occupied rectangles and actual wire coordinates."""
    bodies, labels, points = [], [], []
    for part in circuit._parts:
        template = circuit._template(part)
        bounds = template.get('body_bounds')
        if bounds:
            l, b, r, t = bounds
            if l == r:
                l -= 127000; r += 127000
            if b == t:
                b -= 127000; t += 127000
            bodies.append(Rectangle(part['x'] + l, part['y'] + b, part['x'] + r, part['y'] + t, part['ref']))
        points += [pin['position'] for pin in circuit.pins(part['ref'])]
        for index, text in enumerate((part['ref'], part['value'])):
            x, y = struct.unpack_from('<ii', template['text_tails'][index])
            labels.append(text_box(text, (x + part['x'] - template['x'], y + part['y'] - template['y']),
                                   part['ref'] + (':reference' if index == 0 else ':value'), reference=index == 0))
    for index, term in enumerate(decoded['terminals']):
        x, y = term['position']
        bodies.append(Rectangle(x - 127000, y - 127000, x + 127000, y + 127000, '@terminal:' + str(index)))
        if term['name']:
            labels.append(text_box(term['name'], term['label']['position'], '@terminal-label:' + str(index)))
    for index, wire in enumerate(decoded['wires']):
        points += wire['points']
        for label in wire['labels']:
            labels.append(text_box(label['text'], label['position'], '@wire-label:' + str(index)))
    for box in bodies + labels:
        points.extend(((box.left, box.bottom), (box.right, box.top)))
    return bodies, labels, points


def arrange_terminals(circuit, *, reposition=False):
    """Place new terminal glyphs/labels outside all device pin escape zones."""
    from ._codec.net_objects import terminal_markers, terminal_record, read_terminal, TERMINALS
    from ._codec.pin_geometry import transform
    bodies, labels, _ = geometry(circuit, {'terminals': [], 'wires': []})
    occupied = bodies + labels
    for part in circuit._parts:
        for pin in circuit.pins(part['ref']):
            a = pin['position']
            b = tuple(a[i] + pin['direction'][i] * 254000 for i in (0, 1))
            occupied.append(Rectangle(min(a[0], b[0]) - 63500, min(a[1], b[1]) - 63500,
                                      max(a[0], b[0]) + 63500, max(a[1], b[1]) + 63500, part['ref'] + ':pin'))
    def overlap(a, b):
        return a.left < b.right and b.left < a.right and a.bottom < b.top and b.bottom < a.top
    def boxes(record):
        value = read_terminal(record, 0)
        x, y = value['position']
        result = [Rectangle(x - 127000, y - 127000, x + 127000, y + 127000)]
        if value['name']:
            result.append(text_box(value['name'], value['label']['position']))
        return result
    pending = []
    for terminal in circuit._terminals:
        if terminal.get('pin') is None or terminal.get('position') is not None and not reposition:
            contact = circuit._terminal_contact(terminal)
            rotation = terminal.get('rotation') or 0
            record, _ = terminal_record(circuit._dsn, terminal['kind'], terminal['name'], contact, rotation, terminal.get('label'))
            occupied.extend(boxes(record))
        else:
            pending.append(terminal['id'])
    with circuit.batch():
        for identity in pending:
            terminal = next(t for t in circuit._terminals if t['id'] == identity)
            ref, name = terminal['pin']
            pin = next(p for p in circuit.pins(ref) if p['name'] == name)
            direction = pin['direction']
            rotation = terminal.get('rotation')
            if rotation is None:
                node = terminal_markers(circuit._dsn, TERMINALS[terminal['kind']][0])['$MKRNODE']
                rotation = next(angle for angle in (0, 900, 1800, 2700)
                                if tuple((v > 0) - (v < 0) for v in transform(node, angle)) == tuple(-v for v in direction))
            for distance in range(2, 19):
                found = False
                for shift in (0, 4, -4, 8, -8, 12, -12, 16, -16):
                    contact = tuple(pin['position'][i] + direction[i] * distance * 254000
                                    + (direction[1] if i == 0 else -direction[0]) * shift * 254000 for i in (0, 1))
                    record, _ = terminal_record(circuit._dsn, terminal['kind'], terminal['name'], contact, rotation)
                    candidate = boxes(record)
                    if any(overlap(box, other) for box in candidate for other in occupied):
                        continue
                    circuit.update_terminal(identity, position=contact, rotation=rotation // 10)
                    occupied.extend(candidate)
                    found = True
                    break
                if found:
                    break
            else:
                raise ValueError('No unobstructed terminal placement found: ' + identity + ' ' + terminal['name'])


def tidy_labels(circuit, *, max_shift):
    if circuit._batch_depth:
        raise ValueError('Tidy labels after completing the batch')
    if not 0 <= max_shift <= 5080000:
        raise ValueError('Label shift must be between 0 and 50.8 mm')
    with tempfile.TemporaryDirectory(prefix='proteus86-labels-') as directory:
        path = circuit.save(Path(directory) / 'geometry.pdsprj')
        decoded = decode_net_objects(path)
    bodies, labels, _ = geometry(circuit, decoded)
    # Retain the real routes when changing text on a newly generated circuit.
    connections, terminals = _retain_geometry(circuit, decoded)
    pins = []
    for part in circuit._parts:
        for pin in circuit.pins(part['ref']):
            a = pin['position']; b = tuple(a[i] + pin['direction'][i] * 254000 for i in (0, 1))
            pins.append(Rectangle(min(a[0],b[0])-63500,min(a[1],b[1])-63500,
                                  max(a[0],b[0])+63500,max(a[1],b[1])+63500))
    wires = [(a,b) for wire in decoded['wires'] for a,b in zip(wire['points'],wire['points'][1:])]
    def overlap(a,b):
        return a.left < b.right and b.left < a.right and a.bottom < b.top and b.bottom < a.top
    radius = max_shift // 254000
    shifts = sorted(((x*254000,y*254000) for x in range(-radius,radius+1) for y in range(-radius,radius+1)
                     if x*x+y*y <= radius*radius), key=lambda d:(d[0]*d[0]+d[1]*d[1],abs(d[0]),-d[1],d[0]))
    width,height = sheet_size(circuit)
    moved, unresolved = [], []
    with circuit.batch():
        circuit._connections,circuit._terminals = connections,terminals
        for part in list(circuit._parts):
            owners = {part['ref']+':reference',part['ref']+':value'}
            current = [box for box in labels if box.owner in owners]
            obstacles = bodies + pins + [box for box in labels if box.owner not in owners]
            for dx,dy in shifts:
                boxes = [Rectangle(b.left+dx,b.bottom+dy,b.right+dx,b.top+dy,b.owner) for b in current]
                if any(b.left < -width//2 or b.right > width//2 or b.bottom < -height//2+1778000 or b.top > height//2 for b in boxes):
                    continue
                if any(overlap(b,other) for b in boxes for other in obstacles) or any(b.blocks(a,z) for b in boxes for a,z in wires):
                    continue
                if dx or dy:
                    template = circuit._template(part)
                    offsets = dict(part.get('label_offsets', {}))
                    for index,name in enumerate(('reference','value')):
                        x,y = struct.unpack_from('<ii',template['text_tails'][index])
                        offsets[name]=(x-template['x']+dx,y-template['y']+dy)
                    offsets['device']=offsets['value']
                    circuit.update(part['ref'],label_offsets=offsets)
                    moved.append(dict(ref=part['ref'],dx_mm=dx/100000,dy_mm=dy/100000))
                labels = [b for b in labels if b.owner not in owners]+boxes
                break
            else:
                unresolved.append(part['ref'])
    return dict(moved=moved,unresolved=unresolved)


def _retain_geometry(circuit, decoded):
    """Attach encoded paths to the original requests without changing topology.

    The decoder numbers terminals in file order; user terminal IDs can contain
    gaps after deletion. Keep those IDs and the caller's original wire endpoints.
    Encoded labels replace requests' labels, avoiding duplicate native text.
    """
    connections, terminals = copy.deepcopy((circuit._connections, circuit._terminals))
    remap = {('@TERMINAL_T' + str(i + 1), 'PIN'): ('@TERMINAL_' + t['id'], 'PIN')
             for i, t in enumerate(terminals)}
    layouts, simple = {}, {}
    for request in decoded['connections'] + decoded['semantic_terminals']:
        if request.get('layout'):
            layout = copy.deepcopy(request['layout'])
            layout['paths'] = {remap.get(k, k): v for k, v in layout['paths'].items()}
            layout['labels'] = {remap.get(k, k): v for k, v in layout.get('labels', {}).items()}
            for key in layout['paths']:
                layouts[key] = layout
        elif request.get('points') is not None:
            if 'first' in request:
                first, second = request['first'], request['second']
            else:
                first = request['pin']
                second = ('@TERMINAL_' + request['id'], 'PIN')
            first, second = remap.get(first, first), remap.get(second, second)
            simple[frozenset((first, second))] = (first, request)
    assigned_layouts, assigned_labels = set(), set()
    requests = [(item, item['first'], item['second']) for item in connections]
    for i, terminal in enumerate(terminals):
        raw = decoded['terminals'][i]
        terminal['label'] = copy.deepcopy(raw['label'])
        if terminal.get('pin') is not None:
            requests.append((terminal, terminal['pin'], ('@TERMINAL_' + terminal['id'], 'PIN')))
    for item, first, second in requests:
        manual = item.get('points') is not None and not item.get('preserve_geometry')
        for field in ('points', 'layout', 'labels'):
            item.pop(field, None)
        layout = layouts.get(first)
        if layout is not None:
            _need(second in layout['paths'], 'Saved geometry disagrees with requested net')
            if id(layout) not in assigned_layouts:
                item['layout'] = layout
                assigned_layouts.add(id(layout))
        else:
            key = frozenset((first, second))
            _need(key in simple, 'Missing saved geometry for requested connection')
            start, native = simple[key]
            item['points'] = copy.deepcopy(native['points'] if start == first else native['points'][::-1])
            if key not in assigned_labels:
                item['labels'] = copy.deepcopy(native.get('labels', []))
                assigned_labels.add(key)
        item['preserve_geometry'] = not manual
    return connections, terminals


def translate(circuit, dx, dy, *, decoded=None):
    parts = copy.deepcopy(circuit._parts)
    if decoded is None:
        connections, terminals = copy.deepcopy((circuit._connections, circuit._terminals))
    else:
        connections, terminals = _retain_geometry(circuit, decoded)
    seen = set()
    def point(p):
        result = (p[0] + dx, p[1] + dy)
        if any(not -2**31 <= v < 2**31 for v in result):
            raise ValueError('Translated coordinate exceeds native range')
        return result
    def label(item):
        if id(item) not in seen:
            seen.add(id(item))
            if item.get('position') is not None:
                item['position'] = point(item['position'])
    def request(item):
        if item.get('points') is not None:
            item['points'] = list(map(point, item['points']))
        for value in item.get('labels', []):
            label(value)
        layout = item.get('layout')
        if layout is not None and id(layout) not in seen:
            seen.add(id(layout))
            if layout.get('junction') is not None:
                layout['junction'] = point(layout['junction'])
            if 'junctions' in layout:
                layout['junctions'] = list(map(point, layout['junctions']))
            layout['paths'] = {key: list(map(point, path)) for key, path in layout['paths'].items()}
            for labels in layout.get('labels', {}).values():
                for value in labels:
                    label(value)
            for link in layout.get('links', []):
                link['first'], link['second'] = point(link['first']), point(link['second'])
                request(link)
    for part in parts:
        part['x'], part['y'] = point((part['x'], part['y']))
    for item in connections:
        request(item)
    for item in terminals:
        if item.get('position') is not None:
            item['position'] = point(item['position'])
        if item.get('label') is not None:
            label(item['label'])
        request(item)
    circuit._validate(parts, connections, terminals)
    circuit._parts, circuit._connections, circuit._terminals = parts, connections, terminals


def fit_sheet(circuit, *, margin, footer, center):
    if circuit._batch_depth:
        raise ValueError('Fit the sheet after completing the batch')
    if margin < 0 or footer < 0 or type(center) is not bool:
        raise ValueError('Invalid sheet fitting options')
    width, height = sheet_size(circuit)
    # Use actual encoded wires and labels; fitting estimates alone missed bus
    # detours in complex circuits. This is a file operation, never a GUI call.
    with tempfile.TemporaryDirectory(prefix='proteus86-fit-') as directory:
        path = circuit.save(Path(directory) / 'geometry.pdsprj')
        decoded = decode_net_objects(path)
        _, _, points = geometry(circuit, decoded)
    if not points:
        return dict(width=width, height=height, translation=(0, 0))
    left, right = min(p[0] for p in points), max(p[0] for p in points)
    bottom, top = min(p[1] for p in points), max(p[1] for p in points)
    need_width = right - left + 2 * margin if center else 2 * (max(abs(left), abs(right)) + margin)
    need_height = top - bottom + 2 * margin + footer if center else 2 * max(top + margin, -bottom + margin + footer)
    scale = max(1, need_width / width, need_height / height)
    step = 254000
    new_width, new_height = (math.ceil(value * scale / step) * step for value in (width, height))
    if max(new_width, new_height) >= 2**31:
        raise ValueError('Required page size exceeds native range')
    dx = round(-(left + right) / 2 / step) * step if center else 0
    dy = round((footer - bottom - top) / 2 / step) * step if center else 0
    if center:
        dx = max(-new_width // 2 + margin - left, min(new_width // 2 - margin - right, dx))
        dy = max(-new_height // 2 + margin + footer - bottom, min(new_height // 2 - margin - top, dy))
    if dx or dy:
        # Pure page fitting preserves the already validated routes. Explicit
        # world-coordinate obstacles still require the original rerouting path.
        translate(circuit, dx, dy, decoded=decoded if not circuit.routing_options.get('obstacles') else None)
    data = bytearray(circuit._dsn)
    struct.pack_into('<ii', data, circuit._root + 25, new_width, new_height)
    circuit._dsn = bytes(data)
    return dict(width=new_width, height=new_height, translation=(dx, dy), expanded=scale > 1)


def wiringcheck(project, *, footer_mm=17.78):
    from .api import Circuit, mm
    circuit = Circuit.open(project)
    decoded = decode_net_objects(project)
    bodies, labels, points = geometry(circuit, decoded)
    width, height = sheet_size(circuit)
    bounds = (-width // 2, -height // 2 + mm(footer_mm), width // 2, height // 2)
    outside = [p for p in points if not bounds[0] <= p[0] <= bounds[2] or not bounds[1] <= p[1] <= bounds[3]]
    errors, warnings = [], []
    if outside:
        errors.append(dict(kind='outside_sheet', points=outside[:20], count=len(outside)))
    paths = [wire['points'] for wire in decoded['wires']]
    for i, path in enumerate(paths):
        for j, other in enumerate(paths[:i]):
            if any(collinear_overlap(a, b, c, d) for a, b in zip(path, path[1:]) for c, d in zip(other, other[1:])):
                errors.append(dict(kind='overlapping_wires', wires=[j, i]))
        for box in bodies + labels:
            if box.owner == '@wire-label:' + str(i):
                continue
            if any(box.blocks(a, b) for a, b in zip(path, path[1:])):
                warnings.append(dict(kind='wire_over_estimated_object', wire=i, object=box.owner))
    for i, box in enumerate(labels):
        for other in labels[:i]:
            if box.left < other.right and other.left < box.right and box.bottom < other.top and other.bottom < box.top:
                warnings.append(dict(kind='estimated_label_overlap', objects=[box.owner, other.owner]))
        for body in bodies:
            if box.owner.split(':')[0] == body.owner or box.owner.replace('@terminal-label:', '@terminal:') == body.owner:
                continue
            if box.left < body.right and body.left < box.right and box.bottom < body.top and body.bottom < box.top:
                warnings.append(dict(kind='label_over_estimated_symbol', objects=[box.owner, body.owner]))
    for i, box in enumerate(bodies):
        for other in bodies[:i]:
            if box.left < other.right and other.left < box.right and box.bottom < other.top and other.bottom < box.top:
                warnings.append(dict(kind='estimated_symbol_overlap', objects=[box.owner, other.owner]))
    return dict(passed=not errors, errors=errors, warnings=warnings,
                sheet_mm=dict(width=width / 100000, height=height / 100000),
                components=len(circuit._parts), wires=len(paths), junctions=len(decoded['junctions']))
