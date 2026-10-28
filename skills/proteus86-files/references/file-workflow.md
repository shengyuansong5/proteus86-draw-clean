# File parameters and routing repairs

Read this for generation, editing, firmware binding or file/geometry failures. Native running screenshots and save compatibility use [native.md](native.md); digital readback uses [digital.md](digital.md).

The Codex installer copies the whole skill tree, including these references. Its installed `.proteus86-install.json` identifies the local checkout; that machine-local locator is configuration and must not be added to a source publication. Updates require `--update` and keep a verified full backup under the selected Codex home's `skill-backups/`, outside automatic skill discovery. Unknown local files are retained. A failed publication restores the prior live directory where possible; retained staging/backup paths are reported if an external replacement or cleanup lock needs review.

## Parameter conventions

| Interface | Convention |
|---|---|
| `add_mm`, `move_mm`, `translate_mm`, text `at=x,y` | Millimetres; Y increases upward |
| `set_route(first, second, points=...)` | Native integers: 100000 = 1 mm; exact pin endpoints in caller first/second order |
| `add_terminal(..., position=(x,y))` | Native integers; use `(mm(x), mm(y))` for millimetre input |
| `terminal_label_position(id)` | Read-only absolute terminal-caption anchor in native integers |
| `set_terminal_label_position(id, position)` | Two absolute signed-int32 native coordinates, or `None` for the current default anchor; retains font/style |
| Component/terminal `rotation` | Degrees, multiples of 90; 0, 90, 180 and 270 are ordinary choices |
| Terminal `rotation=None` | Choose from the real pin exit; prefer this unless explicit geometry requires a direction |
| Text design `deg=90` | Component rotation in degrees |
| Pins | Real logical name (`U1.P1.0/T2`) or physical number (`U1.1`) |
| `connect_net(...)` | One shared multi-pin net |
| `connect_bus(...)` | Separate corresponding signals, not a short across every signal |
| `set_property_visibility(ref, KEY=False)` | Display flag only, without removing the model/property value |
| `bind_firmware(ref, path, visible=False)` | Checked local firmware; Unicode and spaces accepted at this high level |

Query identity before wiring unfamiliar models:

```powershell
python -m proteus86 search CRYSTAL
python -m proteus86 device CRYSTAL --library DEVICE
python -m proteus86 inspect input.pdsprj --geometry
```

Device values can be model inputs: a relay value can be its rated voltage (`5V`). Do not substitute an unrelated model merely to make parsing succeed.

## Move a terminal caption through the public API

Take the intended terminal ID from `c.terminals()`; it is not the electrical net name. Duplicate visible names do not identify one terminal. For an existing `terminal_id`:

```python
from proteus86 import mm

x, y = c.terminal_label_position(terminal_id)
c.set_terminal_label_position(terminal_id, (x + mm(1.27), y))
# To restore the anchor for its current glyph/orientation:
# c.set_terminal_label_position(terminal_id, None)
```

The pair is an absolute schematic anchor, not an offset from the part or pin, and uses 100000 native units per mm. Both values must be actual signed-int32 integers; floats and booleans are rejected. Unknown/ambiguous IDs fail. Reading does not mutate an uncustomized terminal. Setting/resetting preserves font/style and electrical identities, participates in batch rollback and is saved/reopened normally. Use this API instead of editing private `_terminals` label records. It does not turn estimated text clearance into electrical clearance.

## Model-defined PP power pins

Use the actual selected PACKAGE definition and complete logical-to-physical pin mapping. A declaration such as `PP (VCC)=40` is native global-name power connectivity, not a drawn wire. The logical partition view can merge only verified declarations whose named pin and complete pad mapping match the instance; unknown, mismatched or ambiguous definitions do not justify inferred connections. `physical=True` continues to show explicit physical connectivity without adding global PP joins.

The independent matrix example selects AT89C51RD2/DIL40, whose observed definitions bind VCC pad 40 and GND pad 20 natively. It no longer adds explicit terminal stubs to these two automatically supplied pads. A controlled 48-component comparison kept everything else unchanged and removed only those two redundant stubs; native time then advanced to 0.22 seconds. This identifies that example's startup failure and does not establish a universal rule for every hidden pin, MCU or power configuration.

Keep all 29 expected logical nets, including pads 40/20. If file checking disagrees with verified native PP bindings, inspect the definition/logical-view support; do not drop expected power pins or add redundant stubs just to make the report pass. The example separately uses the explicit `DEVICE/CAP` capacitor model. That model clarification was not the controlled SPICE root-cause finding; a valid 0V reference is not inherently an invalid configuration.

A netlist may compare correctly while native SPICE initialization fails. Preserve native error diagnostics and require actual time before reporting runnable simulation; see [native.md](native.md).

## Reliable edits

```python
from proteus86 import Circuit, mm

c = Circuit.open('input.pdsprj')
with c.batch():
    c.update('R1', value='22k')
    c.move_mm('C1', 38.1, 0)
    c.connect_net('R1.2', 'C1.2')
    c.add_terminal('label', 'SENSE', 'R1.1',
                   position=(mm(-12.7), mm(0)), rotation=None)
    c.arrange_labels()
    c.arrange_terminals()
c.fit_sheet()
c.save('output/edited/circuit.pdsprj')
```

Use fresh outputs. `batch()` validates/routes once and restores in-memory edits if an exception or interruption escapes. Published files or verified immutable resource copies can remain after cancellation; a forced process kill cannot run Python cleanup.

`route` keeps placement and existing explicit connections unless `--replace` is selected:

```powershell
python -m proteus86 route input.pdsprj -o output/routed.pdsprj --net 'R1.2,C1.2' --net 'C1.1,GND'
```

Use `arrange_modules()` or JSON `layout.modules` for explicit LED/resistor arrays and separate clock/reset/input/output origins. Movement preserves connectivity but still needs saved topology checks. `fit_sheet()` fits actual wires; `tidy_labels()` retains devices/wires while moving estimated colliding labels.

## Routing failure: use pin geometry rather than uniform rotations

Do not force every terminal/label to `rotation=0`. It may point into a component or require a blocked escape corridor. Inspect the target pin's `position` and `direction`, initially keep `rotation=None`, and place the label along the exit. Explicit directions depend on the pin and label side.

Dense probes can obstruct another pin's escape. Start with a generously spaced row/grid, e.g. 10.16 mm, and keep labels/terminals outside exit corridors. This is a layout starting point, not a universal electrical/model minimum. Fixed MCU pin pitch cannot be enlarged by moving a probe.

Keep requested nets while changing placement, terminal direction, probe spacing or orthogonal waypoints. Do not drop a troublesome connection or relax the exit/diagonal guard.

When a fresh layout calculates both component labels and terminal positions, arrange labels before choosing terminal corridors. In the matrix/display example, moving U1's reference text after terminal placement obstructed its VCC escape; `arrange_labels()` followed by `arrange_terminals()` avoided that conflict. If later label edits change the obstacles, recheck exits and intentionally reposition affected terminals rather than changing all rotations.

| Symptom | Meaning and repair |
|---|---|
| `Pin escape is obstructed` | A body/label/terminal/probe blocks the named pin. Inspect that exit and move the obstacle or orient that terminal appropriately. |
| `No route` / visibility grid too large | The bounded router found no permitted path. Increase spacing or supply valid orthogonal geometry; preserve obstacles/nets. |
| Terminal name missing/detached | A bare expected name needs an attached terminal. Create or connect it before `netcheck`. |
| `Invalid property value` / `PropertyError` | Read component/property/reason/hint. Use high-level firmware binding for paths and printable ASCII for ordinary model properties. |
| `Unknown property for visibility` | Assign a declared value first. Only declared `PROGRAM` display may be deferred; spelling mistakes still fail. |
| `Unknown entity layout` after native save | Follow [native.md](native.md); preserve the file and compare native re-open/netlists rather than rewriting unknown bytes. |

## Firmware and portable projects

`bind_firmware()` and high-level `PROGRAM=path` copy checked firmware. Ordinary `save()` puts content-addressed ASCII-relative images under adjacent `resources/firmware/`; source/output hashes must match. Move the whole folder. Rebind after recompiling.

Relative firmware uses the opened project's directory or a new design's current/`resource_base` directory. Plain unresolved ASCII placeholders can remain while drawing; strict packaging/running must resolve them before readiness is claimed.

```powershell
python -m proteus86 bind-firmware input.pdsprj -o output/bound/circuit.pdsprj --firmware 'U1=firmware/中文 固件.hex'
python -m proteus86 package input.pdsprj -o output/package_new --firmware 'U1=firmware/image.hex'
```

`package`, `prepare-run` and `firmware-info` do not launch Proteus. Packaging covers external PROGRAM images, not arbitrary model/image dependencies or embedded VSM Studio builds.

## Current matrix layout profile

The 0.9.1 independent 48-part example alternates DS1 terminal captions between two rows, keeps MCU/probe stubs on their actual cardinal pin exits and moves X1's caption out of the wire corridor. It uses public caption positioning. Its explicit profile recorded 118/120 straight wires and four bends, with no reported overlap/non-node-contact/near-parallel issue at the default and one-native-unit minimum parallel-span audits. Thirty-five conservative text warnings remain; record them without deleting nets or calling them SPICE errors.

Both revised profiles passed native save and fresh independent reopen: 32 parts had 102/104 straight wires, 48 parts 118/120, with four bends each and no reported overlap/non-node-contact/near-parallel issues at both thresholds. Each kept 35 conservative label warnings. Complete known native pin partitions/properties, models/positions/values, wires/junctions and caption anchors matched; net29/SDF39, source preservation and all four owned graceful closures passed. The separate public CLI also passed current 16-key dynamics with 25 reconstructions, 658 native samples and 118 actuator readbacks; older 670 samples remain 0.9.0 history.

A paired file-generation comparison used one current core/Python 3.12.14/template/explicit firmware, three interleaved pairs per size (12 generations total). Median generation time changed 1.89940→1.62266 seconds for 32 parts (14.57% less) and 2.28485→1.95703 for 48 (14.35% less), retaining complete logical/physical/model/firmware equivalence. This describes these example strategies, not a general core speedup, arbitrary-circuit optimizer or native simulation benchmark.

## Acceptance

```powershell
python -m proteus86 netcheck output/new/circuit.pdsprj --design design.txt
python -m proteus86 wiringcheck output/new/circuit.pdsprj
python -m proteus86 wire-quality output/new/circuit.pdsprj --min-gap 2.54 --min-parallel 2.54
python -m proteus86 render output/new/circuit.pdsprj -o output/new/preview.svg
```

Save/reopen/netcheck checks topology. `wiringcheck` includes approximate text/symbol warnings; `--strict` promotes cosmetics to failure. `wire-quality` checks overlaps, non-node contacts, parallel gaps and bends, exempting only real referenced junction endpoints. It is not a global rerouter, full text/widget clearance calculation or electrical/simulation proof.
