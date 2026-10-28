# Codex entry

Install: `python scripts/install_codex_skill.py --update` (optional `--home`).
This builds the installed skill from the shared `skills/proteus86-files/`
resources plus this directory's short `skill.md` entry. No core is copied here.

Use the existing terminal to call the original `python -m proteus86` CLI/API,
or the shared MCP/JSON-RPC dispatcher:

```text
python -m proteus86.bridge --workspace <project> --output-root <project-output> --request <request.json>
```

Native work additionally selects an existing dedicated ASCII `--native-root`
and `--allow-native`; use one persistent stdio process for stateful handles.
The same server can be registered as MCP by the client. Long tasks use
structured submission/status/wait/cancel. Codex permissions are handled by
Codex, not by platform branches in Proteus core functions.
