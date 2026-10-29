## Windows portable runtime

This installation uses the Windows portable bundle. Read this installed skill's
`.proteus86-install.json` to find `checkout_root` (the bundle's `app/` folder).
Use its sibling `runtime/python.exe` for every Python command, including examples,
firmware builders, direct API work and `-m proteus86.bridge`. Do not use bare
`python`, system packages, pip, or install another interpreter. The bundled
runtime's isolated search path already includes the shared application and Pillow.

The sibling `Proteus86.cmd` and `Proteus86-MCP.cmd` are convenient CLI/MCP entries.
For DSH, load the generated bundle `config/DSH-MCP.patch.yml` in the chosen
profile/launch configuration. It starts this same bundled runtime. Native tools
still require the startup `DSH_PROTEUS_NATIVE_ROOT` opt-in and a dedicated ASCII
directory; do not relax ownership, version or path guards.

The install does not change global PATH, harness model, sandbox settings or
existing MCP configuration. After moving the bundle, rerun the platform installer
with `--update` to refresh the checkout locator and generated MCP paths.
