"""Portable, content-addressed project resources; no native process is used."""
import hashlib
import os
from pathlib import Path
import tempfile


def sha256(path):
    with Path(path).open('rb') as stream:
        if hasattr(hashlib,'file_digest'):return hashlib.file_digest(stream,'sha256').hexdigest()
        digest=hashlib.sha256()
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
        return digest.hexdigest()


def copy_verified(info, target):
    """Publish an immutable file only after source and copy match the manifest."""
    source = Path(info['path']).resolve(strict=True)
    target = Path(target).resolve()
    expected = info['sha256']
    if sha256(source) != expected:
        raise RuntimeError(f'Resource changed since binding: {source}; bind it again before saving')
    if target.exists():
        if not target.is_file() or sha256(target) != expected:
            raise RuntimeError(f'Resource collision: {target}; preserve it and use a new output directory')
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.p86-resource-', dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as out, source.open('rb') as incoming:
            for block in iter(lambda: incoming.read(1024 * 1024), b''):
                out.write(block)
        if sha256(temporary) != expected or sha256(source) != expected:
            raise RuntimeError(f'Resource changed during copying: {source}; retry with a stable input')
        try:
            # A hard link publishes without replacing a concurrent writer, also on POSIX.
            os.link(temporary, target)
        except FileExistsError:
            if sha256(target) != expected:
                raise RuntimeError(f'Resource collision: {target}')
        return target
    finally:
        temporary.unlink(missing_ok=True)


def relative_firmware(ref, info):
    return Path('resources/firmware') / (ref + '-' + info['sha256'] + '.' + info['format'])


def package_project(project, destination, *, firmware=None):
    """Strict, new-directory project package; also used by simulation preparation."""
    from .firmware import prepare_run
    return prepare_run(project, destination, firmware=firmware)
