# Rebuild the independent matrix/display firmware

This example's source and small assembler were independently authored for this
project. Python 3.10+ and its standard library are sufficient. The build does not
invoke or distribute Keil, its libraries, a vendor runtime, or an existing HEX
template. It generates machine instructions from the A51 text and resolved
labels. The repository's MIT license applies to these example sources.

From the repository root, choose a new output directory:

```text
python examples/build_matrix_firmware.py --output-dir output/matrix-firmware
python examples/draw_matrix_display.py --output-dir output/matrix-circuit --firmware output/matrix-firmware/matrix_display.hex --probes
```

The build writes `matrix_display.hex` and `manifest.json`. The manifest records
the builder, source and HEX SHA-256 hashes, occupied address range, byte count, each source
statement's encoded bytes and all resolved symbols. Its addressed-byte hash uses
ascending-address triples: a two-byte big-endian address followed by its data
byte. There are no timestamps or absolute local paths, so identical input gives
identical HEX and manifest bytes.

For comparison with a separately available image:

```text
python examples/build_matrix_firmware.py --output-dir output/matrix-firmware-compare --check-against examples/matrix_display.hex
python -m unittest discover -s tests -p test_matrix_assembler.py -v
```

Comparison checks decoded addresses and bytes, not merely textual HEX record
format. Comparison is optional and is never an input to instruction generation.
Changing an immediate operand changes its instruction byte; relocating labels
changes their encoded addresses and branch offsets. The independent example
currently occupies 235 bytes in two sparse ranges, with reset vector at 0000H
and initialization at 0030H. The included firmware can be regenerated solely
with the project-owned Python script.

## Strict assembly subset

The assembler deliberately supports this example's needs rather than arbitrary
A51 input. Symbols are case-insensitive. A semicolon begins a comment. Numeric
literals are decimal or A51 hex beginning with a digit and ending in `H`.
Only `SP` (81H) is predefined; other direct addresses are numeric or `DATA`
symbols. These directives are supported:

- `name DATA byte-address`
- `CSEG AT code-address` (16-bit absolute segments)
- `label:` (optionally followed by an instruction on the same line)
- `DB byte,...`
- one final `END`

Supported instruction forms:

| Mnemonic | Operands |
| --- | --- |
| NOP, RET | none |
| LJMP, LCALL, SJMP, JNZ | code target |
| MOV | A or R0..R7 from immediate; direct from immediate |
| MOV | A from direct, R0..R7 or @R0/@R1 |
| MOV | direct, R0..R7 or @R0/@R1 from A |
| MOV | direct from R0..R7; direct from direct; DPTR from immediate |
| MOVC | A,@A+DPTR |
| INC | A, R0..R7 or direct |
| CJNE | A,#byte,target; A,direct,target; R0..R7,#byte,target |
| DJNZ | R0..R7,target |
| ADD | A,#byte; A,R0..R7 |
| RL | A |
| ANL | A,#byte; direct,#byte |
| ORL | A,#byte |

Unsupported instructions, macros, includes, expressions, strings, relocatable
linking, bit addressing and implicit SFR names fail explicitly. Undefined,
duplicate or inappropriate symbols, byte/address overflow, relative branches
outside -128..127 bytes and overlapping code segments also fail. Intel HEX
supports data and EOF records in the 16-bit address space only; record counts,
checksums, overlaps and EOF are validated. This is not a general compiler or an
execution verifier.

## Firmware behavior and validation boundary

The firmware initially displays `01234567`. One qualified key updates its last
two digits to an accepted-press count modulo 16 and the key index 0..F. First K0
therefore gives `01234510`; after stable release and another K0, `01234520`.
Use one key at a time. Recommended native scenarios initialize for 0.22 seconds
and allow 0.08 seconds each for a stable press and release. Segment outputs are
high-active and digit selects are low-active.

A byte-identical rebuild establishes reproducibility. The build and its unit
tests do not launch Proteus, execute instructions or establish native dynamic
behavior. Native display, debounce, long-hold and all-key acceptance require
separate measured simulations.
