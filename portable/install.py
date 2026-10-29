"""Thin portable skill/config entry over the canonical shared installer."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import sys

from scripts.install_codex_skill import install_platform_skill


def write_config(bundle):
    bundle = Path(bundle).resolve()
    directory = bundle / 'config'
    if directory.exists() and (directory.is_symlink() or getattr(directory.lstat(), 'st_reparse_tag', 0)):
        raise ValueError('Portable config must not be a reparse point')
    directory.mkdir(exist_ok=True)
    for name in ('output', 'tmp'):
        folder = bundle / name
        if folder.exists() and (folder.is_symlink() or getattr(folder.lstat(), 'st_reparse_tag', 0)):
            raise ValueError('Portable data must not be a reparse point')
        folder.mkdir(exist_ok=True)
    python = str(bundle / 'runtime/python.exe')
    script = str(bundle / 'app/portable/mcp.py')
    args = ('[' + ', '.join(json.dumps(value) for value in ('-B', '-X', 'utf8', script, '--workspace')) +
            ', process.cwd(), ' + json.dumps('--output-root') + ", process.cwd() + '/output/proteus86'" +
            ", ...(process.env.DSH_PROTEUS_NATIVE_ROOT ? ['--native-root', process.env.DSH_PROTEUS_NATIVE_ROOT, '--allow-native'] : [])]")
    env = ("Object.fromEntries(Object.entries({PYTHONDONTWRITEBYTECODE:'1', PYTHONUTF8:'1', "
           "PROTEUS86_HOME:process.env.PROTEUS86_HOME, PROTEUS86_TEMPLATE:process.env.PROTEUS86_TEMPLATE, "
           "TEMP:process.env.DSH_PROTEUS_NATIVE_ROOT ? process.env.DSH_PROTEUS_NATIVE_ROOT : " +
           json.dumps(str(bundle / 'tmp')) + ', TMP:process.env.DSH_PROTEUS_NATIVE_ROOT ? process.env.DSH_PROTEUS_NATIVE_ROOT : ' +
           json.dumps(str(bundle / 'tmp')) + "}).filter(([,value])=>value!==undefined))")
    text = ('# Generated for this portable location; existing profiles are unchanged.\n'
            '- insert:\n    - id: mcp-proteus86\n      name: "@deepseek-ai/dsh-mcp-client"\n'
            '      config:\n        serverName: proteus86\n        transport: stdio\n'
            '        command: ' + json.dumps(python) + '\n'
            '        args: !!js ' + json.dumps(args) + '\n'
            '        cwd: !!js process.cwd()\n'
            '        env: !!js ' + json.dumps(env) + '\n'
            '        toolCallTimeoutMs: 300000\n        failOnStartupError: true\n')
    destination = directory / 'DSH-MCP.patch.yml'
    if destination.exists() and (destination.is_symlink() or getattr(destination.lstat(), 'st_reparse_tag', 0)):
        raise ValueError('Portable patch must not be a reparse point')
    if destination.exists() and destination.read_text(encoding='utf-8') != text:
        backup = directory / ('DSH-MCP.' + __import__('uuid').uuid4().hex + '.backup.yml')
        backup.write_bytes(destination.read_bytes())
        if backup.read_bytes() != destination.read_bytes():
            raise RuntimeError('Portable config backup failed')
    descriptor, name = tempfile.mkstemp(prefix='.dsh-', suffix='.tmp', dir=directory)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    class AgentParser(argparse.ArgumentParser):
        def error(self, message):
            if '--json' in argv:
                print(json.dumps(dict(passed=False, error=dict(type='ArgumentError', message=message))))
                raise SystemExit(2)
            super().error(message)
    parser = AgentParser(description=__doc__)
    parser.add_argument('--platform', required=True, choices=('codex', 'dsh'))
    parser.add_argument('--home', type=Path)
    parser.add_argument('--update', action='store_true')
    parser.add_argument('--json', action='store_true', help='One JSON result, no interactive input')
    parser.add_argument('--dry-run', action='store_true', help='Report planned paths without writing files')
    args = parser.parse_args(argv)
    app = Path(__file__).resolve().parents[1]
    bundle = app.parent
    if Path(sys.executable).resolve() != (bundle / 'runtime/python.exe').resolve():
        raise RuntimeError('Use the portable Install-Codex.cmd or Install-DSH.cmd entry')
    variable, fallback = ('CODEX_HOME', '.codex') if args.platform == 'codex' else ('DSH_HOME', '.dsh')
    home = (args.home or Path(os.environ.get(variable) or Path.home() / fallback)).resolve()
    result = dict(passed=True, platform=args.platform, dry_run=args.dry_run, home=str(home),
                  skill=str(home / 'skills/proteus86-files'), checkout_root=str(app),
                  python=str(bundle / 'runtime/python.exe'), mcp_patch=str(bundle / 'config/DSH-MCP.patch.yml'),
                  system_python_required=False, model_changed=False, permissions_changed=False,
                  existing_profiles_changed=False, mcp_registered=False,
                  next_actions=([dict(action='load_dsh_mcp_patch', path=str(bundle / 'config/DSH-MCP.patch.yml'))]
                                if args.platform == 'dsh' else []) + [dict(action='refresh_harness_session')])
    if args.dry_run:
        if args.json:
            print(json.dumps(result))
        else:
            print('Dry run: install ' + args.platform + ' skill at ' + result['skill'])
        return 0
    folder = bundle / 'tmp'
    if folder.exists() and (folder.is_symlink() or getattr(folder.lstat(), 'st_reparse_tag', 0)):
        raise ValueError('Portable temporary directory must not be a reparse point')
    folder.mkdir(exist_ok=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(folder)
    tempfile.tempdir = str(folder)
    installed = install_platform_skill(app, home, args.platform, update=args.update, portable=True)
    write_config(bundle)
    result['installation'] = installed
    if args.json:
        print(json.dumps(result))
        return 0
    print('Installed ' + args.platform + ' skill using the bundled runtime.')
    print('Keep this bundle folder. After moving it, reinstall with --update.')
    if args.platform == 'dsh':
        print('Load this MCP patch in DSH: ' + result['mcp_patch'])
    if installed.get('backup'):
        print('Verified previous-skill backup: ' + str(installed['backup']))
    return 0


if __name__ == '__main__':
    try:
        code = main()
    except Exception as error:
        if '--json' in sys.argv:
            print(json.dumps(dict(passed=False, error=dict(type=type(error).__name__, message=str(error)))))
        else:
            print(type(error).__name__ + ': ' + str(error), file=sys.stderr)
        code = 2
    raise SystemExit(code)
