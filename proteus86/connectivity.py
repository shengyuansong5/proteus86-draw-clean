"""Fresh union-find partitions; no persistent cache can outlive an edit."""
import re

from ._codec.device_library import definition_groups, describe_definition, properties_dict


def _implicit_power_pins(circuit, pin_tables):
    """Read hidden PP declarations from the selected single-unit package.

    PP names are native global net names, not guesses based on a pin's spelling
    or glyph. Require agreement with the instance's complete physical mapping;
    an unknown/mismatched package or ambiguous declaration adds no connection.
    This is a per-call view so edits cannot leave stale connectivity cached.
    """
    definitions = None
    metadata = {}
    for part in circuit._parts:
        template = circuit._template(part)
        properties = properties_dict(template['properties'].splitlines())
        package = properties.get('PACKAGE')
        if not package or package != template.get('package'):
            continue
        if definitions is None:
            definitions = definition_groups(circuit._dsn)['devices']
        symbol = template['symbol']
        if symbol not in metadata:
            definition = definitions.get(symbol)
            metadata[symbol] = (describe_definition({'name': symbol}, definition['body'])
                                if definition is not None else None)
        model = metadata[symbol]
        if model is None or model['pin_parse_status'] != 'parsed':
            continue
        lines = model['pinouts'].get(package)
        if lines is None:
            continue
        lines = [line.strip().strip('{}').strip() for line in lines]
        units = [line for line in lines if line.startswith('ELEMENTS')]
        if len(units) != 1 or re.fullmatch(r'ELEMENTS\s*=\s*1', units[0]) is None:
            continue
        declarations, names, pads, ambiguous = [], set(), set(), False
        for line in lines:
            if not line.startswith('PP'):
                continue
            match = re.fullmatch(r'PP\s+\(([^(){}]+)\)\s*=\s*([A-Za-z0-9]+(?:/[A-Za-z0-9]+)*|\*)', line)
            if match is None:
                ambiguous = True
                break
            name, numbers = match.groups()
            numbers_list = numbers.split('/')
            if (name != name.strip() or name in names or
                    len(set(numbers_list)) != len(numbers_list) or
                    numbers != '*' and pads.intersection(numbers_list)):
                ambiguous = True
                break
            names.add(name)
            if numbers != '*':
                pads.update(numbers_list)
            declarations.append((name, numbers))
        if ambiguous:
            continue
        actual = {pin['name']: str(pin['number']) for pin in pin_tables[part['ref']]}
        for name, numbers in declarations:
            # Match a complete logical pin mapping, including grouped pads.
            # Never find a different pin by its physical number or alias.
            if numbers != '*' and actual.get(name) == numbers:
                yield name, (part['ref'], name)


def nets(circuit, *, physical=False):
    parents, members, order, pin_tables = {}, {}, {}, {}
    for part in circuit._parts:
        pin_tables[part['ref']] = circuit.pins(part['ref'])
        for pin in pin_tables[part['ref']]:
            key = (part['ref'], pin['name'])
            parents[key] = key
            members[key] = {key}
            order[key] = len(order)
    sequence = len(order)

    def find(pin):
        while pin != parents[pin]:
            parents[pin] = parents[parents[pin]]
            pin = parents[pin]
        return pin

    def merge(pins):
        nonlocal sequence
        roots = {find(pin) for pin in pins if pin in parents}
        if not roots:
            return
        root = max(roots, key=lambda key: len(members[key]))
        for other in roots - {root}:
            parents[other] = root
            members[root].update(members.pop(other))
            del order[other]
        # The codec appends each touched group, including an already joined
        # group. Retain that exact public ordering as well as its partition.
        order[root] = sequence
        sequence += 1

    for connection in circuit._connections:
        merge((connection['first'], connection['second']))
    if not physical:
        by_name = {}
        for terminal in circuit._terminals:
            name = terminal.get('name') or ('GND' if terminal['kind'] == 'ground' else '')
            if name and terminal.get('pin') is not None:
                by_name.setdefault(name, []).append(terminal['pin'])
        for item in circuit._connections + circuit._terminals:
            pin = item.get('first', item.get('pin'))
            if pin is None:
                continue
            layout = item.get('layout') or {}
            labels = list(item.get('labels', []))
            labels += [label for values in layout.get('labels', {}).values() for label in values]
            labels += [label for link in layout.get('links', []) for label in link.get('labels', [])]
            for label in labels:
                if label.get('text'):
                    by_name.setdefault(label['text'], []).append(pin)
        for name, pin in _implicit_power_pins(circuit, pin_tables):
            by_name.setdefault(name, []).append(pin)
        for pins in by_name.values():
            merge(pins)
    return [sorted(members[root]) for root in sorted(members, key=order.__getitem__)]
