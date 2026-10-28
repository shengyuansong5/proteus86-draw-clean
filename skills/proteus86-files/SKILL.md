---
name: proteus86-files
description: Create, place, route and inspect saved Proteus 8.6 schematics with Python, and run owned native digital checks when requested. Intended for Codex; other AI harnesses require adaptation and independent validation.
---

# Proteus 8.6 file workflow for Codex

This skill, its default workflow and installer target **Codex**. Other harnesses must adapt skill loading, filesystem/terminal tools, permissions and local paths, then validate their own integration. Reusable Python interfaces are not evidence that another harness is integrated.

## Locate the tool and choose the operation

Run commands from the checkout containing `proteus86/` and `pyproject.toml`, using Python 3.10+. An installed skill directory contains instructions, not the runtime. Its `.proteus86-install.json` records the local `checkout_root`; otherwise use the current task's checkout. Configure libraries/template with `PROTEUS86_HOME` and `PROTEUS86_TEMPLATE`, then run `python -m proteus86 doctor`. Do not reinstall dependencies or rediscover the format for ordinary drawing.

- **Create/edit/wire:** use the file API/CLI. Read [file-workflow.md](references/file-workflow.md) for parameter units, terminal direction, portable firmware, layout and routing errors.
- **Native save compatibility or a running screenshot:** read [native.md](references/native.md). It includes native re-open/SDF fallback and `Simulation.capture()` with clock-advance checks.
- **Buttons, matrix keys or multiplexed digits:** read [digital.md](references/digital.md) for bindings, `simulation_seconds`, grouping and stable frame reconstruction.
- **8051 + 4×4 keypad + eight digits:** use the [complete example](references/matrix-example.md), which generates an independent project/firmware and states its validation limits.
- **Historical acceptance:** consult [history.md](references/history.md) only when a version or old result matters. Never present historical native runs as newly rerun.

## Work on a saved copy

For a new circuit, write a UTF-8 design and generate without desktop interaction:

```text
[parts]
R1 RES 10k
R2 RES 10k
[terms]
VCC POWER
GND GROUND
[nets]
R1.1,R2.1,VCC
R1.2,R2.2,GND
```

```powershell
python -m proteus86 generate design.txt -o output/new/circuit.pdsprj
python -m proteus86 netcheck output/new/circuit.pdsprj --design design.txt
python -m proteus86 render output/new/circuit.pdsprj -o output/new/preview.svg
```

For an existing project use `Circuit.open(path)`, group bulk mutations in `with c.batch():`, and save to a new destination. The batch routes once and rolls back on failure/interruption while re-raising it. Explicit `save(overwrite=True)` creates a checked backup; never overwrite the base template. Move complete project/resource folders together.

After connectivity changes, save, reopen and `netcheck` requested nets. Inspect geometry when placement matters. Cosmetic estimates do not replace connectivity acceptance or justify deleting nets. `wire_quality()` is a read-only saved drawing diagnostic, not a rerouter or electrical test.

## Preserve boundaries and report the right evidence

- Supported format: verified Proteus 8.6 SP2 build 23525, CDB v5 / FILEVER 814 / RELEASE 806, known single-sheet/single-unit objects. Keep format, ASCII, pin-exit and orthogonality guards. Do not alter headers, guess unknown binary structures, or rewrite rejected files.
- `Unknown entity layout` after native save does not mean Proteus failed. Preserve the file, run `diagnose`, and follow native re-open + SDF comparison in [native.md](references/native.md). File editing remains unsupported unless its actual structure is recognized.
- File checks prove saved topology. Native editor checks prove their stated save/re-open/netlist scope. Only actual native time, readback, diagnostics and requested assertions establish a native simulation result. ANIMATING, menu availability, wall time and an image alone are insufficient.
- Native APIs own new independent PDS processes: operate/close only those. During the user's game do file work and defer native/UI checks. Computer Use is for necessary UI operations unavailable through file/native APIs.
- Treat course/user files as read-only references unless changing them is authorized. Keep submissions, reports, private firmware and personal data outside the tool checkout. Publish reviewed tool sources and independent examples; do not distribute local Proteus binaries, libraries or templates.
- Implementation changes require meaningful regressions: `python -m unittest discover -s tests -v`. Keep file tests and native runs separate when practical. Report skipped tests, cancelled/partial runs and unsupported capabilities explicitly.

PCB routing, arbitrary voltage/waveform acquisition, embedded VSM Studio builds and physical hardware validation are unsupported. Sampled digital checks can miss intersample activity and do not measure LED brightness/current.
