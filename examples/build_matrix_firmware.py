"""Build the independent matrix example with a small, strict 8051 assembler.

Only the instruction forms used by matrix_display.a51 are supported. This is
project-authored Python, not a wrapper around a vendor compiler or a general
A51 replacement. It uses no subprocesses, installed tools, libraries or HEX
templates. See matrix_firmware_build.md for the accepted grammar and limits.
"""
import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re


class AssemblyError(ValueError):
    """The source is outside the explicitly supported assembly subset."""


@dataclass(frozen=True)
class Assembly:
    image: dict
    symbols: dict
    listing: tuple


_IDENT = re.compile(r'[A-Z_][A-Z0-9_]*\Z')
_DECIMAL = re.compile(r'[0-9]+\Z')
_HEX = re.compile(r'[0-9][0-9A-F]*H\Z')
_REGISTER = re.compile(r'R([0-7])\Z')
_MNEMONICS = {'NOP', 'RET', 'LJMP', 'LCALL', 'SJMP', 'JNZ', 'MOV', 'MOVC',
              'INC', 'CJNE', 'DJNZ', 'ADD', 'RL', 'ANL', 'ORL'}
_RESERVED = _MNEMONICS | {'DATA', 'CSEG', 'AT', 'DB', 'END', 'A', 'DPTR', 'SP'}
_RESERVED |= {'R' + str(index) for index in range(8)}


def _number(token):
    if _DECIMAL.fullmatch(token):
        return int(token, 10)
    if _HEX.fullmatch(token):
        return int(token[:-1], 16)
    return None


def _resolve(token, symbols, bits, *, unresolved=False, kind=None):
    value = _number(token)
    if value is None:
        if not _IDENT.fullmatch(token):
            raise AssemblyError('invalid operand: ' + token)
        symbol = symbols.get(token)
        if symbol is None:
            if unresolved:
                return 0
            raise AssemblyError('undefined symbol: ' + token)
        if kind and symbol['kind'] != kind:
            raise AssemblyError(token + ' must be a ' + kind + ' symbol')
        value = symbol['value']
    if not 0 <= value < (1 << bits):
        raise AssemblyError(token + ' is outside unsigned ' + str(bits) + '-bit range')
    return value


def _operands(text):
    if not text:
        return []
    result = [operand.strip() for operand in text.split(',')]
    if any(not operand for operand in result):
        raise AssemblyError('empty operand')
    return result


def _encode(mnemonic, operands, pc, symbols, *, unresolved=False):
    """Encode instruction forms; values always come from parsed operands."""
    def value(token, bits=8, kind=None):
        return _resolve(token, symbols, bits, unresolved=unresolved, kind=kind)

    def direct(token):
        if token in _RESERVED and token != 'SP':
            raise AssemblyError('expected direct byte address, got ' + token)
        return value(token, kind='data')

    def immediate(token, bits=8):
        if not token.startswith('#'):
            raise AssemblyError('expected immediate #value, got ' + token)
        return value(token[1:], bits)

    def relative(token, size):
        target = value(token, 16, 'code')
        offset = target - (pc + size)
        if not unresolved and not -128 <= offset <= 127:
            raise AssemblyError('relative branch to ' + token + ' exceeds -128..127 bytes')
        return offset & 255

    def reg(token):
        match = _REGISTER.fullmatch(token)
        return int(match[1]) if match else None

    count = len(operands)
    if mnemonic in {'NOP', 'RET'} and count == 0:
        return bytes([{'NOP': 0x00, 'RET': 0x22}[mnemonic]])
    if mnemonic in {'LJMP', 'LCALL'} and count == 1:
        target = value(operands[0], 16, 'code')
        return bytes([{'LJMP': 0x02, 'LCALL': 0x12}[mnemonic], target >> 8, target & 255])
    if mnemonic in {'SJMP', 'JNZ'} and count == 1:
        return bytes([{'SJMP': 0x80, 'JNZ': 0x70}[mnemonic], relative(operands[0], 2)])
    if mnemonic == 'RL' and operands == ['A']:
        return bytes([0x23])
    if mnemonic == 'MOVC' and operands == ['A', '@A+DPTR']:
        return bytes([0x93])
    if mnemonic == 'MOV' and count == 2:
        dest, src = operands
        dest_reg, src_reg = reg(dest), reg(src)
        if dest == 'DPTR' and src.startswith('#'):
            number = immediate(src, 16)
            return bytes([0x90, number >> 8, number & 255])
        if src.startswith('#'):
            number = immediate(src)
            if dest == 'A':
                return bytes([0x74, number])
            if dest_reg is not None:
                return bytes([0x78 + dest_reg, number])
            return bytes([0x75, direct(dest), number])
        if dest == 'A':
            if src_reg is not None:
                return bytes([0xE8 + src_reg])
            if src in {'@R0', '@R1'}:
                return bytes([0xE6 + int(src[-1])])
            return bytes([0xE5, direct(src)])
        if src == 'A':
            if dest_reg is not None:
                return bytes([0xF8 + dest_reg])
            if dest in {'@R0', '@R1'}:
                return bytes([0xF6 + int(dest[-1])])
            return bytes([0xF5, direct(dest)])
        if src_reg is not None:
            return bytes([0x88 + src_reg, direct(dest)])
        return bytes([0x85, direct(src), direct(dest)])
    if mnemonic == 'INC' and count == 1:
        operand = operands[0]
        if operand == 'A':
            return bytes([0x04])
        register = reg(operand)
        if register is not None:
            return bytes([0x08 + register])
        return bytes([0x05, direct(operand)])
    if mnemonic == 'CJNE' and count == 3:
        left, right, target = operands
        offset = relative(target, 3)
        if left == 'A':
            if right.startswith('#'):
                return bytes([0xB4, immediate(right), offset])
            return bytes([0xB5, direct(right), offset])
        register = reg(left)
        if register is not None and right.startswith('#'):
            return bytes([0xB8 + register, immediate(right), offset])
    if mnemonic == 'DJNZ' and count == 2:
        register = reg(operands[0])
        if register is not None:
            return bytes([0xD8 + register, relative(operands[1], 2)])
    if mnemonic == 'ADD' and count == 2 and operands[0] == 'A':
        if operands[1].startswith('#'):
            return bytes([0x24, immediate(operands[1])])
        register = reg(operands[1])
        if register is not None:
            return bytes([0x28 + register])
    if mnemonic in {'ANL', 'ORL'} and count == 2 and operands[1].startswith('#'):
        number = immediate(operands[1])
        if operands[0] == 'A':
            return bytes([{'ANL': 0x54, 'ORL': 0x44}[mnemonic], number])
        if mnemonic == 'ANL':
            return bytes([0x53, direct(operands[0]), number])
    raise AssemblyError('unsupported instruction form: ' + mnemonic + ' ' + ','.join(operands))


def assemble(source):
    """Assemble UTF-8 text in two passes into a sparse 16-bit code image.

    Comments begin with semicolons. Supported directives are NAME DATA number,
    CSEG AT number, DB byte,... and a required final END. Labels are code
    addresses; only SP is predefined (81H). Unknown syntax fails closed.
    """
    symbols = {'SP': {'kind': 'data', 'value': 0x81}}
    statements = []
    pc = 0
    segment_selected = False
    ended = False

    def define(name, kind, value):
        if not _IDENT.fullmatch(name) or name in _RESERVED or name in symbols:
            raise AssemblyError('invalid, reserved or duplicate symbol: ' + name)
        if not 0 <= value <= 0xFFFF:
            raise AssemblyError('symbol address is outside 16-bit code space: ' + name)
        symbols[name] = {'kind': kind, 'value': value}

    for line_number, original in enumerate(source.splitlines(), 1):
        text = original.split(';', 1)[0].strip().upper()
        if not text:
            continue
        try:
            if ended:
                raise AssemblyError('statement after END')
            if ':' in text:
                label, separator, text = text.partition(':')
                if not segment_selected:
                    raise AssemblyError('code label requires CSEG AT')
                define(label.strip(), 'code', pc)
                text = text.strip()
                if not text:
                    continue
            data = re.fullmatch(r'([A-Z_][A-Z0-9_]*)\s+DATA\s+(\S+)', text)
            if data:
                number = _number(data[2])
                if number is None or not 0 <= number <= 255:
                    raise AssemblyError('DATA requires a numeric byte address')
                define(data[1], 'data', number)
                continue
            segment = re.fullmatch(r'CSEG\s+AT\s+(\S+)', text)
            if segment:
                number = _number(segment[1])
                if number is None or not 0 <= number <= 0xFFFF:
                    raise AssemblyError('CSEG AT requires a numeric 16-bit code address')
                pc = number
                segment_selected = True
                continue
            if text == 'END':
                ended = True
                continue
            if not segment_selected:
                raise AssemblyError('instruction or DB requires CSEG AT')
            pieces = text.split(None, 1)
            mnemonic = pieces[0]
            operands = _operands(pieces[1] if len(pieces) == 2 else '')
            if mnemonic == 'DB':
                if not operands:
                    raise AssemblyError('DB requires at least one byte')
                code = bytes(_resolve(item, symbols, 8, unresolved=True) for item in operands)
            else:
                code = _encode(mnemonic, operands, pc, symbols, unresolved=True)
            if pc + len(code) > 0x10000:
                raise AssemblyError('code extends beyond 16-bit address space')
            statements.append((line_number, original.strip(), pc, mnemonic, operands, len(code)))
            pc += len(code)
        except AssemblyError as error:
            raise AssemblyError('line ' + str(line_number) + ': ' + str(error)) from error
    if not ended:
        raise AssemblyError('missing final END directive')
    image = {}
    listing = []
    for line_number, original, address, mnemonic, operands, expected_size in statements:
        try:
            if mnemonic == 'DB':
                code = bytes(_resolve(item, symbols, 8) for item in operands)
            else:
                code = _encode(mnemonic, operands, address, symbols)
            if len(code) != expected_size:
                raise AssemblyError('instruction changed size between passes')
            for offset, byte in enumerate(code):
                location = address + offset
                if location in image:
                    raise AssemblyError('overlapping code at ' + format(location, '04X') + 'H')
                image[location] = byte
            listing.append({'line': line_number, 'address': address,
                            'bytes_hex': code.hex().upper(), 'source': original})
        except AssemblyError as error:
            raise AssemblyError('line ' + str(line_number) + ': ' + str(error)) from error
    if not image:
        raise AssemblyError('source emitted no code bytes')
    return Assembly(image, symbols, tuple(listing))


def encode_hex(image, *, record_size=16):
    """Encode sparse 0000H..FFFFH data as checksummed Intel HEX 00/01 records."""
    if not isinstance(record_size, int) or isinstance(record_size, bool) or not 1 <= record_size <= 255:
        raise AssemblyError('record_size must be an integer from 1 to 255')
    for address, value in image.items():
        if (type(address) is not int or type(value) is not int or
                not 0 <= address <= 0xFFFF or not 0 <= value <= 255):
            raise AssemblyError('HEX image requires 16-bit integer addresses and byte values')
    lines = []
    addresses = sorted(image)
    index = 0
    while index < len(addresses):
        start = addresses[index]
        data = [image[start]]
        index += 1
        while (index < len(addresses) and len(data) < record_size and
               addresses[index] == start + len(data)):
            data.append(image[addresses[index]])
            index += 1
        payload = bytes([len(data), start >> 8, start & 255, 0] + data)
        lines.append(':' + (payload + bytes([(-sum(payload)) & 255])).hex().upper())
    return '\n'.join(lines + [':00000001FF']) + '\n'


def decode_hex(text):
    """Strictly validate the limited 16-bit Intel HEX representation we emit."""
    image = {}
    ended = False
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line or ended or not re.fullmatch(r':[0-9A-Fa-f]+', line):
            raise AssemblyError('HEX line ' + str(line_number) + ': invalid record or data after EOF')
        try:
            record = bytes.fromhex(line[1:])
        except ValueError as error:
            raise AssemblyError('HEX line ' + str(line_number) + ': invalid hexadecimal bytes') from error
        if len(record) < 5 or len(record) != record[0] + 5 or sum(record) & 255:
            raise AssemblyError('HEX line ' + str(line_number) + ': invalid byte count or checksum')
        count, high, low, kind = record[:4]
        address = (high << 8) | low
        if kind == 1:
            if count or address:
                raise AssemblyError('HEX EOF must have zero count and address')
            ended = True
        elif kind == 0:
            if count == 0 or address + count > 0x10000:
                raise AssemblyError('HEX data record has empty or overflowing address range')
            for offset, value in enumerate(record[4:-1]):
                if address + offset in image:
                    raise AssemblyError('HEX has overlapping data records')
                image[address + offset] = value
        else:
            raise AssemblyError('unsupported HEX record type: ' + str(kind))
    if not ended or not image:
        raise AssemblyError('HEX requires code bytes and one final EOF')
    return image


def build(source, output_dir, *, check_against=None):
    """Build and audit without any external tool; destination must be new."""
    source = Path(source)
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError('Output directory must be new: ' + str(output_dir))
    raw = source.read_bytes()
    assembly = assemble(raw.decode('utf-8-sig'))
    encoded = encode_hex(assembly.image).encode('ascii')
    if decode_hex(encoded.decode('ascii')) != assembly.image:
        raise AssemblyError('internal Intel HEX round-trip failed')
    if check_against is not None:
        reference = decode_hex(Path(check_against).read_text(encoding='ascii'))
        if reference != assembly.image:
            different = next(address for address in sorted(reference.keys() | assembly.image.keys())
                             if reference.get(address) != assembly.image.get(address))
            raise AssemblyError('reference differs at code address ' + format(different, '04X') + 'H')
    addressed = b''.join(address.to_bytes(2, 'big') + bytes([assembly.image[address]])
                         for address in sorted(assembly.image))
    manifest = {
        'builder': 'proteus86_matrix_subset_v1',
        'builder_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'external_tools_used': False,
        'source': source.name,
        'source_sha256': hashlib.sha256(raw).hexdigest(),
        'hex': 'matrix_display.hex',
        'hex_sha256': hashlib.sha256(encoded).hexdigest(),
        'program_bytes': len(assembly.image),
        'address_min': min(assembly.image),
        'address_max': max(assembly.image),
        'addressed_bytes_encoding': 'ascending address: uint16 big-endian address then uint8 value',
        'addressed_bytes_sha256': hashlib.sha256(addressed).hexdigest(),
        'reference_address_bytes_equal': True if check_against is not None else None,
        'symbols': dict(sorted(assembly.symbols.items())),
        'listing': list(assembly.listing),
        'native_simulation_executed': False,
    }
    output_dir.mkdir(parents=True)
    (output_dir / 'matrix_display.hex').write_bytes(encoded)
    (output_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).with_name('matrix_display.a51'))
    parser.add_argument('--output-dir', type=Path, required=True, help='new build directory')
    parser.add_argument('--check-against', type=Path, help='optional independent HEX address/byte comparison')
    arguments = parser.parse_args()
    try:
        manifest = build(arguments.source, arguments.output_dir, check_against=arguments.check_against)
    except (AssemblyError, OSError, UnicodeError) as error:
        parser.exit(2, str(error) + '\n')
    print(json.dumps({key: value for key, value in manifest.items() if key not in {'symbols', 'listing'}}, indent=2))


if __name__ == '__main__':
    main()
