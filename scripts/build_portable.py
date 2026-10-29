"""Build a source-allowlisted Windows x64 bundle from checksum-pinned archives."""
import argparse
import hashlib
import json
from pathlib import Path,PurePosixPath
import re
import shutil
import stat
import zipfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def extract(archive, destination):
    with zipfile.ZipFile(archive) as source:
        if source.testzip() is not None:
            raise ValueError('Dependency ZIP CRC check failed')
        for info in source.infolist():
            name=PurePosixPath(info.filename)
            mode=info.external_attr >> 16
            if name.is_absolute() or '..' in name.parts or '\\' in info.filename or ':' in info.filename or stat.S_ISLNK(mode):
                raise ValueError('Unsafe dependency archive entry')
        source.extractall(destination)


def build(source, downloads, output, *, source_commit=None):
    source,downloads,output=map(lambda path:Path(path).resolve(),(source,downloads,output))
    if output.exists():
        raise FileExistsError('Use a new portable output directory')
    lock=json.loads((source/'portable/dependencies.json').read_text(encoding='utf-8'))
    inventory=json.loads((source/'portable/source-files.json').read_text(encoding='utf-8'))
    version=re.search(r'__version__ = "([^"]+)"',(source/'proteus86/__init__.py').read_text(encoding='utf-8'))[1]
    archives={}
    for key in ('python','pillow'):
        item=lock[key]
        path=downloads/item['filename']
        if sha(path.read_bytes())!=item['sha256']:
            raise ValueError('Dependency SHA-256 mismatch: '+key)
        archives[key]=path
    output.mkdir(parents=True)
    bundle=output/('proteus86-draw-'+version+'-windows-x64-portable')
    bundle.mkdir()
    app=bundle/'app'
    app.mkdir()
    for name in inventory:
        path=PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
            raise ValueError('Unsafe source inventory entry')
        origin=source/name
        if not origin.is_file() or origin.is_symlink() or getattr(origin.lstat(),'st_reparse_tag',0):
            raise ValueError('Non-regular source input: '+name)
        target=app/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(origin,target)
    runtime=bundle/'runtime'
    runtime.mkdir()
    extract(archives['python'],runtime)
    packages=runtime/'site-packages'
    packages.mkdir()
    extract(archives['pillow'],packages)
    path_file=next(runtime.glob('python*._pth'))
    stdlib=next(runtime.glob('python*.zip')).name
    path_file.write_text(stdlib+'\n.\n../app\nsite-packages\n',encoding='utf-8')
    for name in ('output','tmp','config'):
        (bundle/name).mkdir()
    entries={
        'Install-Codex.cmd':'"%~dp0app\\portable\\install.py" --platform codex',
        'Install-DSH.cmd':'"%~dp0app\\portable\\install.py" --platform dsh',
        'Install-Agent.cmd':'"%~dp0app\\portable\\install.py"',
        'Proteus86.cmd':'-m proteus86',
        'Proteus86-MCP.cmd':'-m proteus86.bridge',
    }
    for name,command in entries.items():
        pause='if "%~1"=="" pause\r\n' if name in ('Install-Codex.cmd','Install-DSH.cmd') else ''
        text=('@echo off\r\nsetlocal\r\n'
              'set "PYTHONDONTWRITEBYTECODE=1"\r\n'
              'if not exist "%~dp0tmp" mkdir "%~dp0tmp"\r\n'
              'set "TEMP=%~dp0tmp"\r\nset "TMP=%~dp0tmp"\r\n'
              '"%~dp0runtime\\python.exe" -B -X utf8 '+command+' %*\r\n'
              'set "_proteus_exit=%ERRORLEVEL%"\r\n'+pause+'exit /b %_proteus_exit%\r\n')
        (bundle/name).write_bytes(text.encode('ascii'))
    shutil.copyfile(app/'LICENSE',bundle/'LICENSE')
    agent_entry=dict(format=1,platform='windows-x64',system_python_required=False,
                     command='Install-Agent.cmd',platforms=['codex','dsh'],
                     required_arguments=['--platform','codex|dsh'],
                     options=['--home','--json','--dry-run','--update'],
                     recommended_arguments=['--platform','codex','--json'],
                     direct_entry=['runtime/python.exe','-B','-X','utf8','app/portable/install.py'],
                     success_exit_code=0,error_exit_code=2,result_format='JSON with --json',
                     next_actions_field='next_actions',existing_profiles_modified=False)
    (bundle/'INSTALL.json').write_text(json.dumps(agent_entry,indent=2)+'\n',encoding='utf-8')
    (bundle/'THIRD-PARTY-NOTICES.txt').write_text(
        'Application: MIT; see app/LICENSE and app/THIRD_PARTY.md.\n'
        'Python: unmodified official Windows embeddable binaries and standard library;\n'
        'only the isolated search-path configuration is changed. See runtime/LICENSE.txt.\n'
        'Pillow and bundled image libraries: original licenses retained under\n'
        'runtime/site-packages/*.dist-info/licenses/ (or its LICENSE files).\n'
        'Proteus software, libraries, models, samples, templates and license keys are NOT included.\n'
        'See app/docs/publication.md for the unresolved vendor EULA/interoperability risk.\n',encoding='utf-8')
    (bundle/'START-HERE.txt').write_text(
        'Proteus 8.6 / Codex + DeepSeek Harness - Windows x64 portable\n\n'
        'No Python installation or pip is needed. Keep this extracted folder.\n'
        '1. Double-click Install-Codex.cmd OR Install-DSH.cmd for your platform.\n'
        '2. DSH: load config/DSH-MCP.patch.yml in your DSH launch/profile configuration.\n'
        '3. Supply your own compatible licensed Proteus installation and template.\n'
        '   See app/docs/portable.md for the short setup guide.\n\n'
        'Command entries: Proteus86.cmd and Proteus86-MCP.cmd.\n'
        'Custom harness home: Install-Codex.cmd --home "path" (or Install-DSH.cmd).\n'
        'Agent entry: Install-Agent.cmd --platform codex|dsh --home "path" --json\n'
        'Preview: add --dry-run; updates: add --update. No prompts in the agent entry.\n'
        'Existing skill / moved bundle: reinstall with --update; checked backups are retained.\n'
        'Installation never changes global PATH, model, permissions or existing MCP profiles.\n'
        'The bundle contains only the runtime and tool; it is not the Proteus application.\n',encoding='utf-8')
    files=[]
    for path in sorted(bundle.rglob('*')):
        if path.is_file():
            files.append(dict(path=path.relative_to(bundle).as_posix(),bytes=path.stat().st_size,sha256=sha(path.read_bytes())))
    manifest=dict(version=version,platform='windows-x64',source_commit=source_commit,
                  dependencies=lock,system_python_required=False,global_packages_used=False,
                  source_files=len(inventory),files=files)
    (bundle/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    archive=output/(bundle.name+'.zip')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as zipped:
        for path in sorted(bundle.rglob('*')):
            zipped.write(path,bundle.name+'/'+path.relative_to(bundle).as_posix())
    with zipfile.ZipFile(archive) as zipped:
        if zipped.testzip() is not None:
            raise RuntimeError('Portable archive CRC check failed')
    return dict(bundle=str(bundle),archive=str(archive),bytes=archive.stat().st_size,sha256=sha(archive.read_bytes()),
                source_files=len(inventory),bundled_files=len(files)+1,version=version)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--downloads',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--source-commit')
    args=parser.parse_args()
    print(json.dumps(build(args.source,args.downloads,args.output_dir,source_commit=args.source_commit)))


if __name__=='__main__':
    main()
