# Independent 8051, 4×4 keypad and eight-digit example

Use the maintained `examples/draw_matrix_display.py` in the tool checkout. It generates a generic independent project/firmware rather than distributing a user's course submission. Read its `--help` for current options.

```powershell
python examples/draw_matrix_display.py --output-dir output/matrix_display_new --probes
```

## Public preparation and native verification

From the checkout, choose two different new output directories. A successful first command does not turn its files into a native run:

```powershell
python scripts/verify_matrix_display.py --output-dir artifacts/matrix-prepare-091-NEW
python scripts/verify_matrix_display.py --output-dir artifacts/matrix-native-091-NEW --execute-native --temp-dir D:/Proteus86Temp/matrix-091-NEW
```

Default preparation rebuilds the independent HEX, generates 48 parts with probes, checks the complete 29-net contract and prepares 5/5/5/1 groups without launching Proteus. It records `scope='file_contract_preparation_only'`, `status='prepared'`, `native_run_completed=False`, `simulation_executed=False`. `passed=True` here means file preparation only. A compatible local installation/template is required for library/template data; vendor/private fixtures are not distributed.

The native command explicitly launches only new owned processes and requires a new absolute ASCII `--temp-dir` separate from the new output, with neither directory nested in the other. File preparation uses its output's `tmp` and does not fall back to system TEMP. Add `--capture` to the second command only when an unlocked connected interactive desktop and the checked Pillow window API are available; capture brings only the owned window forward. Do not run native/UI work during a game. Reusing either output directory is rejected rather than overwriting its evidence.

The new script writes top-level `result.json`, rebuilt `firmware-build/`, generated `source/`, `verification-contract.json` and prepared controls. Native TEMP additionally retains per-case evidence and grouped `batches/control-results.json`. Completion requires all 16 keys and 25 accepted reconstructed-display records, expected displays/counts, diagnostics, source preservation and owned-process cleanup. Actual samples and windows come from that run. If launch was requested but no owned PID was observed, launch state may remain unknown; request/attempt alone is not proof of a running process. Interrupted/cancelled/partial attempts remain unpassed and keep available checkpoints; an I/O error must not mask a propagating interruption.

The actual 0.9.1 public CLI run passed all 16 sequential keys in 5/5/5/1 groups, 25 accepted reconstructed displays, 658 native SDF samples and 118 actuator readbacks. Every reconstruction required at least two agreeing full scans. Finite hold/count/display and K0 short-pulse/bounce/rearm assertions, diagnostics and source preservation passed; all four owned processes closed gracefully. Its owned running capture showed `01234567` with .372412/.422412/.472412 seconds before/after/pause. These are fresh results summarized in `docs/validation/v0.9.1.json`, separate from historical 0.9.0's 670 samples below.

## Revised layout and caption API

The 0.9.1 48-part profile alternates DS1 terminal captions over two rows and keeps MCU/probe terminals on their actual pin-exit direction with short straight stubs. X1's caption is moved out of its wire corridor. The example calls the public caption-position API rather than mutating private terminal records; see [file-workflow.md](file-workflow.md) for absolute native units and reset behavior.

The 32-part profile recorded 102/104 straight wires and the 48-part profile 118/120; both had four bends and zero reported overlap/non-node-contact/near-parallel issues at default and one-native-unit minimum parallel-span checks. Thirty-five conservative text warnings remain. These are drawing metrics for the explicit example, not electrical checks or proof of universal optimal routing. Native save/fresh-independent-reopen passed for both profiles: net29/SDF39, full known pins/properties, models/positions/values, wire/junction geometry and terminal-caption anchors were retained, sources stayed unchanged and four newly owned processes closed gracefully. The dynamic run and running image remain separate acceptance scopes.

## Rebuild firmware without a vendor compiler

The independently authored source and a strict project-owned 8051 assembler use only Python's standard library:

```powershell
python examples/build_matrix_firmware.py --output-dir output/matrix_firmware_new --check-against examples/matrix_display.hex
python examples/draw_matrix_display.py --output-dir output/matrix_rebuilt_new --firmware output/matrix_firmware_new/matrix_display.hex --probes
```

The builder emits `matrix_display.hex` and deterministic `manifest.json` with source/builder/HEX hashes, symbols and encoded address/byte evidence. `--check-against` compares decoded addresses and machine bytes; the compared HEX is not an input to code generation. The current independent program occupies 235 bytes. No Keil binary, library, runtime or existing HEX template is invoked by this build.

Read `examples/matrix_firmware_build.md` in the checkout for the exact supported assembly subset and error boundaries. This is a restricted example assembler, not a general A51/Keil replacement. A matching rebuild is file/reproducibility evidence; it does not execute the firmware or establish debounce/display behavior in Proteus.

## Generated project and requested evidence

The output contains `matrix_display.pdsprj`, `expected_nets.json`, `design.json`, `preview.svg`, `result.json` and adjacent `resources/firmware/`. Move the whole directory. A compatible local template and device libraries are still required; source distribution does not include them.

`design.json` is example metadata, not the sectioned text accepted by CLI `netcheck --design`. Check the generated expected-net list directly:

```python
import json
from pathlib import Path
from proteus86.inspection import netcheck

folder = Path('output/matrix_display_new')
expected = json.loads((folder / 'expected_nets.json').read_text(encoding='utf-8'))
assert netcheck(folder / 'matrix_display.pdsprj', expected)['passed']
```

The circuit has 32 components, or 48 with `--probes`. Its ordered probes are `PS0`…`PS7` for A…G/DP (the model's eighth segment pin is named H) and `PD0`…`PD7` for digit selection. Segments are high-active, digit selects low-active. The independent firmware initializes to `01234567`; after an accepted key the first six positions remain `012345`, the next is an acceptance counter modulo 16, and the last is key 0…F. This counter distinguishes a new response from repeated writes of an unchanged key value. Use the source's actual debounce/hold assumptions when writing expectations.

Inspect the generated design/metadata and `netcheck` requested nets. Native acceptance is a separate opt-in workflow on a fresh copy: require actual time, diagnostics, frame reconstruction and coverage of each requested key group. A generated file or copied HEX alone is not a native run.

## Native power/model boundary

For this selected AT89C51RD2/DIL40 definition, `PP(VCC)=40` and `PP(GND)=20` supply native global-name bindings. The generator omits two redundant explicit terminal stubs on those pads, while retaining all 29 expected logical nets including pads 40/20. Logical checking uses verified selected-package PP declarations; the `physical=True` view remains explicit physical connections. Never re-add those stubs just to satisfy file checks or extrapolate their failure to every MCU/hidden pin.

A controlled 48-component native comparison changed only those two stubs and reached 0.22 seconds; it establishes startup viability for that copy, not all-key/display/debounce/long-hold behavior. The example also selects the real `DEVICE/CAP` model explicitly. That separate model clarification is not the controlled SPICE root cause, and a 0V reference is not inherently invalid.

Read actual native `diagnostics()` on startup failure. Correct logical SDF membership does not prove that SPICE initializes or that native time advances. Keep failed attempts and their errors separate from later successful copies.

Sixteen keys need independent prepared groups because each binary control uses two of ten native key slots. Do not claim simultaneous 16-key control. Eight-digit reconstruction combines scan phases using explicit segment/digit polarity and a stability window; it does not measure brightness, voltage or physical hardware.

For a running image use `Simulation.capture()` after firmware initialization. For text/key assertions use digital probes/helpers. An image and a stable word do not establish response counts when repeated writes look identical.

This is a tool demonstration, not a replacement for user requirements. Keep submitted reports, private program variants and personal information outside the source repository.

## Completed 0.9.0 native scope

The independent example passed all 16 keys in sequential independent groups of 5/5/5/1. Each key was pressed for .08 native seconds and kept held for .12 more seconds before eight-character display/modulo-16 acceptance-count checks; all matched the single-response expectation. K0 additionally rejected a .003-second short pulse and three .002/.003-second press/release bounce cycles. After stable release and repress its count advanced 1→2.

The run collected 25 reconstructed display records and 670 native SDF samples. Every accepted record required at least two agreeing complete scan reconstructions; these are non-atomic display windows. Native diagnostics and source preservation passed. Four owned processes closed gracefully with no forced cleanup. The 48-part example also passed unlocked running capture and independent save/fresh-reopen compatibility, separately from the digital assertions.

This covers the independent firmware, ordered single-key grouping and the stated finite hold/bounce/sample windows. It is not simultaneous 16-key operation, arbitrary-duration holds, voltage/brightness or physical hardware validation. Earlier failed/interrupted/partial attempts stay unpassed. Historical course direction/speed and unrelated counter programs were not relabeled as rerun.
