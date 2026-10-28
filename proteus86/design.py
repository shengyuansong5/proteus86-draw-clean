"""Component-list and net-list pipeline inspired by RACErace/pdsprj-auto."""
import shlex
from pathlib import Path

from .api import Circuit, mm
from .layout import autoplace

ALIASES = {'RES': 'RESISTOR', 'R': 'RESISTOR', 'CAP': 'CAPACITOR', 'C': 'CAPACITOR'}
TERMINALS = {'GROUND': 'ground', 'POWER': 'power', 'LABEL': 'label', 'INPUT': 'input', 'OUTPUT': 'output', 'BIDIR': 'bidir'}


def parse_design(text):
    result = {'parts': [], 'ports': {}, 'nets': []}
    section = None
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].lower()
            if section not in ('parts', 'terms', 'nets'):
                raise ValueError(f'Line {line_number}: unknown section {line}')
            continue
        if section == 'parts':
            fields = shlex.split(line, posix=True)
            if len(fields) < 3:
                raise ValueError(f'Line {line_number}: use REF DEVICE VALUE')
            ref, device, value = fields[:3]
            part = {'ref': ref, 'device': ALIASES.get(device.upper(), device), 'value': value}
            for field in fields[3:]:
                key, separator, value = field.partition('=')
                if not separator:
                    raise ValueError(f'Line {line_number}: invalid option {field}')
                if key == 'at':
                    x, y = value.split(',')
                    part.update(x=float(x), y=float(y))
                elif key == 'deg':
                    part['rotation'] = int(value)
                elif key == 'library':
                    part['library'] = value
                else:
                    raise ValueError(f'Line {line_number}: unknown option {key}')
            result['parts'].append(part)
        elif section == 'terms':
            fields = shlex.split(line)
            if len(fields) != 2 or fields[1].upper() not in TERMINALS:
                raise ValueError(f'Line {line_number}: use NAME POWER/GROUND/LABEL/INPUT/OUTPUT/BIDIR')
            if fields[0] in result['ports']:
                raise ValueError(f'Line {line_number}: duplicate terminal')
            result['ports'][fields[0]] = TERMINALS[fields[1].upper()]
        elif section == 'nets':
            pins = [value.strip() for value in line.split(',')]
            if len(pins) < 2 or not all(pins):
                raise ValueError(f'Line {line_number}: a net needs at least two entries')
            result['nets'].append(pins)
        else:
            raise ValueError(f'Line {line_number}: content before a section')
    if not result['parts']:
        raise ValueError('Design has no components')
    return result


def apply_nets(circuit, nets, ports=None):
    ports = ports or {}
    existing = {}
    for item in circuit.terminals():
        if item['name']:
            existing.setdefault(item['name'], []).append(item)
    with circuit.batch():
        for group in nets:
            group = [value.strip() for value in group.split(',')] if isinstance(group, str) else list(group)
            pins, labels = [], []
            for value in group:
                if isinstance(value, str) and '.' not in value:
                    if value not in ports and value not in existing:
                        raise ValueError('Net mentions an undeclared terminal: ' + value)
                    labels.append(value)
                else:
                    pins.append(circuit._endpoint(value))
            if not pins:
                raise ValueError('Each routed net requires at least one component pin')
            if len(pins) > 1:
                circuit.connect_net(*pins)
            for name in labels:
                candidates = existing.get(name, [])
                if not any(item.get('pin') is not None and tuple(item['pin']) == pins[0] for item in candidates):
                    kind = ports.get(name) or candidates[0]['kind']
                    terminal_id = circuit.add_terminal(kind, name, pins[0])
                    existing.setdefault(name, []).append(dict(id=terminal_id, name=name, kind=kind, pin=pins[0]))
    return circuit


def _from_design(design, *, install=None, template_project=None, place=True, route=True, fit=True, gap_mm=12.7, resource_base=None):
    circuit = Circuit(template_project, install=install)
    if resource_base is not None: circuit._resource_base = Path(resource_base).resolve()
    circuit.layout_report = []
    with circuit.batch():
        fixed = []
        for part in design['parts']:
            part = dict(part)
            anchored = 'x' in part and 'y' in part
            x, y = part.pop('x', 0), part.pop('y', 0)
            if anchored:
                fixed.append(part['ref'])
            circuit.add_mm(part.pop('device'), part.pop('ref'), part.pop('value'), x, y, **part)
        if place:
            pin_groups = [[pin for pin in group if '.' in pin] for group in design['nets']]
            circuit.layout_report = autoplace(circuit, pin_groups, fixed=fixed, gap=mm(gap_mm))
        if route:
            apply_nets(circuit, design['nets'], design['ports'])
        else:
            # Place terminals next to their eventual pins, without merging part nets.
            for group in design['nets']:
                pins = [value for value in group if '.' in value]
                for name in group:
                    if name in design['ports']:
                        circuit.add_terminal(design['ports'][name], name, pins[0])
        circuit.arrange_terminals()
    if place and fit and not fixed:
        circuit.fit_sheet()
    return circuit


def from_design(text, *, install=None, template_project=None, place=True, route=True, fit=True, gap_mm=12.7, resource_base=None):
    """Place and route, retrying bounded wider spacing for congested layouts."""
    from .routing import RoutingError
    design = parse_design(text) if isinstance(text, str) else text
    mm(gap_mm)
    movable = place and any('x' not in part or 'y' not in part for part in design['parts'])
    attempts = [gap_mm * scale for scale in ((1, 1.2, 1.5) if movable and route else (1,))]
    failures = []
    for gap in attempts:
        try:
            circuit = _from_design(design, install=install, template_project=template_project,
                                   place=place, route=route, fit=fit, gap_mm=gap, resource_base=resource_base)
            circuit.layout_attempts = dict(gap_mm=gap, prior_failures=failures)
            return circuit
        except RoutingError as error:
            failures.append(dict(gap_mm=gap, error=str(error)))
            last_error = error
    raise RoutingError('Automatic layout/routing failed after bounded spacing attempts: ' + str(failures)) from last_error


def format_layout(circuit, design):
    """Serialize the computed placement; coordinates are explicitly millimetres."""
    lines = ['# Coordinates in millimetres. Generated by proteus86.', '[parts]']
    originals = {part['ref']: part for part in design['parts']}
    for part in circuit._parts:
        library = originals.get(part['ref'], {}).get('library')
        suffix = ' library=' + shlex.quote(library) if library else ''
        lines.append(f"{part['ref']} {part['device']} {shlex.quote(part['value'])} at={part['x']/100000:g},{part['y']/100000:g} deg={part.get('rotation', 0)}{suffix}")
    lines += ['', '[terms]']
    lines += [shlex.quote(name) + ' ' + kind.upper() for name, kind in design['ports'].items()]
    lines += ['', '[nets]']
    lines += [','.join(group) for group in design['nets']]
    return '\n'.join(lines) + '\n'


def route_file(source, destination, nets, *, overwrite=False, replace=False, install=None):
    circuit = Circuit.open(source, install=install)
    with circuit.batch():
        if replace:
            circuit._connections = []
        apply_nets(circuit, nets)
        circuit.arrange_terminals()
        circuit.autoroute()
    return circuit.save(destination, overwrite=overwrite)
