"""Place a component/net list using real local pin geometry, without Proteus."""
from collections import Counter


def _bounds(circuit, part, *, margin=508000):
    template = circuit._template(part)
    points = list(template['pin_offsets'].values())
    return (part['x'] + min(p[0] for p in points) - margin,
            part['y'] + min(p[1] for p in points) - margin,
            part['x'] + max(p[0] for p in points) + margin,
            part['y'] + max(p[1] for p in points) + margin)


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _signal_chains(circuit, hub, groups, placed, gap, report):
    """Keep repeated two-component signal paths in ordered rows/columns."""
    if hub is None:
        return
    by_ref = {part['ref']: part for part in circuit._parts}
    candidates, used = {}, set(placed)
    for group in groups:
        if len(group) != 2 or sum(pin[0] == hub['ref'] for pin in group) != 1:
            continue
        source = next(pin for pin in group if pin[0] == hub['ref'])
        inner = next(pin for pin in group if pin != source)
        if inner[0] in used or len(circuit._template(by_ref[inner[0]])['pins']) != 2:
            continue
        links = [net for net in groups if len(net) == 2 and any(pin[0] == inner[0] and pin != inner for pin in net)]
        if len(links) != 1:
            continue
        outer = next(pin for pin in links[0] if pin[0] != inner[0])
        if outer[0] in used or outer[0] == hub['ref'] or len(circuit._template(by_ref[outer[0]])['pins']) != 2:
            continue
        middle = next(pin for pin in links[0] if pin[0] == inner[0])
        pin = next(pin for pin in circuit.pins(source[0]) if pin['name'] == source[1])
        candidates.setdefault(pin['direction'], []).append((pin, inner, middle, outer))
        used.update((inner[0], outer[0]))
    def oriented(ref, name, desired):
        original = by_ref[ref]
        for rotation in (original.get('rotation', 0), 0, 90, 180, 270):
            part = dict(original, rotation=rotation)
            if circuit._template(part)['pin_directions'][name] == desired:
                return part
        raise ValueError('Cannot orient signal-chain pin: ' + ref + '.' + name)
    occupied = [_bounds(circuit, part, margin=gap // 2) for part in placed.values()]
    for direction, chains in candidates.items():
        if len(chains) < 3:
            continue
        axis = 1 if direction[0] else 0
        chains.sort(key=lambda chain: chain[0]['position'][axis], reverse=bool(direction[0]))
        pitch = max(gap + 254000, 1524000)
        center = sum(chain[0]['position'][axis] for chain in chains) // len(chains)
        sign = -1 if direction[0] else 1
        coordinates = [center + sign * (2 * i - len(chains) + 1) * pitch // 2 for i in range(len(chains))]
        for distance in range(4, 13):
            proposals, boxes = [], []
            for row, (pin, inner, middle, outer) in zip(coordinates, chains):
                part = oriented(inner[0], inner[1], tuple(-v for v in direction))
                template = circuit._template(part)
                target = [pin['position'][i] + direction[i] * gap * distance for i in (0, 1)]
                target[axis] = row
                part.update(x=target[0] - template['pin_offsets'][inner[1]][0],
                            y=target[1] - template['pin_offsets'][inner[1]][1])
                middle_point = tuple(part[key] + template['pin_offsets'][middle[1]][i] for i, key in enumerate(('x', 'y')))
                middle_direction = template['pin_directions'][middle[1]]
                leaf = oriented(outer[0], outer[1], tuple(-v for v in middle_direction))
                leaf_template = circuit._template(leaf)
                leaf.update(x=middle_point[0] + middle_direction[0] * gap - leaf_template['pin_offsets'][outer[1]][0],
                            y=middle_point[1] + middle_direction[1] * gap - leaf_template['pin_offsets'][outer[1]][1])
                for candidate in (part, leaf):
                    proposals.append(candidate)
                    boxes.append(_bounds(circuit, candidate, margin=gap // 2))
            if any(_overlap(box, old) for box in boxes for old in occupied):
                continue
            if any(_overlap(box, other) for i, box in enumerate(boxes) for other in boxes[:i]):
                continue
            for part in proposals:
                circuit.update(part['ref'], x=part['x'], y=part['y'], rotation=part.get('rotation', 0))
                placed[part['ref']] = circuit._parts[circuit._index(part['ref'])]
                report.append(dict(ref=part['ref'], x=part['x'], y=part['y'], rotation=part.get('rotation', 0),
                                   reason='ordered repeated signal chain'))
            occupied.extend(boxes)
            break


def autoplace(circuit, nets=(), *, gap=1270000, fixed=()):
    """Use the largest IC as a hub; align neighbors with their connected pins.

    Discrete-only circuits are packed into columns with vertical pin pairs,
    leaving room for parallel rails and label rows. Explicit fixed refs stay put.
    """
    if type(gap) is not int or gap < 254000:
        raise ValueError('Layout gap must be at least 2.54 mm')
    parts = circuit._parts
    if not parts:
        return []
    groups = [[circuit._endpoint(pin) for pin in group] for group in nets]
    fixed = set(fixed)
    if fixed - {part['ref'] for part in parts}:
        raise ValueError('Unknown fixed component in layout')
    largest = max(parts, key=lambda part: len(circuit._template(part)['pins']))
    hub = largest if len(circuit._template(largest)['pins']) > 4 else None
    placed = {part['ref']: part for part in parts if part['ref'] in fixed}
    report = []
    with circuit.batch():
        if hub is not None and hub['ref'] not in placed:
            circuit.update(hub['ref'], x=0, y=0)
            hub = circuit._parts[circuit._index(hub['ref'])]
            placed[hub['ref']] = hub
            report.append({'ref': hub['ref'], 'reason': 'largest pin-count hub', 'x': 0, 'y': 0})
        _signal_chains(circuit, hub, groups, placed, gap, report)
        occupied = [_bounds(circuit, part, margin=gap // 2) for part in placed.values()]
        remaining = [part['ref'] for part in circuit._parts if part['ref'] not in placed]
        degree = Counter(pin[0] for group in groups for pin in group)
        while remaining:
            remaining = [ref for ref in remaining if ref not in placed]
            if not remaining:
                break
            def priority(ref):
                attached = sum(any(pin[0] == ref for pin in group) and any(pin[0] in placed for pin in group) for group in groups)
                return (-attached, -degree[ref], ref)
            ref = min(remaining, key=priority)
            remaining.remove(ref)
            part = dict(circuit._parts[circuit._index(ref)])
            attachments = []
            for group in groups:
                own = [pin for pin in group if pin[0] == ref]
                others = [pin for pin in group if pin[0] in placed]
                for pin in own:
                    for other in others:
                        other_pin = next(item for item in circuit.pins(other[0]) if item['name'] == other[1])
                        attachments.append((pin[1], other_pin))
            anchored = None
            if hub is not None and attachments:
                # Prefer a direct hub pin over a more distant peripheral.
                attached_name, target = attachments[0]
                for rotation in (0, 90, 180, 270):
                    candidate = dict(part, rotation=rotation)
                    template = circuit._template(candidate)
                    desired = tuple(-v for v in target['direction'])
                    if template['pin_directions'][attached_name] == desired:
                        part, anchored = candidate, (attached_name, target)
                        break
            if anchored:
                name, target = anchored
                template = circuit._template(part)
                dx, dy = template['pin_offsets'][name]
                direction = target['direction']
                proposals = []
                for column in range(1, 9):
                    for shift in (0, 1, -1, 2, -2, 3, -3, 4, -4):
                        x = target['position'][0] + direction[0] * gap * column - dx + (shift * gap if direction[1] else 0)
                        y = target['position'][1] + direction[1] * gap * column - dy + (shift * gap if direction[0] else 0)
                        proposals.append((x, y))
            else:
                if hub is None and len(circuit._template(part)['pins']) == 2:
                    # Prefer a vertical primitive without changing model/pin identity.
                    for rotation in (0, 90, 180, 270):
                        candidate = dict(part, rotation=rotation)
                        directions = list(circuit._template(candidate)['pin_directions'].values())
                        if all(direction[0] == 0 for direction in directions):
                            part = candidate; break
                proposals = [(column * gap * 3, -row * gap * 6) for row in range(16) for column in range(16)]
            for x, y in proposals:
                candidate = dict(part, x=x, y=y)
                box = _bounds(circuit, candidate, margin=gap // 2)
                if not any(_overlap(box, other) for other in occupied):
                    circuit.update(ref, x=x, y=y, rotation=candidate.get('rotation', 0))
                    current = circuit._parts[circuit._index(ref)]
                    occupied.append(box); placed[ref] = current
                    report.append({'ref': ref, 'x': x, 'y': y, 'rotation': current.get('rotation', 0),
                                   'reason': 'aligned to connected pin' if anchored else 'nonoverlapping geometry packing'})
                    if len(circuit._template(current)['pins']) > 4:
                        _signal_chains(circuit, current, groups, placed, gap, report)
                        occupied = [_bounds(circuit, item, margin=gap // 2) for item in placed.values()]
                    break
            else:
                raise ValueError('No automatic placement found for ' + ref)
        circuit.arrange_labels()
    return report


def arrange_modules(circuit, modules):
    """Explicit module/array grids. Preserve model identity and exact requested nets.

    rows preserve user order (for example [[R1,D1],[R2,D2]]). Origins and
    pitches are millimetres, rows go down. Signed X pitch permits left-facing arrays.
    Approximate overlap warnings are advisory; native encoding/routing guards remain.
    """
    from .api import mm
    if not isinstance(modules,dict) or not modules: raise ValueError('Provide named module grid plans')
    before=circuit.nets();known={p['ref'] for p in circuit._parts};seen=set();plans=[]
    for name,config in modules.items():
        if not isinstance(config,dict) or set(config)-{'rows','origin_mm','pitch_mm'}:
            raise ValueError('Module '+str(name)+': use rows, origin_mm and pitch_mm')
        rows=config.get('rows');origin=config.get('origin_mm');pitch=config.get('pitch_mm',(20.32,15.24))
        if not isinstance(rows,list) or not rows or not all(isinstance(row,list) and row for row in rows):
            raise ValueError('Module '+str(name)+': rows must be nonempty lists of references')
        if not isinstance(origin,(list,tuple)) or len(origin)!=2 or not isinstance(pitch,(list,tuple)) or len(pitch)!=2:
            raise ValueError('Module '+str(name)+': origin/pitch require X,Y pairs in millimetres')
        ox,oy=map(mm,origin);px,py=map(mm,pitch)
        if abs(px)<254000 or py<254000:raise ValueError('Module pitch must be at least 2.54 mm; Y pitch is positive')
        for row,refs in enumerate(rows):
            for col,ref in enumerate(refs):
                if ref not in known or ref in seen:raise ValueError('Unknown/repeated module reference: '+str(ref))
                seen.add(ref);plans.append(dict(module=name,ref=ref,x=ox+col*px,y=oy-row*py))
    report=dict(modules=list(modules),placements=plans,warnings=[])
    with circuit.batch():
        for item in plans:circuit.update(item['ref'],x=item['x'],y=item['y'])
        circuit.arrange_labels()
        circuit.arrange_terminals(reposition=True)
        if circuit.nets()!=before:raise RuntimeError('Module layout changed requested connectivity')
        boxes=[(part['ref'],_bounds(circuit,part,margin=254000)) for part in circuit._parts]
        for index,(ref,box) in enumerate(boxes):
            for other,other_box in boxes[:index]:
                if (ref in seen or other in seen) and _overlap(box,other_box):
                    report['warnings'].append(dict(kind='estimated_symbol_overlap',refs=[ref,other]))
    circuit.module_report=report
    return report
