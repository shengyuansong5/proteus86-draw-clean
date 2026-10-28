"""Install the shared Codex/DSH skill; explicit updates retain a verified backup."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import tempfile
import time

SKILL = 'proteus86-files'
MANIFEST = '.proteus86-install.json'


def _digest(path):
    with path.open('rb') as stream:
        value = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def _snapshot(directory):
    """Hash regular files only; reject links/reparse points before copying."""
    if not directory.exists():
        return {}
    if not directory.is_dir():
        raise ValueError('Skill location is not a directory: ' + str(directory))
    result = {}
    for path in [directory, *sorted(directory.rglob('*'))]:
        before = path.lstat()
        if path.is_symlink() or getattr(before, 'st_reparse_tag', 0):
            raise ValueError('Skill links/reparse points require separate review: ' + str(path))
        if path.is_file():
            digest = _digest(path)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise RuntimeError('Skill file changed while being read: ' + str(path))
            result[path.relative_to(directory).as_posix()] = digest
        elif not path.is_dir():
            raise ValueError('Skill resource is not a regular file/directory: ' + str(path))
    return result


def _relative(name):
    if not isinstance(name, str) or not name or '\\' in name:
        raise ValueError('Invalid managed skill path')
    path = PurePosixPath(name)
    if path.is_absolute() or PureWindowsPath(name).drive or '..' in path.parts or '.' == name:
        raise ValueError('Managed skill path escaped its directory: ' + name)
    return path


def _old_manifest(destination):
    path = destination / MANIFEST
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('format') != 1 or not isinstance(data.get('files'), dict):
        raise ValueError('Unrecognized installed skill manifest; preserve it for review')
    for name, digest in data['files'].items():
        _relative(name)
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Invalid installed skill digest: ' + name)
    return data


def _copy_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _copy_tree(source, destination, snapshot):
    destination.mkdir()
    for path in source.rglob('*'):
        if path.is_dir():
            (destination / path.relative_to(source)).mkdir(parents=True, exist_ok=True)
    for name in snapshot:
        _copy_file(source / name, destination / name)
    if _snapshot(destination) != snapshot:
        raise RuntimeError('Skill tree copy verification failed: ' + str(destination))


def _publish(staged, destination):
    # Destination must be absent: do not merge a partly installed resource tree.
    if destination.exists():
        raise FileExistsError('Skill destination appeared during publication: ' + str(destination))
    os.rename(staged, destination)


def _is_publication(destination, transaction):
    try:
        data = json.loads((destination / MANIFEST).read_text(encoding='utf-8'))
        return isinstance(data, dict) and data.get('transaction') == transaction
    except (OSError, ValueError):
        return False


def _remove_staging(directory, staging_parent):
    resolved = directory.resolve()
    parent = staging_parent.resolve()
    if resolved.parent != parent or not resolved.name.startswith(SKILL + '-'):
        raise RuntimeError('Refusing cleanup outside the owned skill staging directory')
    if directory.is_symlink():
        raise RuntimeError('Refusing cleanup of a replaced staging link')
    shutil.rmtree(directory)


def _tree_digest(files):
    payload = json.dumps(files, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def install_skill(source, codex_directory, *, update=False, checkout_root=None):
    """Copy instructions/resources as one verified tree, preserving local extras.

    Backups live outside skills/ so they cannot become duplicate discovered
    skills. Python failures restore the prior live directory when publication
    has begun; external destination replacement is retained for manual review.
    """
    source = Path(source).resolve(strict=True)
    codex_directory = Path(codex_directory).resolve()
    checkout_root = Path(checkout_root).resolve() if checkout_root is not None else source.parent.parent
    destination = codex_directory / 'skills' / SKILL
    if not destination.resolve().is_relative_to(codex_directory):
        raise ValueError('Installed skill resolves outside the selected Codex directory')
    if source == destination.resolve() or source.is_relative_to(destination.resolve()) or destination.resolve().is_relative_to(source):
        raise ValueError('Source and installed skill directories must not overlap')
    incoming = _snapshot(source)
    if 'SKILL.md' not in incoming or MANIFEST in incoming:
        raise ValueError('Source needs SKILL.md and must not include an installation manifest')
    previous = _snapshot(destination)
    old = _old_manifest(destination)
    metadata = dict(format=1, files=incoming, checkout_root=str(checkout_root))
    if old and old.get('files') == incoming and old.get('checkout_root') == str(checkout_root) and all(previous.get(name) == digest for name, digest in incoming.items()):
        if _snapshot(source) != incoming or _snapshot(destination) != previous:
            raise RuntimeError('Skill source/destination changed during inspection')
        return dict(status='already_installed', path=str(destination / 'SKILL.md'),
                    directory=str(destination), backup=None, files=len(incoming),
                    sha256=incoming['SKILL.md'], tree_sha256=_tree_digest(incoming))
    existed = destination.exists()
    if existed and not update:
        raise FileExistsError('Existing skill differs; review and use --update: ' + str(destination))
    staging_parent = codex_directory / '.skill-staging'
    if staging_parent.exists() and (staging_parent.is_symlink() or getattr(staging_parent.lstat(), 'st_reparse_tag', 0)):
        raise ValueError('Skill staging directory must not be a link/reparse point')
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging_parent = staging_parent.resolve()
    transaction = Path(tempfile.mkdtemp(prefix=SKILL + '-', dir=staging_parent))
    metadata['transaction'] = transaction.name
    staged, retired = transaction / 'new', transaction / 'previous'
    backup = None
    published = False
    preserve_staging = False
    outcome = None
    failure = None
    try:
        if existed:
            _copy_tree(destination, staged, previous)
            # Remove obsolete, unmodified files managed by a prior installer.
            # Unknown extras and user-modified obsolete files stay intact.
            for name, digest in (old or {}).get('files', {}).items():
                if name not in incoming and previous.get(name) == digest:
                    (staged / name).unlink()
        else:
            staged.mkdir()
        for path in source.rglob('*'):
            if path.is_dir():
                (staged / path.relative_to(source)).mkdir(parents=True, exist_ok=True)
        for name, digest in incoming.items():
            _copy_file(source / name, staged / name)
            if _digest(staged / name) != digest:
                raise RuntimeError('Skill source changed while copying: ' + name)
        manifest_path = staged / MANIFEST
        manifest_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        ready = _snapshot(staged)
        if any(ready.get(name) != digest for name, digest in incoming.items()):
            raise RuntimeError('Staged skill verification failed')
        if _snapshot(source) != incoming or _snapshot(destination) != previous:
            raise RuntimeError('Skill source/destination changed before publication')
        if existed:
            backup_stage = transaction / 'backup'
            _copy_tree(destination, backup_stage, previous)
            if _snapshot(destination) != previous:
                raise RuntimeError('Installed skill changed during backup')
            backups = codex_directory / 'skill-backups' / SKILL
            if not backups.resolve().is_relative_to(codex_directory):
                raise ValueError('Backup path resolves outside the selected Codex directory')
            backups.mkdir(parents=True, exist_ok=True)
            backup = backups / (str(time.time_ns()) + '-' + transaction.name.rsplit('-', 1)[-1])
            os.rename(backup_stage, backup)
            if _snapshot(backup) != previous:
                raise RuntimeError('Complete skill backup verification failed')
        if _snapshot(source) != incoming or _snapshot(destination) != previous:
            raise RuntimeError('Skill source/destination changed after backup')
        destination.parent.mkdir(parents=True, exist_ok=True)
        if existed:
            os.rename(destination, retired)
        _publish(staged, destination)
        published = True
        if _snapshot(destination) != ready or _snapshot(source) != incoming:
            raise RuntimeError('Published skill/source verification failed')
        outcome = dict(status='updated' if existed else 'installed', path=str(destination / 'SKILL.md'),
                       directory=str(destination), backup=str(backup) if backup else None,
                       files=len(incoming), sha256=incoming['SKILL.md'], tree_sha256=_tree_digest(incoming))
        return outcome
    except BaseException as error:
        failure = error
        if destination.exists() and (published or _is_publication(destination, transaction.name)):
            # Preserve the newly published tree rather than deleting data during
            # rollback. Its exact original copy remains in the verified backup.
            preserve_staging = True
            os.rename(destination, transaction / 'failed-publication')
        if retired.exists() and not destination.exists():
            try:
                os.rename(retired, destination)
            except BaseException as recovery_error:
                preserve_staging = True
                raise RuntimeError('Automatic skill recovery is blocked; original retained at ' + str(retired)
                                   + '; verified backup: ' + str(backup)) from recovery_error
            if _snapshot(destination) != previous:
                preserve_staging = True
                raise RuntimeError('Skill recovery verification failed; retain backup/staging: ' + str(transaction))
        elif retired.exists():
            preserve_staging = True
            raise RuntimeError('Concurrent skill destination prevents automatic recovery; original retained: ' + str(retired))
        raise
    finally:
        # Complete verified backups remain outside the auto-discovery directory.
        # Staging is private, unique and path-checked before recursive cleanup.
        if transaction.exists() and not preserve_staging:
            try:
                _remove_staging(transaction, staging_parent)
            except (OSError, RuntimeError) as error:
                # Cleanup locks do not undo a complete verified publication or
                # replace the original exception after successful rollback.
                if outcome is not None:
                    outcome.update(cleanup_warning=str(error), staging_retained=str(transaction))
                elif failure is not None:
                    failure.skill_staging_retained = str(transaction)
                    failure.skill_cleanup_error = str(error)
                else:
                    raise


def install_platform_skill(root, directory, platform, *, update=False):
    """Assemble one small platform entry over the same canonical resources."""
    if platform not in ('codex', 'dsh'):
        raise ValueError('Supported platform entries are codex and dsh')
    root, directory = Path(root).resolve(), Path(directory).resolve()
    source = root / 'skills' / SKILL
    incoming = _snapshot(source)
    overlay = root / 'adapters' / platform / 'skill.md'
    text = overlay.read_text(encoding='utf-8-sig')
    parent = directory / '.skill-source-builds'
    if parent.exists() and (parent.is_symlink() or getattr(parent.lstat(), 'st_reparse_tag', 0)):
        raise ValueError('Adapter source staging must not be a reparse point')
    parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=SKILL + '-' + platform + '-', dir=parent))
    failure, result = None, None
    try:
        for name in incoming:
            _copy_file(source / name, staged / name)
        original = (staged / 'SKILL.md').read_text(encoding='utf-8-sig')
        (staged / 'SKILL.md').write_text(original.rstrip() + '\n\n' + text, encoding='utf-8')
        if _snapshot(source) != incoming or overlay.read_text(encoding='utf-8-sig') != text:
            raise RuntimeError('Canonical skill or platform entry changed during assembly')
        result = install_skill(staged, directory, update=update, checkout_root=root)
        result['platform'] = platform
        return result
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            _remove_staging(staged, parent)
        except (OSError, RuntimeError) as cleanup_error:
            if failure is not None:
                failure.skill_staging_retained = str(staged)
                failure.skill_cleanup_error = str(cleanup_error)
            elif result is not None:
                result.update(cleanup_warning=str(cleanup_error), staging_retained=str(staged))
            else:
                raise


def main(default_platform='codex'):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform', choices=('codex', 'dsh'), default=default_platform)
    parser.add_argument('--home', type=Path, help='Explicit harness home; default is CODEX_HOME or DSH_HOME')
    parser.add_argument('--update', action='store_true', help='Back up and replace a different installed skill')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    variable, fallback = ('DSH_HOME', '.dsh') if args.platform == 'dsh' else ('CODEX_HOME', '.codex')
    codex_directory = args.home or Path(os.environ.get(variable) or Path.home() / fallback)
    result = install_platform_skill(root, codex_directory, args.platform, update=args.update)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
