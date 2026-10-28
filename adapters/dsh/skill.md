## DeepSeek Harness adapter

Load this skill through DSH's skill tool. Use the registered
`mcp__proteus86__capabilities`, `project_action`, `circuit_edit`, `native_action`
tools; the same shared dispatcher backs the Codex entry. DSH may not discover
the checkout's `skills/` unless the project overlay or this installed skill is
present. Read the manifest only for the checkout locator, never for publication.
Use matrix_submit/recipe_submit plus bounded job_wait for long native tasks.
Submission is not success. Follow DSH's own approval channel; a broken local
shell sandbox is not permission to disable confinement or silently widen roots.

The core functions and validation rules above are shared with Codex. This
entry owns only DSH skill/tool registration, permission interaction and long
task handling. This project targets these two platforms, not every harness.
