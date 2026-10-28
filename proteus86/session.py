"""PID-scoped native menu/ADI API for Proteus 8.6; no mouse input."""
import hashlib
import shutil
import uuid
import io
import math
import time
from pathlib import Path
from zipfile import ZipFile, BadZipFile

from .installation import Installation
from ._codec.proteus_session import Session as NativeSession, parse_sdf


def _cleanup_owned_startup(session, error):
    """Close only a constructor's own Popen without replacing its failure.

    A Session can fail or be interrupted after PDS starts but before a caller
    receives the Session. Keep cleanup evidence on the original exception so a
    batch can report that process even when its local ``sim`` is still None.
    """
    process = getattr(session, 'process', None)
    if process is None:
        return
    evidence = dict(owned_pid=process.pid, process_closed=False)
    try:
        if process.poll() is None:
            evidence['owned_startup_cleanup'] = 'terminated'
            process.terminate()
            process.wait(timeout=5)
        else:
            evidence['owned_startup_cleanup'] = 'already_closed'
    except BaseException as cleanup_error:
        evidence['owned_cleanup_error'] = repr(cleanup_error)
    try:
        evidence['process_closed'] = process.poll() is not None
    except BaseException as cleanup_error:
        evidence['owned_cleanup_error'] = repr(cleanup_error)
    # Diagnostic attachment must not hide KeyboardInterrupt/SystemExit either.
    try:
        for name, value in evidence.items():
            setattr(error, name, value)
    except BaseException:
        pass


def _archive_digest(path):
    """Validate a complete container snapshot, including the central directory/CRCs."""
    data=Path(path).read_bytes()
    with ZipFile(io.BytesIO(data)) as archive:
        infos=archive.infolist()
        if len({i.filename for i in infos})!=len(infos):raise BadZipFile('Duplicate native ZIP member')
        if any(i.file_size>64*1024*1024 for i in infos) or sum(i.file_size for i in infos)>128*1024*1024:
            raise ValueError('Native project archive exceeds the verified size limits')
        if not {'ROOT.DSN','ROOT.CDB','PROJECT.XML'}<=set(archive.namelist()):raise BadZipFile('Incomplete native project archive')
        if archive.testzip() is not None:raise BadZipFile('Native project ZIP CRC mismatch')
    return hashlib.sha256(data).digest()


class Session(NativeSession):
    def __init__(self, project, executable=None, *, install=None):
        executable = Path(executable) if executable is not None else Installation.discover(install).executable
        self.last_backup = None
        try:
            super().__init__(project, executable=executable)
        except BaseException as error:
            _cleanup_owned_startup(self, error)
            raise

    def menu(self, path, *, timeout=15):
        """Wait only for a uniquely identified disabled command, then recheck.

        Native editor menus can settle after the main window becomes ready.
        Missing/ambiguous paths and changed ownership/window profiles are errors,
        not startup conditions to retry. Command IDs are never cached.
        """
        import ctypes
        from ._codec import proteus_native as native
        from .native_simulation import owned

        if not isinstance(path, str) or not path.strip():
            raise ValueError('Menu path must be a non-empty exact native path')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise ValueError('Menu timeout must be between 0 and 300 seconds')
        process, pid = self.process, self.pid
        deadline = time.monotonic() + timeout
        identity = None

        def snapshot():
            nonlocal identity
            if self.process is not process or self.pid != pid or process.pid != pid:
                raise RuntimeError(f'Owned Proteus process identity changed while waiting for menu: {path}')
            code = process.poll()
            if code is not None:
                raise RuntimeError(f'Proteus PID {pid} exited while waiting for menu {path}: {code}')
            window = self._ready()
            if not window:
                raise RuntimeError(f'Owned Proteus main window is unavailable while waiting for menu: {path}')
            current = (window['hwnd'], window['cls'])
            if current[1] != 'LX_APPLN_DClkNoDC':
                raise RuntimeError(f'Unrecognized Proteus main window profile while waiting for menu: {path}')
            if identity is not None and current != identity:
                raise RuntimeError(f'Owned Proteus main window changed while waiting for menu: {path}')
            owned(pid, current[0])
            handle = native.u.GetMenu(current[0])
            if not handle:
                raise RuntimeError(f'Owned Proteus main menu disappeared while waiting for: {path}')
            found = [item for item in native.menus(handle) if item['path'] == path]
            if len(found) != 1:
                reason = 'Missing' if not found else 'Ambiguous'
                raise ValueError(f'{reason} native menu path: {path}')
            identity = current
            return window, found[0]

        while True:
            window, item = snapshot()
            if item['enabled']:
                # Re-read the live menu immediately before dispatch: it may have
                # been rebuilt, disabled again, or assigned a new command ID.
                window, item = snapshot()
                if item['enabled']:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f'Proteus PID {pid}: menu did not become ready within {timeout:g}s: {path}')
                    if self.process is not process or self.pid != pid or process.pid != pid or process.poll() is not None:
                        raise RuntimeError(f'Owned Proteus process changed or exited before menu dispatch: {path}')
                    owned(pid, window['hwnd'])
                    if not native.u.PostMessageW(window['hwnd'], 0x111, item['command_id'], 0):
                        raise ctypes.WinError(ctypes.get_last_error())
                    return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f'Proteus PID {pid}: menu stayed disabled for {timeout:g}s: {path}')
            time.sleep(min(.1, remaining))

    def save(self):
        _archive_digest(self.project)
        backup = self.project.with_name(self.project.name + '.backup-native-' + uuid.uuid4().hex[:12])
        with self.project.open('rb') as source, backup.open('xb') as target:
            shutil.copyfileobj(source, target)
        if hashlib.sha256(backup.read_bytes()).digest() != hashlib.sha256(self.project.read_bytes()).digest():
            raise IOError('Native-save backup verification failed')
        self.last_backup = backup
        result=super().save()
        self._wait_saved_archive()
        return result

    def _wait_saved_archive(self):
        previous=None
        def complete():
            nonlocal previous
            try:
                digest=_archive_digest(self.project)
                stat=self.project.stat()
                current=(digest,stat.st_size,stat.st_mtime_ns)
            except (OSError,BadZipFile,EOFError):
                previous=None
                return False
            stable=current==previous
            previous=current
            return stable and self._ready()
        # Proteus can expose its ready menu and modified timestamp before ZIP close.
        # Two complete matching snapshots prevent returning in that write window.
        return self._wait(complete,timeout=15)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        # Close never chooses Discard on an unexpected unsaved-changes dialog.
        self.close()
        return False


__all__ = ['Session', 'parse_sdf']
