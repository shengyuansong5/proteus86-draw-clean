# DeepSeek Harness entry

Install: `python scripts/install_dsh_skill.py --update` (optional `--home`).
This uses the same verified installer and canonical resources as Codex, adding
only this directory's `skill.md`. The compatibility installer flag
`scripts/install_codex_skill.py --platform dsh` remains supported.

Project configuration is `docs/proteus86-mcp.patch.yml`; optional headless
official Flash/low selection is `docs/dsh-headless.patch.yml`. See
`docs/dsh-integration.md` for roots, Web/headless sessions and native opt-in.
DSH registers the same dispatcher through `scripts/dsh_mcp.py`; long calls
use matrix_submit/recipe_submit and bounded job_wait. The bridge does not
disable or claim to repair DSH's Windows shell sandbox.
