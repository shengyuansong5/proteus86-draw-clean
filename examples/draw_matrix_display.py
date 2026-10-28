"""Independent 8051 + 4x4 keypad + multiplexed eight-digit display example.

This is a file-only generator. Native editor and digital behavior require their
own explicitly requested verification; creating this example does not run PDS.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SEGMENT_PINS = tuple('ABCDEFGH')  # H is the model's decimal-point pin.
SEGMENT_PROBES = tuple('PS' + str(index) for index in range(8))
DIGIT_PROBES = tuple('PD' + str(index) for index in range(8))
KEYS = tuple('K' + str(index) for index in range(16))


def expected_nets(probes=False):
    """Complete named component-pin partitions, including clock/reset/power."""
    groups = []
    for index, pin in enumerate(SEGMENT_PINS):
        group = ['U1.' + str(39 - index), 'DS1.' + pin, 'RP' + str(index) + '.1']
        if probes:
            group.append(SEGMENT_PROBES[index] + '.D0')
        groups.append(group)
    for index in range(8):
        group = ['U1.' + str(21 + index), 'DS1.' + str(index + 1)]
        if probes:
            group.append(DIGIT_PROBES[index] + '.D0')
        groups.append(group)
    groups += [['U1.' + str(10 + row)] + ['K' + str(row * 4 + col) + '.2' for col in range(4)]
               for row in range(4)]
    groups += [['U1.' + str(14 + col)] + ['K' + str(row * 4 + col) + '.1' for row in range(4)]
               for col in range(4)]
    groups += [['U1.19', 'X1.2', 'CX1.2'], ['U1.18', 'X1.1', 'CX2.2'],
               ['U1.9', 'CR1.-', 'RR1.2'],
               ['U1.31', 'U1.40', 'CR1.+', 'CD1.2'] + ['RP' + str(i) + '.2' for i in range(8)],
               ['U1.20', 'CX1.1', 'CX2.1', 'RR1.1', 'CD1.1']]
    return groups


def _label(circuit, pin, name):
    # Let the codec orient each terminal against the actual pin exit. In
    # particular, the display's pins face down while MCU output pins face right.
    circuit.add_terminal('label', name, pin=pin)


def _place_terminal_stubs(circuit):
    """Keep this example's terminal rows in real pin order, with no fanout.

    The MCU and display pitches belong to the native symbols. Moving a terminal
    sideways to satisfy conservative text estimates creates crossing wires, so
    these short named stubs stay on their actual cardinal pin exits instead.
    Display labels alternate between two rows so their fixed 2.54 mm pin pitch
    does not turn the names into an unreadable horizontal string.
    """
    pins = {part['ref']: {pin['name']: pin for pin in circuit.pins(part['ref'])}
            for part in circuit.components()}
    for terminal in circuit.terminals():
        if terminal.get('pin') is None:
            continue
        ref, name = terminal['pin']
        pin = pins[ref][name]
        length = 762000  # 7.62 mm, including MCU/probe and power stubs.
        if ref == 'DS1':
            bank = SEGMENT_PINS if name in SEGMENT_PINS else tuple(str(i + 1) for i in range(8))
            length = 1016000 + bank.index(name) % 2 * 508000  # 10.16 / 15.24 mm.
        contact = tuple(pin['position'][axis] + pin['direction'][axis] * length for axis in (0, 1))
        circuit.update_terminal(terminal['id'], position=contact)
    # Center each caption in its own lane so long adjacent stubs clear its text
    # box, while preserving the normal terminal font and all routing guards.
    for terminal in circuit.terminals():
        if not terminal.get('pin') or terminal['pin'][0] != 'DS1':
            continue
        _, y = circuit.terminal_label_position(terminal['id'])
        circuit.set_terminal_label_position(terminal['id'],
                (terminal['position'][0] - len(terminal['name']) * 70000, y))


def make_circuit(*, probes=False):
    from proteus86 import Circuit
    if type(probes) is not bool:
        raise ValueError('probes must be a boolean')
    c = Circuit()
    with c.batch():
        c.add_mm('AT89C51RD2', 'U1', 'AT89C51RD2', -140, 45,
                 properties={'CLOCK': '12MHz', 'X2': '0', 'HWDOG': '0'},
                 property_visibility={'CLOCK': False, 'PROGRAM': False})
        c.add_mm('7SEG-MPX8-CC-BLUE', 'DS1', '8-DIGIT CC', -10, 125)
        # The crystal/capacitor lead junctions share cardinal directions. The
        # upper junction lies on XTAL1's row; the lower one stays below XTAL2,
        # avoiding the previous near-coincident crossing beside the crystal.
        c.add_mm('CRYSTAL', 'X1', '12MHz', -200, 34.84, library='DEVICE',
                 rotation=90, properties={'FREQ': '12MHz'})
        # Use the DEVICE capacitor model explicitly. The bare template
        # CAPACITOR primitive does not declare its analogue component type.
        c.add_mm('CAP', 'CX1', '22p', -207.62, 42.46, library='DEVICE')
        c.add_mm('CAP', 'CX2', '22p', -207.62, 27.22, library='DEVICE')
        c.add_mm('CAP-ELEC', 'CR1', '10u', -200, -10, library='DEVICE', rotation=270)
        c.add_mm('RESISTOR', 'RR1', '10k', -200, -40, rotation=90)
        c.add_mm('CAP', 'CD1', '100n', -140, -65, library='DEVICE', rotation=90)
        for index in range(8):
            ref = 'RP' + str(index)
            c.add_mm('RESISTOR', ref, '10k', -160 + index * 12.7, 100, rotation=90)
            _label(c, ref + '.1', 'S' + str(index))
            c.add_terminal('power', 'VCC', pin=ref + '.2')
        for row in range(4):
            for col in range(4):
                index = row * 4 + col
                ref = KEYS[index]
                c.add_mm('BUTTON', ref, format(index, 'X'), col * 45.72, 35 - row * 25.4)
                _label(c, ref + '.2', 'R' + str(row))
                _label(c, ref + '.1', 'C' + str(col))
        for index, pin in enumerate(SEGMENT_PINS):
            _label(c, 'U1.' + str(39 - index), 'S' + str(index))
            _label(c, 'DS1.' + pin, 'S' + str(index))
            _label(c, 'U1.' + str(21 + index), 'D' + str(index))
            _label(c, 'DS1.' + str(index + 1), 'D' + str(index))
        for row in range(4):
            _label(c, 'U1.' + str(10 + row), 'R' + str(row))
            _label(c, 'U1.' + str(14 + row), 'C' + str(row))
        c.connect_net('U1.19', 'X1.2', 'CX1.2')
        c.connect_net('U1.18', 'X1.1', 'CX2.2')
        c.connect_net('U1.9', 'CR1.-', 'RR1.2')
        # U1's hidden PP pins VCC/GND are automatically bound by their native
        # global names. Extra terminal stubs on those PP pins create conflicting
        # analogue interfaces in this 8.6 model and fail SPICE initialization.
        for pin in ('U1.31', 'CR1.+', 'CD1.2'):
            c.add_terminal('power', 'VCC', pin=pin)
        for pin in ('CX1.1', 'CX2.1', 'RR1.1', 'CD1.1'):
            c.add_terminal('ground', 'GND', pin=pin)
        if probes:
            for row, refs in enumerate((SEGMENT_PROBES, DIGIT_PROBES)):
                for index, ref in enumerate(refs):
                    c.add_mm('LOGICPROBE', ref, ref, -190 + 30.48 * index, -110 - row * 30.48)
                    _label(c, ref + '.D0', ('S' if row == 0 else 'D') + str(index))
        c.configure_power({'VCC': 5.0, 'GND': 0.0})
        c.arrange_labels()
        # In the native preview the crystal value touched the XTAL2 wire.
        # Keep both captions above the clock corridor, away from CX2's labels.
        c.update('X1', label_offsets={'reference': (1016000, 1524000),
                                      'value': (1016000, 1016000)})
        _place_terminal_stubs(c)
    c.tidy_labels(max_shift_mm=20.32)
    c.fit_sheet()
    return c


@contextmanager
def _temporary_files(directory):
    previous = {name: os.environ.get(name) for name in ('TEMP', 'TMP')}
    old_tempdir = tempfile.tempdir
    try:
        os.environ['TEMP'] = os.environ['TMP'] = str(directory)
        tempfile.tempdir = str(directory)
        yield
    finally:
        tempfile.tempdir = old_tempdir
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def generate(output_dir, *, probes=False, firmware=None):
    from proteus86 import Circuit, firmware_info, wiringcheck, wire_quality
    from proteus86.inspection import netcheck
    from proteus86.preview import render
    directory = Path(output_dir).resolve()
    if directory.exists():
        raise FileExistsError('Use a new example output directory: ' + str(directory))
    if type(probes) is not bool:
        raise ValueError('probes must be a boolean')
    firmware = Path(firmware).resolve() if firmware else Path(__file__).with_name('matrix_display.hex')
    info = firmware_info(firmware)
    directory.mkdir(parents=True)
    temporary = directory / 'tmp'
    temporary.mkdir()
    with _temporary_files(temporary):
        return _write_output(directory, probes=probes, firmware=firmware, info=info)


def _write_output(directory, *, probes, firmware, info):
    from proteus86 import Circuit, wiringcheck, wire_quality
    from proteus86.inspection import netcheck
    from proteus86.preview import render
    c = make_circuit(probes=probes)
    c.bind_firmware('U1', firmware, visible=False)
    project = c.save(directory / 'matrix_display.pdsprj')
    reopened = Circuit.open(project)
    expected = expected_nets(probes)
    check = netcheck(project, expected)
    if not check['passed']:
        raise RuntimeError('Saved example does not match the complete design netlist: ' + repr(check))
    canonical = lambda circuit: sorted(sorted(net) for net in circuit.nets())
    if canonical(c) != canonical(reopened):
        raise RuntimeError('Saving/reopening changed the example topology')
    geometry = wiringcheck(project)
    if not geometry['passed']:
        raise RuntimeError('Saved example has structural drawing errors: ' + repr(geometry['errors']))
    quality = wire_quality(project)
    render(project, directory / 'preview.svg')
    bundled = Path(__file__).with_name('matrix_display.hex')
    known_firmware = bundled.is_file() and hashlib.sha256(bundled.read_bytes()).hexdigest() == info['sha256']
    design = dict(kind='independent_matrix_display_example', keys=list(KEYS),
                  components=[{key: part[key] for key in ('ref', 'device', 'value', 'position')}
                              for part in reopened.components()],
                  nets=expected, initial_display='01234567' if known_firmware else None,
                  accepted_key_display='012345' + '<press_count_mod16>' + '<key_hex>' if known_firmware else None,
                  bundled_firmware=known_firmware,
                  custom_firmware_needs_own_scenarios=not known_firmware,
                  single_key_only=True, segment_active_low=False, digit_active_low=True,
                  segment_probes=list(SEGMENT_PROBES) if probes else [],
                  digit_probes=list(DIGIT_PROBES) if probes else [],
                  recommended_stable_press_seconds=0.08 if known_firmware else None,
                  recommended_stable_release_seconds=0.08 if known_firmware else None)
    (directory / 'design.json').write_text(json.dumps(design, indent=2), encoding='utf-8')
    (directory / 'expected_nets.json').write_text(json.dumps(expected, indent=2), encoding='utf-8')
    result = dict(passed=True, project=str(project), parts=len(reopened.components()),
                  project_sha256=hashlib.sha256(project.read_bytes()).hexdigest(),
                  firmware=dict(format=info['format'], sha256=info['sha256'], program_bytes=info['program_bytes']),
                  netcheck=check, saved_reopen_topology_equal=True,
                  geometry=geometry, wire_quality=quality,
                  drawing_quality_has_warnings=bool(geometry['warnings'] or not quality['passed']),
                  native_verified=False, simulation_executed=False,
                  scope='File generation and complete requested topology; native behavior needs a separate run')
    (directory / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--probes', action='store_true', help='Add PS0..7 and PD0..7 native digital probes')
    parser.add_argument('--firmware', type=Path, help='Compatible custom firmware; requires its own behavioral expectations')
    args = parser.parse_args()
    result = generate(args.output_dir, probes=args.probes, firmware=args.firmware)
    print(json.dumps({key: result[key] for key in ('passed', 'project', 'parts', 'simulation_executed')}), flush=True)


if __name__ == '__main__':
    main()
