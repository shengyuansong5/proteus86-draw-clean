"""Native editor menu readiness must never dispatch stale or disabled IDs."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from proteus86.session import Session


PATH = 'Tool/Netlist Compiler'


def item(command_id=100, enabled=True, path=PATH):
    return dict(path=path, command_id=command_id, enabled=enabled)


def window(hwnd=123, cls='LX_APPLN_DClkNoDC'):
    return dict(hwnd=hwnd, cls=cls, enabled=True, title='circuit - Proteus 8 Professional')


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, duration):
        self.now += duration


class SessionMenuTests(unittest.TestCase):
    def setUp(self):
        self.session = Session.__new__(Session)
        self.session.pid = 321
        self.session.process = Mock(pid=321)
        self.session.process.poll.return_value = None
        self.session._ready = Mock(return_value=window())
        self.clock = Clock()
        self.get_menu = Mock(return_value=900)
        self.menus = Mock(return_value=[item()])
        self.post = Mock(return_value=True)
        self.pid_read = Mock(side_effect=self.read_owner)
        for target, value in (
                ('proteus86.session.time.monotonic', self.clock.monotonic),
                ('proteus86.session.time.sleep', self.clock.sleep),
                ('proteus86._codec.proteus_native.u.GetMenu', self.get_menu),
                ('proteus86._codec.proteus_native.menus', self.menus),
                ('proteus86._codec.proteus_native.u.PostMessageW', self.post),
                ('proteus86._codec.proteus_native.u.GetWindowThreadProcessId', self.pid_read)):
            operation = patch(target, value)
            operation.start()
            self.addCleanup(operation.stop)

    @staticmethod
    def read_owner(hwnd, pointer):
        pointer._obj.value = 321
        return 1

    def test_disabled_becomes_enabled_and_dispatch_uses_latest_command_id(self):
        self.menus.side_effect = [[item(10, False)], [item(20)], [item(30)]]
        self.assertIsNone(self.session.menu(PATH))  # Existing one-argument API.
        self.assertEqual(self.clock.now, .1)
        self.post.assert_called_once_with(123, 0x111, 30, 0)
        self.assertEqual(self.get_menu.call_count, 3)
        self.assertEqual(self.pid_read.call_count, 4)  # Every snapshot + dispatch.

    def test_enabled_again_disabled_is_not_sent_from_an_old_snapshot(self):
        self.menus.side_effect = [[item(10)], [item(20, False)], [item(30)], [item(40)]]
        self.session.menu(PATH)
        self.post.assert_called_once_with(123, 0x111, 40, 0)
        self.assertEqual(self.clock.now, .1)

    def test_permanently_disabled_menu_times_out_without_sending(self):
        self.menus.return_value = [item(enabled=False)]
        with self.assertRaisesRegex(TimeoutError, 'stayed disabled.*Tool/Netlist Compiler'):
            self.session.menu(PATH, timeout=.25)
        self.assertEqual(self.clock.now, .25)
        self.post.assert_not_called()

    def test_missing_or_ambiguous_paths_fail_immediately_even_if_one_is_enabled(self):
        for rows, reason in (([item(path='File/Save Project')], 'Missing'),
                             ([item(10), item(20, False)], 'Ambiguous')):
            with self.subTest(reason=reason):
                self.menus.return_value = rows
                with self.assertRaisesRegex(ValueError, reason + ' native menu path'):
                    self.session.menu(PATH)
                self.assertEqual(self.clock.now, 0)
        self.post.assert_not_called()

    def test_main_window_change_or_loss_during_wait_is_rejected(self):
        for replacement in (window(hwnd=456), None):
            with self.subTest(replacement=replacement):
                self.session._ready.side_effect = [window(), replacement]
                self.menus.return_value = [item(enabled=False)]
                with self.assertRaisesRegex(RuntimeError, 'main window (changed|is unavailable)'):
                    self.session.menu(PATH)
        self.post.assert_not_called()

    def test_changed_or_unrecognized_main_window_profile_is_rejected(self):
        self.session._ready.side_effect = [window(), window(cls='UnverifiedMainFrame')]
        self.menus.return_value = [item(enabled=False)]
        with self.assertRaisesRegex(RuntimeError, 'main window profile'):
            self.session.menu(PATH)
        self.post.assert_not_called()

    def test_live_hwnd_pid_change_is_rejected_before_dispatch(self):
        owner_values = iter((321, 999))
        def changed_owner(hwnd, pointer):
            pointer._obj.value = next(owner_values)
            return 1
        self.pid_read.side_effect = changed_owner
        with self.assertRaisesRegex(RuntimeError, 'no longer belongs'):
            self.session.menu(PATH)
        self.post.assert_not_called()

    def test_session_pid_or_process_object_change_is_rejected(self):
        for attribute, replacement in (('pid', 999), ('process', Mock(pid=321))):
            with self.subTest(attribute=attribute):
                self.session.pid = 321
                self.session.process = Mock(pid=321)
                self.session.process.poll.return_value = None
                self.session._ready.side_effect = None
                self.session._ready.return_value = window()
                self.menus.return_value = [item(enabled=False)]
                def sleep(duration):
                    self.clock.sleep(duration)
                    setattr(self.session, attribute, replacement)
                with patch('proteus86.session.time.sleep', sleep):
                    with self.assertRaisesRegex(RuntimeError, 'process identity changed'):
                        self.session.menu(PATH)
        self.post.assert_not_called()

    def test_owned_process_exit_during_wait_and_just_before_dispatch_is_rejected(self):
        for poll_results, rows in (([None, 7], [item(enabled=False)]),
                                   ([None, None, 7], [item()])):
            with self.subTest(poll_results=poll_results):
                self.session.process.poll.side_effect = poll_results
                self.menus.return_value = rows
                with self.assertRaisesRegex(RuntimeError, 'exited'):
                    self.session.menu(PATH)
        self.post.assert_not_called()

    def test_menu_handle_disappearing_is_a_profile_failure(self):
        self.get_menu.side_effect = [900, 0]
        with self.assertRaisesRegex(RuntimeError, 'main menu disappeared'):
            self.session.menu(PATH)
        self.post.assert_not_called()

    def test_invalid_options_do_not_read_or_post_native_menu(self):
        for timeout in (0, -1, float('inf'), float('nan'), True, '15', 301):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                self.session.menu(PATH, timeout=timeout)
        for path in ('', '  ', None):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.session.menu(path)
        self.get_menu.assert_not_called()
        self.post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
