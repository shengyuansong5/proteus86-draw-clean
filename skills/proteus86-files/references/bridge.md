# Shared structured API for Codex and DSH

Both platforms execute `proteus86.bridge` and `bridge_operations.Operations`.
DSH prefixes tools with `mcp__proteus86__`; Codex can use the same MCP server or
send one JSON-RPC request from a local file with `--request`. No Python source,
shell command, private method, executable or native process ID is accepted as
an operation. Capability equality is separate from current-run validation.

Call `capabilities {}` first. It returns the workspace/output/native roots,
every permitted method's exact Python signature and whether native calls are
enabled. Input paths are relative to the workspace; write destinations are
relative to the output root. Use absolute paths returned by prior calls for
subsequent reads. Files under a configured native root can be inspected too.
Links, junctions, root traversal and output writes into read-only source trees
are refused. Startup configuration chooses roots; the model cannot widen them.

`project_action {action, params}` offers generation from text or JSON specs,
full inspection/read-only Circuit queries, device search and pin metadata,
diagnose/netcheck/wiringcheck/wire_quality, SVG rendering, firmware inspection,
portable packaging, control batch preparation, pin-order checking/repair,
Protel text conversion, and the independent matrix example/preparation.
`capabilities.file_actions` lists the current action names. Parameter names
follow the public functions, with `project`, `destination` and `expected_nets`
as applicable. `generate` takes `design` text; `build` takes `spec` JSON.

`circuit_edit` accepts `source` (optional for a blank new circuit),
`destination`, `operations`, `expected_nets`, optional `title` and explicit
`overwrite`. All edits run inside one `with circuit.batch():`, then save,
reopen and check. Each operation is `{method, args: [], kwargs: {}}` and must
name a listed public Circuit method. For example:

```json
{
  "source": "output/example/circuit.pdsprj",
  "destination": "edited/circuit.pdsprj",
  "operations": [
    {"method": "update", "args": ["R1"], "kwargs": {"value": "22k"}},
    {"method": "bind_firmware", "args": ["U1", "examples/blink8051.hex"]}
  ],
  "expected_nets": [["R1.1", "U1.1"], ["R1.2", "GND"]]
}
```

Supply the actual complete expected nets for your circuit. Omitted/empty
expected nets are explicitly reported as `topology_verified=false`; they are
never a complete connectivity acceptance. Explicit overwrite retains the
core's checked backup; the base template is never overwritten. PROGRAM inputs
and firmware overrides must resolve to files in the configured input roots.
Native route/terminal-caption coordinates stay signed native integers;
`add_mm` and `move_mm` use millimetres. Use the same file-workflow reference.

`native_action {action, params}` is advertised only with startup
`--allow-native --native-root <dedicated ASCII directory>`. It cannot enable
itself. `open` takes `project`, fresh `name`, optional `firmware` mapping,
then returns a server-owned `handle`. `call` takes that handle, a listed
Simulation `method`, `args` and `kwargs`. Use `run_for`, `diagnostics` and
actual `simulation_seconds`; `start` alone is not success. `scenario` takes
the handle, structured Scenario `actions` (set/press/release/hold/bounce),
probes, until, sample_every and the existing expectation options. Python
callbacks cannot be supplied over JSON. `display` uses the public
read_display_frame options; retain its non-atomic sample window. `capture`
takes a fresh PNG `destination` and the public capture options.

`editor_open` prepares a fresh portable copy and returns an owned editor
handle; `editor_save` and `editor_export` operate only that copy. Use a new
editor for independent reopen acceptance. Close with `close` or
`editor_close`. EOF/interruption attempts to close every remaining owned
handle; failed cleanup remains failed and keeps the handle for recovery.
Unknown IDs and private methods fail. Ownership, profile, menu, status,
five-control, diagnostics, time and unlocked-desktop guards remain in the
existing native APIs.

`matrix_prepare {destination}` is a **project_action** that rebuilds/generates
and prepares 5/5/5/1 control groups without launching PDS. The separate
**native_action** `matrix_verify {destination, name, capture:false}` executes
the maintained independent 16-key native acceptance with new file and ASCII
native directories. It uses real native readback and existing assertions,
never offline emulation. `capture:true` additionally requires an unlocked
connected desktop and the checked Pillow backend. Never call native tools
during the user's game. Read digital.md/native.md before native work.

The CLI accepts `--workspace`, `--output-root`, optional `--native-root` and
`--allow-native`; paths must exist at startup. A `--request` file contains a
normal `tools/call` JSON-RPC request and uses precisely the MCP dispatcher.
For multiple stateful native calls use one persistent stdio process. A fresh
CLI process cannot reuse another process's handle.

Long native work must not depend on one MCP request staying open.
Use `matrix_submit {destination,name,capture}` or `recipe_submit
{destination,steps}`. A recipe step is `{action,params,as?}`; an `open` result
saved with `as:"sim"` is referenced by later `params.handle:"$sim"`.
Recipes allow only the non-job native operations; recursive submissions and
Python/shell callbacks are rejected. Poll with `job_wait {job,seconds:30}` or
`job_status`; `job_cancel` requests cooperative cancellation. Submitted/running
records remain `passed:false`. Success needs an exited worker, final passed
record and completed native run. The worker watches the exact owning bridge
process handle; cancellation or parent exit stops at a safe checkpoint and
closes only owned contexts. Failed graceful cleanup attempts termination only
through its retained owned Popen, and still reports failure.

The single repository ships `adapters/codex/` and `adapters/dsh/` as thin
platform entries plus separate install commands. Both share the references
above and the same core; installed entry text may differ by platform. Source
distribution must not include machine configs, locator manifests, credentials,
vendor libraries/templates, screenshots or temporary run bundles.
