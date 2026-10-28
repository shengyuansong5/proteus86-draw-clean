"""Read-only topology, pin geometry and layout reports from native files."""
from .api import Circuit
from ._codec.net_objects import decode_net_objects
from .connectivity import _implicit_power_pins


def inspect_project(project):
    circuit = Circuit.open(project)
    decoded = decode_net_objects(project)
    return {
        'components': circuit.components(),
        'pins': {part['ref']: circuit.pins(part['ref']) for part in circuit.components()},
        'terminals': circuit.terminals(), 'nets': circuit.nets(),
        'wires': decoded['wires'], 'junctions': decoded['junctions'],
        'complete': decoded['complete'], 'rebuild_complete': decoded.get('rebuild_complete', False),
        'power_rails': circuit.power_rails(),
    }


def netcheck(project, expected):
    """Require exact nets, including package-declared implicit power endpoints.

    A design's named global power port includes the selected package's matching
    PP pins. Expand from that declaration, never from observed terminal anchors
    or actual network membership: accidental extra pins still fail equality.
    """
    circuit = Circuit.open(project)
    implicit_by_name, implicit_names = {}, {}
    pin_tables = {part['ref']: circuit.pins(part['ref']) for part in circuit._parts}
    for name, pin in _implicit_power_pins(circuit, pin_tables):
        implicit_by_name.setdefault(name, set()).add(pin)
        implicit_names[pin] = name
    terminals = {item['name']: item for item in circuit.terminals() if item['name']}
    groups = []
    for group in expected:
        group = group.split(',') if isinstance(group, str) else group
        pins = set()
        for entry in group:
            if isinstance(entry, str) and '.' not in entry:
                if entry not in terminals or not terminals[entry].get('pin'):
                    raise ValueError('Expected terminal is missing or detached: ' + entry)
                # Expected topology must come from the design, never from the
                # observed terminal's anchor after an accidental short.
                pins.add(('@PORT', entry))
                pins.update(implicit_by_name.get(entry, ()))
            else:
                endpoint = circuit._endpoint(entry)
                pins.add(endpoint)
                # Explicit PP endpoints have the same global semantics even
                # when their corresponding named port appears in a later net.
                if endpoint in implicit_names:
                    pins.update(implicit_by_name[implicit_names[endpoint]])
        overlaps = [previous for previous in groups if previous & pins]
        for previous in overlaps:
            groups.remove(previous); pins.update(previous)
        groups.append(pins)
    actual = [set(group) for group in circuit.nets()]
    errors = []
    for group in groups:
        pins = {pin for pin in group if pin[0] != '@PORT'}
        names = {pin[1] for pin in group if pin[0] == '@PORT'}
        if not pins:
            raise ValueError('Expected net has no component pins')
        related = [item for item in actual if item & pins]
        observed_names = {name for name, terminal in terminals.items()
                          if terminal.get('pin') and tuple(terminal['pin']) in pins}
        if pins not in actual or not names <= observed_names:
            errors.append({'expected': sorted(pins), 'terminal_names': sorted(names),
                           'actual_connected_groups': [sorted(item) for item in related]})
    return {'passed': not errors, 'expected_nets': len(groups), 'actual_nets': len(actual), 'errors': errors}
