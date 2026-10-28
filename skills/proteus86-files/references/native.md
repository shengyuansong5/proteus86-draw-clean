# Native save compatibility and running screenshots

Use this when native compatibility, a running image or actual simulation is requested/needed. Native APIs create independent PDS processes. During games defer native/UI checks; never operate or close unrelated PDS processes.

## Save/reopen and an unsupported native result

Keep a compatible pre-save source and work on a new copy with its resources. After native save, try `Circuit.open(saved)` and compare requested nets, model values and saved geometry. A Python refusal such as `Unknown entity layout` can coexist with a native project that opens and exports a valid netlist.

Run `python -m proteus86 diagnose saved.pdsprj`. Retain the rejected file and diagnostic. The additionally recognized form is the observed **2048-byte all-zero entity extension for AT89C51RD2**, retained unchanged. Its purpose has not been inferred. This specific 32-component case passed native save, Python reopen/netcheck and a fresh independent native reopen/SDF comparison in the 0.9.0 run; this editor acceptance does not certify its dynamic behavior. Other lengths, nonzero payloads and unverified models still fail; this is not a generic persisted simulator-data parser.

When Python still refuses a native file:

1. Preserve it and make a private working copy with resolvable adjacent resources. Do not change headers, delete objects, patch bytes or substitute models.
2. Open that copy in an owned native `Session`, export SDF and save. Close that session.
3. Use a **fresh independent** owned `Session` to reopen it and export another SDF.
4. Compare component identities/model values and full known pin partitions before/after. If a supported pre-save circuit is available, also run `verify_netlist(expected_circuit, sdf)` for its expected connections/terminals.
5. Report native re-open/netlist and Python readback separately. Native preservation does not make unsupported Python editing safe; continue edits from the supported source or rebuild explicitly from verified topology.

```python
from proteus86 import Session
from proteus86.verification import verify_netlist

# saved_copy is private; expected_circuit came from the supported pre-save input.
with Session(saved_copy) as first:
    before = first.export_netlist('output/check/before.sdf')
    first.save()
with Session(saved_copy) as fresh:
    after = fresh.export_netlist('output/check/reopened.sdf')
verify_netlist(expected_circuit, before)
verify_netlist(expected_circuit, after)
```

Also compare complete native membership when unrequested/dangling/hidden pins matter; a count or selected expected nets alone does not prove all topology unchanged. `Session.save()` waits for stable complete ZIP snapshots, not a format-support guarantee. Editor/netlist work is not a simulation run.

Use owned contexts for normal cleanup. If closing fails on an unexpected native dialog, record that failure/PID and terminate only that session's still-live `session.process` handle with a bounded wait. Do not choose Discard in an unknown dialog or close every PDS process.

## Startup menu readiness

An owned main window may be ready before its Netlist Compiler menu becomes enabled. `Session.menu(path, timeout=15)` waits only for a unique exact-path match that is currently disabled. It rechecks the live process, PID, main-window identity/profile and full menu on every poll, then re-reads the current command immediately before dispatch. Missing or ambiguous paths, a missing menu and changed process/window ownership fail; command IDs are not cached. A bounded timeout remains failure, not permission to repeatedly send a stale command.

Eleven targeted regressions cover the wait and rejection paths. The subsequent native 32/48-component run passed both native save and a fresh independent reopen for each example, with Python readback, all 29 expected logical nets, 39 native networks and complete known native pin-partition/property equality. All four owned processes closed gracefully and sources remained unchanged. The earlier disabled-menu failure is retained as pre-fix evidence. This editor/readiness acceptance does not verify digital behavior.

## Interruptions before a context is returned

`Session` construction and `Simulation.open()` can fail after PDS starts but before the caller receives its context. In 0.9.1 they catch BaseException, clean only the constructor's exact owned Popen, attach startup evidence such as `owned_pid`/`process_closed` and re-raise the original exception. Batch results preserve those fields even when local `sim` was never assigned. Never replace this with a process-name scan or global termination.

Two controlled real-PDS checks interrupted after the verified native profile and confirmed owned cleanup plus the same KeyboardInterrupt rethrow; the group partial record remained `status='interrupted'`, `passed=False`, `native_run_completed=False`. No simulation ran in those guard tests. Eleven targeted regressions also cover interruption/cleanup/checkpoint behavior. If writing a checkpoint fails while an interruption is already propagating, retain/annotate the recording error without swallowing that interruption. Forced Python termination/power loss still cannot run cleanup.

## Actual native time

```python
from proteus86 import Simulation

with Simulation.open('input.pdsprj', 'output/run_new') as sim:
    result = sim.run_for(0.25)
    assert result['state'] == 'paused'
    print(result['simulation_seconds'], sim.diagnostics())
```

Check actual `simulation_seconds`, elapsed/target tolerance, diagnostics and process cleanup. `start()` resumes a native state; **ANIMATING/running is not proof of advancing time**. A residual timed breakpoint can leave a running status at a fixed time. Set a fresh target via `run_for()` or use capture below. A menu or wall-clock sleep is not simulation completion.

The status reader binds the initially unique main status widget. If a debugger adds another widget with the same control ID, it keeps the original widget identity and rechecks PID on every read; it never selects an arbitrary matching row or caches native time. A changed/lost identity is a failed session requiring a new owned open.

Keep binary/PID/profile guards. Embedded builds and arbitrary waveform/model-memory acquisition remain unsupported; failed/interrupted/cancelled records remain unpassed.

## Native startup and log diagnostics

A correct SDF comparison establishes topology, not successful SPICE initialization. If `run_for()` fails or time remains stopped, preserve the failed report and inspect `sim.diagnostics()`/`sim.log()` before changing timers or claiming a working run. Three controlled native failure groups in this cycle actually exposed SPICE initialization errors through the debugger log.

Log discovery is PID-scoped and requires real parent/owner chains, exact signatures and a unique list. The observed error hierarchy is `VSM Debugger` (`LX_APPLN_DClkNoDC`, id 101) → `Log Window` (same class, id 0) → `SysListView32` (id 1). The independent normal `Simulation Log` window is `LX_APPLN_DClkNoDC`/id 0 containing `SysListView32`/id 1; it is not a standard `#32770` dialog. Matching a title or flat descendant list alone is insufficient. The strict hierarchy has offline regression coverage. In the unlocked successful capture path, native diagnostics read the independent normal Simulation Log through this verified owner chain; no VSM Debugger was open. Both failed-debugger-log and normal-log native evidence are now present, without publishing transient Win32 handles or process IDs.

The matrix startup controlled comparison removed only redundant explicit terminals on the selected AT89C51RD2/DIL40 PP-bound VCC/GND pads. The otherwise unchanged 48-part copy reached 0.22 native seconds. Keep all expected logical power nets, and do not equate logical global-name PP binding with a physical wire/stub; see [file-workflow.md](file-workflow.md). This is not full matrix dynamic acceptance or a general diagnosis of all hidden pins, capacitor aliases or 0V configurations.

## Capture a running, owned window

```python
with Simulation.open('input.pdsprj', 'output/capture_run_new') as sim:
    sim.run_for(0.2)  # firmware-specific initialization
    report = sim.capture('output/images/running-new.png',
                         advance_seconds=0.01, fit=True)
    assert report['passed']
    assert report['paused_after_capture']['state'] == 'paused'
```

`capture(destination, *, advance_seconds=.01, animation_seconds=10000, timeout=20, fit=True, width=1600, height=1000, foreground=True)`:

- Requires a new `.png` and adjacent `.png.json`; refuses existing outputs.
- Reads WTS session state before window preparation; a known locked or disconnected session is refused.
- Fits/resizes only its owned window and sets a fresh verified native timer.
- Requires native time advance before and after the image, then leaves paused. Failure attempts to pause and retains a failed report.
- Captures only the owned window. `foreground=True` requests activation of that window; Windows may refuse foreground requests. The image must contain the verified real main canvas (8.6 profile control id 5) with a non-uniform interior. A blank canvas is an explicit failure even when toolbars, window borders or the overview are visible; non-uniform pixels alone do not prove correct circuit rendering.
- Requires optional `Pillow>=11.2.1`; ordinary file APIs do not import Pillow. The explicit `ImageGrab.grab(window=...)` parameter is checked before changing a window and again before capture. A generic `**kwargs` is not sufficient support.

Install into the Python environment used for this checkout with `python -m pip install -e ".[capture]"`, or `python -m pip install --upgrade "Pillow>=11.2.1"`. Windows HWND capture was added in [Pillow 11.2.1](https://pillow.readthedocs.io/en/stable/reference/ImageGrab.html#PIL.ImageGrab.grab). Missing or incompatible backends raise a repair message; capture does not fall back to the full desktop.

Check `passed`, `simulation_executed`, `before_image`, `after_image`, `paused_after_capture` and diagnostics. A passed capture certifies an image of an advancing engine, not correct digit text, a whole multiplexed frame, LED brightness/current, voltage or electrical correctness. Use probes/assertions from [digital.md](digital.md) for functional evidence.

| Symptom | Next step |
|---|---|
| ANIMATING/running with fixed time | Set a fresh `run_for`/capture timer and require actual clock growth. |
| Black digits in a paused image | Capture during verified time advance; paused rendering can show one blanked scan phase. |
| Locked desktop / blank main canvas | Unlock the interactive Windows desktop and retry. Main canvas content, not toolbars/minimap/borders, must be visible. Never bypass the guard or substitute a desktop image. |
| Timer overshoot/unknown clock | Preserve failure diagnostics; do not enlarge tolerance merely to claim success. |
| Netlist Compiler uniquely present but disabled after open | Use the bounded `Session.menu()` readiness wait. Missing/ambiguous paths or changed ownership still fail; never cache/retry a stale command ID. |
| Unknown binary/profile | Use the supported build or independently validate an adapter; never bypass the fingerprint guard. |

## Current 0.9.1 and historical acceptance

The public 0.9.1 CLI completed the current native matrix run: 16 sequential keys in 5/5/5/1 groups, 25 reconstructed-display records, 658 native SDF samples and 118 actuator readbacks, with actual-time/readback/display/count/diagnostic assertions passed. Four owned processes closed gracefully and sources stayed unchanged. See [digital.md](digital.md) for its finite-window and non-atomic boundaries.

Its unlocked owned-window capture passed with before-image .372412 seconds, after-image .422412 and final pause .472412. The main canvas was nonblank and visually showed `01234567`; diagnostics had no errors/warnings. An image alone still reports no digital-function certification, and the PNG remains local evidence.

Both revised 32/48-part projects passed native save and fresh independent reopen, using four newly owned processes closed gracefully. Python readback/net29/SDF39, full known native pin partitions/properties, models/positions/values, wire/junction geometry and terminal-caption anchors matched; sources stayed unchanged. Drawing audits passed default and one-native-unit minimum parallel spans, with 102/104 and 118/120 straight wires respectively, four bends each and zero reported overlap/non-node-contact/near-parallel issues. Each retains 35 conservative text warnings. This editor acceptance is separate from native dynamic assertions.

Run `scripts/verify_matrix_display.py` using the distinct file/native commands in [matrix-example.md](matrix-example.md). Default preparation still does not launch a process; explicit native mode requires a new separate absolute ASCII TEMP, with optional capture requiring an unlocked connected desktop and the checked Pillow window API. Current root regressions were 295 passed/zero skipped in 120.379 seconds; final scope is in `artifacts/validation_v091.json`. Historical results below remain unchanged.

The 0.9.0 unlocked 48-component capture passed the live checks: initial native .22 seconds, .27 before the image, .37 after it and paused at .37. The real main canvas was nonblank; native diagnostics had zero errors/warnings, the source remained unchanged and the owned process closed. Visual inspection of that image showed initial `01234567`. The capture result still reports `digital_function_verified=False`: an initial word/image is not all-key, debounce or long-hold acceptance. The PNG remains local evidence and is not included in public source.

The historical 0.9.0 menu-readiness run passed both 32- and 48-component Python reopen/netcheck of all 29 expected nets, with two independent native save/fresh-reopen phases per example, 39 native networks and complete known native pin-partition/property equality. Four owned processes closed gracefully and sources remained unchanged. These are editor/save compatibility checks, distinct from the capture's actual-time evidence.

An earlier image whose native clock advanced but whose main canvas was blank remains invalid screenshot evidence even if its older report has a passed flag. The earlier locked-desktop rejection remains a valid failed negative test; do not change it to passed or weaken WTS/canvas guards. A separate historical 0.9.0 independent matrix native run also passed 16 sequential keys in 5/5/5/1 groups, using 25 reconstructed display records and 670 SDF samples with at least two agreeing complete scans each. Every key matched its expected display/count after .08 s press plus .12 s hold; K0 additionally passed short-pulse/bounce rejection and stable-release/repress count 1→2. Diagnostics/source preservation passed and four owned processes closed gracefully without forced cleanup. See [digital.md](digital.md) for the finite-window, non-atomic and single-key boundaries; historical course direction/speed scenes were not rerun.
