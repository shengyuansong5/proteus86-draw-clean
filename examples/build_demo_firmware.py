"""Rebuild the project's two small independent 8051 demos without vendor tools.

This deliberately limited assembler parses source and emits instruction bytes.
It is not a general A51 compiler or an instruction execution/simulation engine.
"""
import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples import build_matrix_firmware as hex_codec


class AssemblyError(ValueError):
    """Source is outside the explicitly supported demo assembly subset."""


@dataclass(frozen=True)
class Assembly:
    image: dict
    symbols: dict
    listing: tuple


_SYMBOL = re.compile(r'[A-Z_][A-Z0-9_]*\Z')
_REGISTER = re.compile(r'R([0-7])\Z')
_MNEMONICS = {'NOP', 'MOV', 'LCALL', 'SJMP', 'DJNZ', 'RET', 'JB', 'JNB', 'INC', 'CPL'}
_RESERVED = _MNEMONICS | {'CSEG', 'AT', 'END', 'A', 'SP'} | {'R' + str(i) for i in range(8)}


def _number(token, bits):
    if re.fullmatch(r'[0-9][0-9A-F]*H', token):
        value = int(token[:-1], 16)
    elif re.fullmatch(r'0X[0-9A-F]+', token):
        value = int(token[2:], 16)
    elif re.fullmatch(r'[0-9]+', token):
        value = int(token, 10)
    else:
        raise AssemblyError('expected an unsigned numeric constant, got ' + token)
    if not 0 <= value < 1 << bits:
        raise AssemblyError(token + ' exceeds unsigned ' + str(bits) + '-bit range')
    return value


def _encode(mnemonic, operands, pc, symbols, *, first_pass=False):
    def direct(token):
        return 0x81 if token == 'SP' else _number(token, 8)

    def immediate(token):
        if not token.startswith('#'):
            raise AssemblyError('expected immediate #value, got ' + token)
        return _number(token[1:], 8)

    def target(token):
        if token in symbols:
            return symbols[token]
        if _SYMBOL.fullmatch(token) and token not in _RESERVED:
            if first_pass:
                return 0
            raise AssemblyError('unknown code label: ' + token)
        return _number(token, 16)

    def relative(token, size):
        offset = target(token) - (pc + size)
        if not first_pass and not -128 <= offset <= 127:
            raise AssemblyError('relative branch to ' + token + ' exceeds -128..127 bytes')
        return offset & 0xFF

    def register(token):
        match = _REGISTER.fullmatch(token)
        return int(match[1]) if match else None

    if mnemonic in {'NOP', 'RET'} and not operands:
        return bytes([0x00 if mnemonic == 'NOP' else 0x22])
    if mnemonic == 'MOV' and len(operands) == 2:
        dest, src = operands
        dest_reg, src_reg = register(dest), register(src)
        if src.startswith('#'):
            value = immediate(src)
            if dest == 'A':
                return bytes([0x74, value])
            if dest_reg is not None:
                return bytes([0x78 + dest_reg, value])
            return bytes([0x75, direct(dest), value])
        if dest == 'A' and src_reg is not None:
            return bytes([0xE8 + src_reg])
        if src == 'A':
            if dest_reg is not None:
                return bytes([0xF8 + dest_reg])
            if dest != 'A':
                return bytes([0xF5, direct(dest)])
    if mnemonic == 'LCALL' and len(operands) == 1:
        value = target(operands[0])
        return bytes([0x12, value >> 8, value & 255])
    if mnemonic == 'SJMP' and len(operands) == 1:
        return bytes([0x80, relative(operands[0], 2)])
    if mnemonic == 'DJNZ' and len(operands) == 2:
        number = register(operands[0])
        if number is not None:
            return bytes([0xD8 + number, relative(operands[1], 2)])
    if mnemonic in {'JB', 'JNB'} and len(operands) == 2:
        return bytes([0x20 if mnemonic == 'JB' else 0x30,
                      _number(operands[0], 8), relative(operands[1], 3)])
    if mnemonic == 'INC' and len(operands) == 1:
        number = register(operands[0])
        if number is not None:
            return bytes([0x08 + number])
        if operands[0] == 'A':
            return bytes([0x04])
        return bytes([0x05, direct(operands[0])])
    if mnemonic == 'CPL' and operands == ['A']:
        return bytes([0xF4])
    raise AssemblyError('unsupported instruction form: ' + mnemonic + ' ' + ','.join(operands))


def assemble(text):
    """Assemble strict CSEG/END source; reject unknown and overlapping content."""
    if not isinstance(text, str):
        raise TypeError('assembly source must be text')
    pc = None
    ended = False
    symbols, items = {}, []
    for line_number, original in enumerate(text.splitlines(), 1):
        line = original.split(';', 1)[0].strip().upper()
        if not line:
            continue
        try:
            if ended:
                raise AssemblyError('content after END')
            label = None
            if ':' in line:
                label, line = line.split(':', 1)
                label, line = label.strip(), line.strip()
                if not _SYMBOL.fullmatch(label) or label in _RESERVED:
                    raise AssemblyError('invalid or reserved label: ' + label)
                if label in symbols:
                    raise AssemblyError('duplicate label: ' + label)
                if pc is None or not 0 <= pc <= 0xFFFF:
                    raise AssemblyError('label requires a valid CSEG code position')
                symbols[label] = pc
            if not line:
                continue
            words = line.split()
            if words[0] == 'CSEG':
                if label or len(words) != 3 or words[1] != 'AT':
                    raise AssemblyError('expected CSEG AT <16-bit address> without a label')
                pc = _number(words[2], 16)
                continue
            if words[0] == 'END':
                if label or len(words) != 1:
                    raise AssemblyError('END takes no label or operands')
                ended = True
                continue
            if pc is None:
                raise AssemblyError('instruction requires CSEG AT first')
            # A51 accepts a tab or several spaces between mnemonic/operands.
            fields = line.split(None, 1)
            mnemonic = fields[0]
            argument_text = fields[1] if len(fields) > 1 else ''
            if mnemonic not in _MNEMONICS:
                raise AssemblyError('unsupported directive/instruction: ' + mnemonic)
            operands = [value.strip() for value in argument_text.split(',')] if argument_text else []
            if any(not operand or any(char.isspace() for char in operand) for operand in operands):
                raise AssemblyError('empty operand or unsupported operand expression')
            encoded = _encode(mnemonic, operands, pc, symbols, first_pass=True)
            if pc + len(encoded) > 0x10000:
                raise AssemblyError('instruction exceeds 16-bit code address space')
            items.append((line_number, pc, mnemonic, operands, len(encoded)))
            pc += len(encoded)
        except AssemblyError as error:
            raise AssemblyError('line ' + str(line_number) + ': ' + str(error)) from error
    if not ended:
        raise AssemblyError('source requires a final END')
    if not items:
        raise AssemblyError('source contains no instructions')
    image, listing = {}, []
    for line_number, pc, mnemonic, operands, size in items:
        try:
            encoded = _encode(mnemonic, operands, pc, symbols)
            if len(encoded) != size:
                raise AssemblyError('instruction size changed between assembly passes')
            for offset, byte in enumerate(encoded):
                address = pc + offset
                if address in image:
                    raise AssemblyError('overlapping code at ' + format(address, '04X') + 'H')
                image[address] = byte
            listing.append(dict(line=line_number, address=pc,
                                instruction=mnemonic + (' ' + ','.join(operands) if operands else ''),
                                bytes=encoded.hex().upper()))
        except AssemblyError as error:
            raise AssemblyError('line ' + str(line_number) + ': ' + str(error)) from error
    return Assembly(image, symbols, tuple(listing))


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def build(source, output_dir, *, check_against=None):
    """Build into a new directory only; reference checks happen before writes."""
    source, output_dir = Path(source), Path(output_dir)
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError('Output directory must be new: ' + str(output_dir))
    raw = source.read_bytes()
    assembly = assemble(raw.decode('utf-8-sig'))
    encoded = hex_codec.encode_hex(assembly.image).encode('ascii')
    if hex_codec.decode_hex(encoded.decode('ascii')) != assembly.image:
        raise AssemblyError('internal HEX round-trip mismatch')
    reference_raw = None
    if check_against is not None:
        reference_raw = Path(check_against).read_bytes()
        reference = hex_codec.decode_hex(reference_raw.decode('ascii'))
        if reference != assembly.image:
            address = next(address for address in sorted(reference.keys() | assembly.image.keys())
                           if reference.get(address) != assembly.image.get(address))
            raise AssemblyError('reference differs at code address ' + format(address, '04X') + 'H')
    addressed = b''.join(address.to_bytes(2, 'big') + bytes([assembly.image[address]])
                         for address in sorted(assembly.image))
    hex_name = source.stem + '.hex'
    manifest = dict(
        builder='proteus86_demo_subset_v1', builder_source_sha256=_digest(Path(__file__).read_bytes()),
        hex_codec_source='build_matrix_firmware.py',
        hex_codec_source_sha256=_digest(Path(hex_codec.__file__).read_bytes()),
        source=source.name, source_sha256=_digest(raw), hex=hex_name, hex_sha256=_digest(encoded),
        program_bytes=len(assembly.image), address_min=min(assembly.image), address_max=max(assembly.image),
        addressed_bytes_encoding='ascending address: uint16 big-endian address then uint8 value',
        addressed_bytes_sha256=_digest(addressed),
        reference_hex_sha256=_digest(reference_raw) if reference_raw is not None else None,
        reference_address_bytes_equal=True if reference_raw is not None else None,
        reference_hex_bytes_equal=encoded == reference_raw if reference_raw is not None else None,
        external_tools_used=False, native_simulation_executed=False,
        scope='Source-to-instruction-byte reproducibility only; no firmware execution or native validation',
        symbols=dict(sorted(assembly.symbols.items())), listing=list(assembly.listing))
    output_dir.mkdir(parents=True)
    (output_dir / hex_name).write_bytes(encoded)
    (output_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True, help='new build directory')
    parser.add_argument('--check-against', type=Path, help='optional exact Intel HEX address/byte reference')
    args = parser.parse_args()
    try:
        result = build(args.source, args.output_dir, check_against=args.check_against)
    except (AssemblyError, hex_codec.AssemblyError, OSError, UnicodeError) as error:
        parser.exit(2, str(error) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key not in {'symbols', 'listing'}}, indent=2))


if __name__ == '__main__':
    main()
