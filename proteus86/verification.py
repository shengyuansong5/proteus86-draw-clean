"""Compare requested explicit nets with the real Proteus logical SDF result."""


def verify_netlist(circuit, netlist):
    parts = {part['ref']: part for part in circuit.components()}
    if set(parts) != set(netlist['parts']):
        raise AssertionError('Native component references disagree with the generated circuit')
    for ref, part in parts.items():
        if netlist['parts'][ref]['value'] != part['value']:
            raise AssertionError('Native value mismatch for ' + ref)
    membership = {}
    for index, net in enumerate(netlist['nets']):
        for pin in net['pins']:
            try:
                endpoint = circuit._endpoint((pin['ref'], pin['pin']))
            except (ValueError, KeyError):
                continue
            if endpoint in membership and membership[endpoint] != index:
                raise AssertionError('A native pin occurs in multiple nets')
            membership[endpoint] = index
    explicit = [net for net in circuit.nets() if len(net) > 1]
    seen = {}
    for group in explicit:
        actual = {membership.get(pin) for pin in group}
        if None in actual or len(actual) != 1:
            raise AssertionError('Requested pins were not joined by Proteus: ' + repr(group))
        index = actual.pop()
        if index in seen:
            raise AssertionError('Separate requested nets were shorted by Proteus')
        seen[index] = group
    for terminal in circuit.terminals():
        if terminal.get('pin') is None:
            continue
        name = terminal.get('name') or ('GND' if terminal['kind'] == 'ground' else '')
        index = membership.get(tuple(terminal['pin']))
        if index is None or name and not (netlist['nets'][index]['name'] == name or
                                         any(item['name'] == name for item in netlist['nets'][index]['terminals'])):
            raise AssertionError('Native terminal mismatch: ' + repr(terminal))
    return {'parts': len(parts), 'explicit_nets': len(explicit), 'native_nets': len(netlist['nets']), 'passed': True}
