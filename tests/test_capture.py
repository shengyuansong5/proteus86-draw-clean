"""Running menu/status alone must never certify a native screenshot."""
import json
from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from proteus86.capture import (capture_simulation, _canvas_box, _check_canvas_image,
                               _require_window_capture, _prepare_window, _capture_window)
from proteus86.simulation import Simulation, SimulationError

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = ImageDraw = None


def state(value, mode='running'):
    return dict(state=mode, simulation_seconds=value, time_resolution_seconds=0.000001)


def fake_sim():
    sim = SimpleNamespace(session=SimpleNamespace(pid=321),
        pause=Mock(side_effect=[state(.2, 'paused'), state(.26, 'paused'), state(.26, 'paused')]),
        _begin_timed=Mock(return_value=dict(start_seconds=.2)),
        diagnostics=Mock(return_value=dict(passed=True, errors=[], warnings=[])),
        _wait=Mock(side_effect=[state(.22), state(.25)]))
    return sim


class CaptureTests(unittest.TestCase):
    def setUp(self):
        # Unit tests must not depend on the developer's live desktop session.
        desktop = patch('proteus86.capture._desktop_state', return_value=dict(known=False))
        desktop.start()
        self.addCleanup(desktop.stop)

    def test_valid_capture_checks_both_clock_advances_and_finishes_paused(self):
        sim = fake_sim()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'frame.png'
            with patch('proteus86.capture._prepare_window', return_value=123), patch(
                    'proteus86.capture._capture_window', return_value={'file': str(path)}) as capture:
                result = capture_simulation(sim, path)
            self.assertTrue(result['passed'])
            self.assertTrue(result['simulation_executed'])
            self.assertFalse(result['digital_function_verified'])
            self.assertEqual(result['paused_after_capture']['state'], 'paused')
            before_test = sim._wait.call_args_list[0].args[0]
            self.assertFalse(before_test(state(.2)))
            self.assertTrue(before_test(state(.22)))
            after_test = sim._wait.call_args_list[1].args[0]
            self.assertFalse(after_test(state(.22)))
            self.assertTrue(after_test(state(.25)))
            capture.assert_called_once()
            self.assertTrue(json.loads(path.with_suffix('.png.json').read_text())['passed'])

    def test_animating_without_clock_progress_is_not_captured_or_passed(self):
        sim = fake_sim()
        sim.status = Mock(return_value=state(.2))
        sim._wait = lambda predicate, timeout: Simulation._wait(sim, predicate, timeout)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'stalled.png'
            with patch('proteus86.capture._prepare_window', return_value=123), patch(
                    'proteus86.capture._capture_window') as capture:
                with self.assertRaises(TimeoutError):
                    capture_simulation(sim, path, timeout=.02)
            capture.assert_not_called()
            result = json.loads(path.with_suffix('.png.json').read_text())
            self.assertFalse(result['passed'])
            self.assertFalse(result['simulation_executed'])
            self.assertEqual(result['paused_on_exit']['state'], 'paused')

    def test_stall_after_image_is_not_certified(self):
        sim = fake_sim()
        sim._wait.side_effect = [state(.22), TimeoutError('native time stalled after capture')]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'late-stall.png'
            with patch('proteus86.capture._prepare_window', return_value=123), patch(
                    'proteus86.capture._capture_window', return_value={'file': str(path)}):
                with self.assertRaises(TimeoutError):
                    capture_simulation(sim, path)
            self.assertFalse(json.loads(path.with_suffix('.png.json').read_text())['passed'])

    def test_interrupt_keeps_original_exception_and_pauses_with_failure_record(self):
        sim = fake_sim()
        interruption = KeyboardInterrupt('cancel capture')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cancelled.png'
            with patch('proteus86.capture._prepare_window', return_value=123), patch(
                    'proteus86.capture._capture_window', side_effect=interruption):
                with self.assertRaises(KeyboardInterrupt) as caught:
                    capture_simulation(sim, path)
            self.assertIs(caught.exception, interruption)
            result = json.loads(path.with_suffix('.png.json').read_text())
            self.assertFalse(result['passed'])
            self.assertEqual(result['paused_on_exit']['state'], 'paused')

    def test_existing_output_and_invalid_options_do_not_operate_native_session(self):
        sim = fake_sim()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'output.png'
            for options in [dict(advance_seconds=0), dict(animation_seconds=.001), dict(width=True),
                            dict(fit='yes'), dict(foreground=1)]:
                with self.subTest(options=options), self.assertRaises(ValueError):
                    capture_simulation(sim, path, **options)
            path.write_bytes(b'preserved')
            with self.assertRaises(FileExistsError):
                capture_simulation(sim, path)
            self.assertEqual(path.read_bytes(), b'preserved')
        sim.pause.assert_not_called()
        sim._begin_timed.assert_not_called()

    def test_locked_desktop_fails_explicitly_and_records_pause_without_starting(self):
        sim = fake_sim()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'locked.png'
            with patch('proteus86.capture._desktop_state', return_value=dict(
                    known=True, connection_state=0, locked=True)), patch(
                    'proteus86.capture._prepare_window') as prepare:
                with self.assertRaisesRegex(SimulationError, 'desktop is locked'):
                    capture_simulation(sim, path)
            result = json.loads(path.with_suffix('.png.json').read_text())
            self.assertFalse(result['passed'])
            self.assertFalse(result['simulation_executed'])
            self.assertTrue(result['desktop']['locked'])
            self.assertEqual(result['paused_on_exit']['state'], 'paused')
            self.assertFalse(path.exists())
        prepare.assert_not_called()
        sim._begin_timed.assert_not_called()

    def test_disconnected_desktop_is_not_certified(self):
        sim = fake_sim()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'disconnected.png'
            with patch('proteus86.capture._desktop_state', return_value=dict(
                    known=True, connection_state=4, locked=False)), patch(
                    'proteus86.capture._prepare_window') as prepare:
                with self.assertRaisesRegex(SimulationError, 'not active'):
                    capture_simulation(sim, path)
            self.assertFalse(json.loads(path.with_suffix('.png.json').read_text())['passed'])
        prepare.assert_not_called()
        sim._begin_timed.assert_not_called()

    def test_canvas_is_main_control_five_and_uses_client_origin_with_bitmap_scaling(self):
        # Minimap 6 has genuine circuit-colored pixels but must never certify 5.
        native_u = SimpleNamespace(GetClientRect=Mock(), ClientToScreen=Mock(), GetWindowRect=Mock())
        def client(hwnd, pointer):
            self.assertEqual(hwnd, 123)
            pointer._obj.right, pointer._obj.bottom = 1000, 600
            return True
        def origin(hwnd, pointer):
            self.assertEqual(hwnd, 123)
            pointer._obj.x, pointer._obj.y = 200, 100
            return True
        def rectangle(hwnd, pointer):
            self.assertEqual(hwnd, 555)
            rect = pointer._obj
            rect.left, rect.top, rect.right, rect.bottom = 500, 250, 1150, 650
            return True
        native_u.GetClientRect.side_effect = client
        native_u.ClientToScreen.side_effect = origin
        native_u.GetWindowRect.side_effect = rectangle
        session = SimpleNamespace(pid=321, _ready=lambda: dict(children=[
            dict(cls='LX_APPLN_OwnDC', control_id=6, hwnd=666),
            dict(cls='LX_APPLN_OwnDC', control_id=5, hwnd=555)]))
        owner = Mock()
        with patch.dict('sys.modules', {
                'proteus86._codec.proteus_native': SimpleNamespace(u=native_u),
                'proteus86.native_simulation': SimpleNamespace(owned=owner)}), patch(
                'proteus86._codec.proteus_native', SimpleNamespace(u=native_u), create=True), patch(
                'proteus86.capture._check_canvas_image') as check:
            image = SimpleNamespace(width=2000, height=1200)
            box = _canvas_box(session, 123, image)
        self.assertEqual(box, (600, 300, 1900, 1100))
        check.assert_called_once_with(image, box)
        self.assertEqual(owner.call_args_list[0].args, (321, 123))
        self.assertEqual(owner.call_args_list[1].args, (321, 555))

    @unittest.skipIf(Image is None, 'Pillow is optional outside native screenshot use')
    def test_colored_toolbars_minimap_and_widget_border_cannot_certify_white_canvas(self):
        image = Image.new('RGB', (800, 600), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 799, 99), fill='blue')
        draw.rectangle((5, 110, 95, 200), fill='red')
        draw.rectangle((100, 100, 799, 599), outline='black', width=2)
        with self.assertRaisesRegex(RuntimeError, 'schematic canvas is blank'):
            _check_canvas_image(image, (100, 100, 800, 600))
        draw.line((180, 180, 600, 400), fill='green', width=3)
        _check_canvas_image(image, (100, 100, 800, 600))

    @unittest.skipIf(Image is None, 'Pillow is optional outside native screenshot use')
    def test_black_and_uniform_colored_main_canvas_are_also_rejected(self):
        for color in ('black', 'white', '#ddddbb'):
            with self.subTest(color=color), self.assertRaisesRegex(RuntimeError, 'canvas is blank'):
                _check_canvas_image(Image.new('RGB', (100, 100), color), (0, 0, 100, 100))


class WindowCaptureDependencyTests(unittest.TestCase):
    def pillow(self, grab):
        package, backend = ModuleType('PIL'), ModuleType('PIL.ImageGrab')
        package.__version__ = 'not-a-version-string'
        package.ImageGrab = backend
        backend.grab = grab
        return {'PIL': package, 'PIL.ImageGrab': backend}

    @contextmanager
    def window(self):
        api = SimpleNamespace(GetSystemMetrics=Mock(side_effect=lambda index: 2400),
            ShowWindow=Mock(), SetWindowPos=Mock(), BringWindowToTop=Mock(), SetForegroundWindow=Mock())
        native = SimpleNamespace(u=api)
        owner = Mock()
        session = SimpleNamespace(pid=321, process=SimpleNamespace(poll=Mock(return_value=None)),
            _ready=Mock(return_value=dict(hwnd=123)), _wait=lambda ready: ready(), menu=Mock())
        with patch.dict(sys.modules, {'proteus86._codec.proteus_native': native,
                'proteus86.native_simulation': SimpleNamespace(owned=owner)}), patch(
                'proteus86._codec.proteus_native', native, create=True), patch('proteus86.capture.time.sleep'):
            yield session, api, owner

    def test_missing_pillow_has_minimum_version_and_repair_command(self):
        with patch.dict(sys.modules, {'PIL': None, 'PIL.ImageGrab': None}):
            with self.assertRaises(RuntimeError) as caught:
                _require_window_capture()
        self.assertIn('Pillow>=11.2.1', str(caught.exception))
        self.assertIn('python -m pip install', str(caught.exception))

    def test_missing_imagegrab_has_actionable_optional_dependency_error(self):
        with patch.dict(sys.modules, {'PIL': ModuleType('PIL'), 'PIL.ImageGrab': None}):
            with self.assertRaisesRegex(RuntimeError, 'Pillow>=11.2.1'):
                _require_window_capture()

    def test_old_or_kwargs_only_signatures_are_not_probed_or_used_as_desktop_fallback(self):
        calls = []
        def old(bbox=None):
            calls.append(bbox)
        def kwargs_only(**kwargs):
            calls.append(kwargs)
        def named_kwargs(**window):
            calls.append(window)
        def positional_only(window, /):
            calls.append(window)
        for grab in (old, kwargs_only, named_kwargs, positional_only, None):
            with self.subTest(grab=grab), patch.dict(sys.modules, self.pillow(grab)):
                with self.assertRaisesRegex(RuntimeError, 'Pillow>=11.2.1'):
                    _require_window_capture()
        self.assertEqual(calls, [])

    def test_explicit_keyword_support_is_accepted_without_reading_version_or_capturing(self):
        calls = []
        def ordinary(bbox=None, window=None):
            calls.append(window)
        def keyword_only(*, window=None):
            calls.append(window)
        for grab in (ordinary, keyword_only):
            modules = self.pillow(grab)
            with self.subTest(grab=grab), patch.dict(sys.modules, modules):
                self.assertIs(_require_window_capture(), modules['PIL.ImageGrab'])
        self.assertEqual(calls, [])

    def test_uninspectable_backend_is_rejected_without_guessing_support(self):
        def grab(*, window=None):
            self.fail('Capability inspection must not capture')
        grab.__signature__ = 'invalid signature'
        with patch.dict(sys.modules, self.pillow(grab)):
            with self.assertRaisesRegex(RuntimeError, 'Cannot verify.*Pillow>=11.2.1'):
                _require_window_capture()

    def test_dependency_failure_precedes_any_window_changes(self):
        def old(bbox=None):
            self.fail('Old backend must never be called')
        with patch.dict(sys.modules, self.pillow(old)), self.window() as (session, api, owner):
            with self.assertRaisesRegex(RuntimeError, 'Pillow>=11.2.1'):
                _prepare_window(session, fit=True, width=1600, height=1000, foreground=True)
        api.ShowWindow.assert_not_called()
        api.SetWindowPos.assert_not_called()
        api.BringWindowToTop.assert_not_called()
        api.SetForegroundWindow.assert_not_called()
        session.menu.assert_not_called()

    def test_supported_backend_captures_only_explicit_owned_hwnd_in_both_paths(self):
        calls = []
        image = SimpleNamespace(width=64, height=64,
            convert=lambda mode: SimpleNamespace(getextrema=lambda: ((0, 255),) * 3),
            save=lambda stream, format: stream.write(b'unit-test-image'))
        def grab(bbox=None, *, window=None):
            calls.append((bbox, window))
            self.assertEqual(window, 123)
            return image
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, self.pillow(grab)), self.window() as (session, api, owner):
            self.assertEqual(_prepare_window(session, fit=False, width=1600, height=1000, foreground=False), 123)
            with patch('proteus86.capture._canvas_box', return_value=(0, 0, 64, 64)):
                result = _capture_window(session, 123, Path(directory) / 'owned.png')
            self.assertTrue(result['owned_window_only'])
            self.assertEqual(Path(result['file']).read_bytes(), b'unit-test-image')
        self.assertEqual(calls, [(None, 123), (None, 123)])

    def test_capture_rechecks_backend_when_it_changed_after_window_preparation(self):
        calls = []
        def supported(*, window=None):
            calls.append(window)
        def old(bbox=None):
            self.fail('No full-desktop fallback is allowed')
        modules = self.pillow(supported)
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, modules), self.window() as (session, api, owner):
            _prepare_window(session, fit=False, width=1600, height=1000, foreground=False)
            modules['PIL.ImageGrab'].grab = old
            path = Path(directory) / 'changed.png'
            with self.assertRaisesRegex(RuntimeError, 'Pillow>=11.2.1'):
                _capture_window(session, 123, path)
            self.assertFalse(path.exists())
        self.assertEqual(calls, [123])

    def test_dependency_errors_keep_failed_json_and_paused_cleanup(self):
        def old(bbox=None):
            self.fail('Old backend must not capture the desktop')
        for modules in ({'PIL': None, 'PIL.ImageGrab': None}, self.pillow(old)):
            sim = fake_sim()
            with self.subTest(modules=modules), tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, modules), patch(
                    'proteus86.capture._desktop_state', return_value=dict(known=False)):
                path = Path(directory) / 'unsupported.png'
                with self.assertRaisesRegex(RuntimeError, 'Pillow>=11.2.1'):
                    capture_simulation(sim, path)
                report = json.loads(path.with_suffix('.png.json').read_text())
                self.assertFalse(report['passed'])
                self.assertFalse(report['simulation_executed'])
                self.assertEqual(report['paused_on_exit']['state'], 'paused')
                self.assertFalse(path.exists())
            self.assertEqual(sim.pause.call_count, 2)
            sim._begin_timed.assert_not_called()

    def test_mocked_capture_can_run_without_pillow_installed(self):
        sim = fake_sim()
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {'PIL': None, 'PIL.ImageGrab': None}), patch(
                'proteus86.capture._desktop_state', return_value=dict(known=False)), patch(
                'proteus86.capture._prepare_window', return_value=123), patch(
                'proteus86.capture._capture_window', return_value=dict(owned_window_only=True)):
            report = capture_simulation(sim, Path(directory) / 'mocked.png')
        self.assertTrue(report['passed'])

    def test_fresh_file_api_and_capture_module_imports_need_no_pillow(self):
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c',
            "import sys; sys.modules['PIL'] = None; sys.modules['PIL.ImageGrab'] = None; "
            "from proteus86 import Circuit; import proteus86.capture"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
