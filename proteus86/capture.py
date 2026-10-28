"""Owned-window capture with native-clock evidence; never a display-value test."""
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time


def _require_window_capture():
    """Load the optional HWND backend without calling it or guessing versions."""
    hint = ('Owned-window capture requires Pillow>=11.2.1 with an explicit '
            'ImageGrab.grab(window=...) parameter. Install into this Python '
            'environment with: python -m pip install --upgrade "Pillow>=11.2.1" '
            '(or python -m pip install -e ".[capture]" from the checkout).')
    try:
        import PIL
        from PIL import ImageGrab
    except ImportError as error:
        raise RuntimeError('Pillow/ImageGrab is unavailable. ' + hint) from error
    try:
        window = inspect.signature(ImageGrab.grab).parameters.get('window')
    except (AttributeError, TypeError, ValueError) as error:
        raise RuntimeError('Cannot verify the Pillow window-capture interface. ' + hint) from error
    if window is None or window.kind not in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                             inspect.Parameter.KEYWORD_ONLY):
        raise RuntimeError('This Pillow ImageGrab interface lacks window-keyword support. ' + hint)
    return ImageGrab


def _desktop_state(pid):
    """Read only the target session's lock/connect flags, never user details."""
    if sys.platform != 'win32':
        return dict(known=False)
    import ctypes
    from ctypes import wintypes

    class Level1(ctypes.Structure):
        _fields_ = [('SessionId', wintypes.ULONG), ('SessionState', ctypes.c_int),
                    ('SessionFlags', wintypes.LONG), ('WinStationName', wintypes.WCHAR * 33),
                    ('UserName', wintypes.WCHAR * 21), ('DomainName', wintypes.WCHAR * 18),
                    ('Times', ctypes.c_longlong * 5), ('Counters', wintypes.DWORD * 6)]

    class Info(ctypes.Structure):
        _fields_ = [('Level', wintypes.DWORD), ('Data', Level1)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    wts = ctypes.WinDLL('wtsapi32', use_last_error=True)
    kernel.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    wts.WTSQuerySessionInformationW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_int,
                                                ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
    wts.WTSFreeMemory.argtypes = [ctypes.c_void_p]
    session_id, size, data = wintypes.DWORD(), wintypes.DWORD(), ctypes.c_void_p()
    if not kernel.ProcessIdToSessionId(pid, ctypes.byref(session_id)):
        return dict(known=False)
    if not wts.WTSQuerySessionInformationW(None, session_id.value, 25, ctypes.byref(data), ctypes.byref(size)):
        return dict(known=False)
    try:
        if not data.value or size.value < ctypes.sizeof(Info):
            return dict(known=False)
        info = ctypes.cast(data, ctypes.POINTER(Info)).contents
        if info.Level != 1 or info.Data.SessionId != session_id.value:
            return dict(known=False)
        flags = info.Data.SessionFlags
        # Microsoft documents reversed LOCK/UNLOCK flags on Windows 7 / 2008 R2.
        if sys.getwindowsversion()[:2] == (6, 1) and flags in (0, 1):
            flags = 1 - flags
        return dict(known=True, session_id=session_id.value,
                    connection_state=info.Data.SessionState,
                    locked=flags == 0 if flags in (0, 1) else None)
    finally:
        wts.WTSFreeMemory(data)


def _prepare_window(session, *, fit, width, height, foreground):
    ImageGrab = _require_window_capture()
    import ctypes
    from ctypes import wintypes
    from ._codec import proteus_native as native
    from .native_simulation import owned
    if session.process.poll() is not None:
        raise RuntimeError('Owned Proteus process exited before capture')
    window = session._wait(session._ready)
    hwnd = window['hwnd']
    owned(session.pid, hwnd)
    width = min(width, native.u.GetSystemMetrics(0) - 50)
    height = min(height, native.u.GetSystemMetrics(1) - 100)
    if width < 256 or height < 256:
        raise RuntimeError('The current display is too small for native capture')
    # A hidden/maximized 8.6 OwnDC canvas can remain white until restored and
    # initialized. Warm up its capture surface before the final fit operation.
    native.u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    native.u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    native.u.BringWindowToTop.argtypes = [wintypes.HWND]
    native.u.SetForegroundWindow.argtypes = [wintypes.HWND]
    native.u.ShowWindow(hwnd, 9)
    native.u.SetWindowPos(hwnd, 0, 20, 20, width, height, 0x14)
    time.sleep(.2)
    ImageGrab.grab(window=hwnd)
    if fit:
        session.menu('View/Zoom To View Entire Sheet')
    if foreground:
        owned(session.pid, hwnd)
        native.u.BringWindowToTop(hwnd)
        native.u.SetForegroundWindow(hwnd)
    time.sleep(.2)
    return hwnd


def _check_canvas_image(image, box):
    canvas = image.crop(box).convert('RGB')
    if canvas.width >= 40 and canvas.height >= 40:
        # Ignore the widget border: it must not certify an otherwise white/black
        # OwnDC surface, nor may the separate overview/minimap certify it.
        canvas = canvas.crop((4, 4, canvas.width - 4, canvas.height - 4))
    if canvas.width < 32 or canvas.height < 32 or all(low == high for low, high in canvas.getextrema()):
        raise RuntimeError('Native schematic canvas is blank; unlock the Windows desktop, restore the owned Proteus window and retry capture. Toolbars, borders and the overview are not circuit-image evidence')


def _canvas_box(session, hwnd, image):
    import ctypes
    from ctypes import wintypes
    from ._codec import proteus_native as native
    from .native_simulation import owned
    rows = [row for row in session._ready()['children']
            if row['cls'] == 'LX_APPLN_OwnDC' and row['control_id'] == 5]
    if len(rows) != 1:
        raise RuntimeError('Unrecognized native schematic canvas; capture is not certified')
    owned(session.pid, hwnd)
    owned(session.pid, rows[0]['hwnd'])
    outer, canvas, origin = wintypes.RECT(), wintypes.RECT(), wintypes.POINT(0, 0)
    native.u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    native.u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    native.u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    if (not native.u.GetClientRect(hwnd, ctypes.byref(outer)) or
            not native.u.ClientToScreen(hwnd, ctypes.byref(origin)) or
            not native.u.GetWindowRect(rows[0]['hwnd'], ctypes.byref(canvas))):
        raise RuntimeError('Could not read the owned native canvas bounds')
    width, height = outer.right - outer.left, outer.bottom - outer.top
    if width <= 0 or height <= 0:
        raise RuntimeError('Invalid owned window bounds')
    # Pillow's HWND backend captures the client area, not GetWindowRect's frame.
    # Scale from this thread's logical coordinates to the returned bitmap pixels.
    box = (round((canvas.left - origin.x) * image.width / width),
           round((canvas.top - origin.y) * image.height / height),
           round((canvas.right - origin.x) * image.width / width),
           round((canvas.bottom - origin.y) * image.height / height))
    if not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
        raise RuntimeError('Native canvas falls outside the captured owned window')
    _check_canvas_image(image, box)
    return box


def _capture_window(session, hwnd, destination):
    ImageGrab = _require_window_capture()
    from .native_simulation import owned
    owned(session.pid, hwnd)
    image = ImageGrab.grab(window=hwnd)
    if image.width <= 0 or image.height <= 0 or image.convert('RGB').getextrema() == ((0, 0),) * 3:
        raise RuntimeError('The owned window capture is blank; check native rendering before retrying')
    canvas_box = _canvas_box(session, hwnd, image)
    descriptor, name = tempfile.mkstemp(prefix='.p86-capture-', suffix='.png', dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            image.save(stream, format='PNG')
        os.link(temporary, destination)  # Refuse to replace a concurrent output.
    finally:
        temporary.unlink(missing_ok=True)
    return dict(file=str(destination), sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                width=image.width, height=image.height, owned_window_only=True,
                schematic_canvas_box=canvas_box, schematic_canvas_nonblank=True)


def _write_report(path, report):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)


def capture_simulation(sim, destination, *, advance_seconds=0.01, animation_seconds=10000,
                       timeout=20, fit=True, width=1600, height=1000, foreground=True):
    """Restart a timer, prove clock advance around capture, then leave paused.

    A passed report certifies an advancing native engine and owned-window image,
    not multiplexed digits, voltage, LED brightness or electrical correctness.
    """
    from .simulation import SimulationError, validate_duration
    if any(isinstance(value, bool) for value in (advance_seconds, animation_seconds, timeout)):
        raise ValueError('Capture durations and timeout must be numeric, not booleans')
    advance = validate_duration(advance_seconds, timeout)
    animation = validate_duration(animation_seconds, timeout)
    if animation <= advance:
        raise ValueError('animation_seconds must exceed advance_seconds')
    if any(type(value) is not bool for value in (fit, foreground)):
        raise ValueError('fit and foreground must be booleans')
    if any(type(value) is not int or not 256 <= value <= 8192 for value in (width, height)):
        raise ValueError('width and height must be integer pixels between 256 and 8192')
    destination = Path(destination).resolve()
    record_path = destination.with_suffix(destination.suffix + '.json')
    if destination.suffix.lower() != '.png':
        raise ValueError('Native capture destination must be a new .png file')
    if destination.exists() or record_path.exists():
        raise FileExistsError('Capture image/report already exists: ' + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = dict(passed=False, backend='proteus_native_window', simulation_executed=False,
                  digital_function_verified=False, file=str(destination), pid=sim.session.pid,
                  scope='Advancing native engine and owned-window image; not a complete display frame or electrical test')
    error_in_flight = False
    try:
        report['desktop'] = _desktop_state(sim.session.pid)
        if report['desktop'].get('locked'):
            raise SimulationError('Windows desktop is locked; native schematic capture needs an unlocked interactive desktop. Unlock it and retry capture; simulation/file checks may continue separately')
        if report['desktop'].get('known') and report['desktop']['connection_state'] != 0:
            raise SimulationError('Windows desktop session is not active; reconnect the interactive desktop and retry native capture')
        initial = sim.pause()
        report['initial'] = initial
        hwnd = _prepare_window(sim.session, fit=fit, width=width, height=height, foreground=foreground)
        begun = sim._begin_timed(animation, timeout=timeout)
        start = begun['start_seconds']
        report['timer'] = begun

        def advancing(state):
            value = state.get('simulation_seconds')
            return state['state'] == 'running' and value is not None and math.isfinite(value) and value >= start + advance

        before = sim._wait(advancing, timeout)
        report['before_image'] = before
        report['image'] = _capture_window(sim.session, hwnd, destination)
        after = sim._wait(lambda state: state['state'] == 'running' and
                         state.get('simulation_seconds') is not None and
                         state['simulation_seconds'] > before['simulation_seconds'], timeout)
        report['after_image'] = after
        paused = sim.pause(timeout=timeout)
        report['paused_after_capture'] = paused
        if paused['state'] != 'paused' or paused.get('simulation_seconds') is None or paused['simulation_seconds'] < after['simulation_seconds']:
            raise SimulationError('Capture did not finish at a verified paused native time')
        report['diagnostics'] = sim.diagnostics()
        if not report['diagnostics']['passed']:
            raise SimulationError('Native diagnostics reported errors during capture')
        report.update(passed=True, simulation_executed=True,
                      observed_native_advance_seconds=paused['simulation_seconds'] - start)
    except BaseException as error:
        error_in_flight = True
        report.update(passed=False, error=repr(error))
        raise
    finally:
        if not report.get('paused_after_capture') or report['paused_after_capture'].get('state') != 'paused':
            try:
                report['paused_on_exit'] = sim.pause(timeout=timeout)
            except BaseException as error:
                report['pause_error'] = repr(error)
                report['passed'] = False
                _write_report(record_path, report)
                if not error_in_flight:
                    raise
        if not record_path.exists():
            _write_report(record_path, report)
    return report
