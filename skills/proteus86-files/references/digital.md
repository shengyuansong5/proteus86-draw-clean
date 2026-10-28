# Matrix controls and multiplexed digital observations

These are sampled native digital checks, not voltage/current/brightness or physical measurements. Records must identify backend, actual time, input readback, requested expectations and limitations.

## Inputs and probes

Native BUTTON and LOGICSTATE binary operation is verified. Bind before save/reopen: `c.bind_controls('K0', 'K1')`. Each control uses two INC/DEC slots from native keys 0–9, so a prepared run supports **at most five controls**. Changed/colliding bindings refuse dispatch.

Connect LOGICPROBE devices before save to observe outputs. Space them according to real symbols/pin exits; see [file-workflow.md](file-workflow.md). Crowded probes may block routing even if their text appears separated.

## observe is not a scenario frame

```python
reading = sim.observe(['QA0', 'QA1'])
now = reading['simulation_seconds']  # not actual_at
```

```json
{
  "backend": "proteus_native_sdf",
  "simulation_seconds": 0.125,
  "time_resolution_seconds": 0.000001,
  "probes": {"QA0": 1, "QA1": 0},
  "meaning": "sampled_native_digital_levels"
}
```

`actual_at` belongs to scenario sample records, not `observe()`. Observations use fresh paused-time SDF and require binary probe states. Unknown/X is an error, not zero. `control_state()` reports actuator position, not downstream voltage.

`sim.interact(controls={'K0': 1}, probes=['QA0'])` validates before sequential dispatch and returns shared `simulation_seconds`, `actions`, `observation` and `native_exports`. Advance native time afterward if propagation requires it. Snapshots are not cached across frames.

## Press, hold, release and bounce

```python
from proteus86 import Scenario

scene = (Scenario().bounce('K0', at=.02, intervals=[.01] * 4, state=1)
         .release('K0', at=.6))
report = sim.run_scenario(scene, probes=['Q0'], until=.8,
                          sample_every=.02, expected_changes={'Q0': 1})
```

Choose firmware-specific settling/sample intervals. Times are relative to the paused baseline. Timer tolerance must be below half the smallest event/sample interval; timing failures stay failed. Counts cover sampled edges and may miss intersample pulses.

Scenario progress/checkpoints support cancellation and partial records. Cancelled, callback-failed or exited-process results remain unpassed. KeyboardInterrupt/SystemExit saves partial evidence and is re-raised. Use an owned Simulation context for cleanup.

## Matrix groups and display frames

Maintained `proteus86.digital` helpers prepare separate control-group copies and reconstruct digit frames; see the [complete example](matrix-example.md). Sixteen keys are tested across independent batches, not by claiming simultaneous 16-key native bindings.

```python
from proteus86.digital import prepare_control_batches, read_display_frame

groups = prepare_control_batches('matrix_display.pdsprj', 'output/key_groups_new',
                                 controls=[f'K{i}' for i in range(16)], batch_size=5)
# groups['groups'] holds each fresh project's controls/project paths.
frame = read_display_frame(sim,
                           segments=[f'PS{i}' for i in range(8)],
                           digits=[f'PD{i}' for i in range(8)],
                           segment_active_low=False, digit_active_low=True)
assert frame['passed']
print(frame['text'], frame['decimal_points'], frame['simulation_seconds'])
```

`prepare_control_batches(project, destination, *, controls=None, batch_size=5)` returns file-preparation evidence only (`scope='file_preparation_only'`), per-group paths/bindings/firmware and source preservation. It clears INC/DEC/KEY in independent copies before assigning each group, preserving actual STATE. Start from correctly released inputs; unbound held controls are not silently changed.

`run_control_batches(project, destination, *, callback, controls=None, batch_size=5, initialize_seconds=.2, settle_seconds=.02, install=None, stop_on_failure=True)` runs groups in owned simulations. `callback(sim, ref)` must return a JSON-serializable mapping with explicit `passed=True`; actual native time must increase for each case. A callback is where firmware-specific text/sequence/count assertions belong. Exceptions, cancellations and false/missing passed values remain failed/partial records.

`decode_seven_segment(value, *, segment_active_low=False)` returns `character`, `decimal_point`, `raw` and `normalized_code`; it is offline decoding, not a native measurement. `read_display_frame(...)` uses 7 or 8 ordered segment probes (A…G[,DP]), ordered digit-select probes, and distinct references. Options include `sample_seconds=.002`, `max_samples=256`, `stable_frames=2`, `max_native_seconds=.5`, `timeout=30`. It uses bounded native sampling with slight deterministic timing variation to reduce fixed-period aliasing. A `DisplaySamplingError` retains its partial `.report`. KeyboardInterrupt/SystemExit are re-raised with partial `digital_report`; the helper still attempts to pause. Default sampling alternates approximately .002/.002201 native seconds to reduce fixed-period aliasing; this bounded strategy cannot guarantee recovery of every scan rate.

Successful frame records include `backend='proteus_native_sdf'`, `text`, `decimal_points`, `simulation_seconds`, `window_start_seconds`, `window_end_seconds`, `samples` and `completed_frames` arrays, `stable_frames`, `paused_after_sampling` and `atomic_instantaneous_frame=False`. Retain that window rather than presenting a reconstructed word as eight simultaneous measured levels.

Specify ordered segment and digit-select probe lists and derive polarity from the circuit/model. Common-cathode circuits often use high-active segments and low-active digit selections. DP is a separate bit, not an extra hexadecimal digit.

An accepted frame must cover all positions within bounded samples/native time and satisfy the helper's stability requirement. Reject unknown segment codes and ambiguous simultaneous digit selects. The reconstruction spans scan phases; it is not an atomic snapshot of eight simultaneous outputs. Sampling may miss transients or alias with a scan period; preserve the reported window/assumptions and use a bounded failure.

| Mistake/failure | Repair |
|---|---|
| `observe()['actual_at']` | Read `simulation_seconds`; scenario fields belong to scenario records. |
| More than five controls in one run | Prepare independent groups with other bindings unassigned in each copy. |
| BUTTON command without readback | Require native actuator STATE; dispatch alone is not input evidence. |
| Blank/incomplete digits | Verify actual time, digit polarity, segment order and distinct scan phases within a bounded window. |
| Two selected digits / unknown segment code | Check wiring, polarity, blanking/timing and probes. Do not choose one arbitrarily or map X to zero. |
| Stable word during a long hold | This alone cannot prove single response when repeated writes produce the same word. Add a count/sequence observable when required. |

## Historical 0.9.0 verification scope

0.9.0 file/offline regressions cover group copies, source/resource preservation, callbacks, strict native-time contracts and display reconstruction failure cases. Those tests do not launch Proteus. A separate native run of the independent matrix/display example passed all 16 keys in sequential groups of 5/5/5/1: 25 reconstructed display records, 670 native SDF samples and at least two agreeing complete scans per reconstruction. Each key was checked after .08 seconds of stable press plus .12 seconds further hold; the eight-character display and modulo-16 acceptance count matched the single-response expectation.

K0 also rejected a .003-second pulse and three .002-second pressed/.003-second released bounce cycles, then advanced count 1→2 after stable release/repress. All diagnostics and source-preservation checks passed; four owned processes closed gracefully without forced cleanup. Results cover this independent firmware and these finite native windows, not simultaneous 16-key input or arbitrary hold times. Earlier failed/partial/interrupted attempts remain unpassed; historical course direction/speed scenes were not rerun. Reconstructed displays remain non-atomic samples across scan phases.

## Current 0.9.1 reproduction and partial evidence

The maintained public `scripts/verify_matrix_display.py` rebuilds the firmware, generates the revised 48-part example, checks all 29 expected nets and prepares independent control groups by default. Its file-only `passed=True`, `status='prepared'`, `scope='file_contract_preparation_only'` does not certify native execution. Use [matrix-example.md](matrix-example.md) for file/native commands with different new output directories.

Explicit native mode targets the same 16 sequential keys, finite .08-second stable press plus .12-second hold, K0 short-pulse/bounce/rearm expectations and 25 reconstructed-display records. Record its actual sample count; the historical 670 samples above are not the revised layout's current result. The actual 0.9.1 CLI run passed all 16 keys in groups of 5/5/5/1, 25 reconstructed displays, 658 native SDF samples and 118 actuator readbacks. Each accepted reconstruction required at least two agreeing complete scans; display/count expectations, diagnostics and source preservation passed, with all four owned processes closed gracefully. The current samples were measured afresh, not copied from the historical 670. Its separate running capture showed initial `01234567` with before/after/pause times .372412/.422412/.472412 seconds. Final evidence is `docs/validation/v0.9.1.json`.

Startup BaseException cleanup retains the exact owned PID/closed state even when no Simulation was returned; group records mark `startup_failure` and remain unpassed. Interruption rethrows the original exception. A checkpoint I/O failure cannot turn an interruption into an ordinary failed return. Partial native evidence can prove that a process launched or initialization time advanced without proving completed key/display acceptance; `native_run_completed` remains false. Recovered checkpoints and failed cleanup/recording errors must stay explicit. The two real startup-interruption checks are cleanup evidence with no simulation execution, separate from digital success.
