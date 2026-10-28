"""A debugger's second id=3 bar must not replace the verified main identity."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from proteus86.native_simulation import StatusReader


def window(*handles, main=100):
    return dict(hwnd=main, children=[dict(hwnd=handle, control_id=3, cls='LX_APPLN_NoDC')
                                    for handle in handles])


class StatusWidgetTests(unittest.TestCase):
    def reader(self):
        reader=StatusReader.__new__(StatusReader)
        reader.session=SimpleNamespace(pid=77)
        return reader

    def test_debugger_widget_does_not_replace_initial_main_bar(self):
        reader=self.reader()
        with patch('proteus86.native_simulation.owned') as check:
            self.assertEqual(reader._widget(window(200))['hwnd'],200)
            self.assertEqual(reader._widget(window(300,200))['hwnd'],200)
            self.assertEqual(reader._widget(window(200,300))['hwnd'],200)
        self.assertEqual([call.args for call in check.call_args_list],[(77,200)]*3)

    def test_ambiguous_initial_or_replaced_widget_is_not_guessed(self):
        for initial in [window(),window(200,300)]:
            with self.subTest(initial=initial),self.assertRaises(RuntimeError):
                self.reader()._widget(initial)
        reader=self.reader()
        with patch('proteus86.native_simulation.owned'):
            reader._widget(window(200))
            with self.assertRaisesRegex(RuntimeError,'widget changed'):
                reader._widget(window(300))
            with self.assertRaisesRegex(RuntimeError,'main window changed'):
                reader._widget(window(200,main=101))

    def test_ownership_is_checked_on_every_use(self):
        reader=self.reader()
        with patch('proteus86.native_simulation.owned'):
            reader._widget(window(200))
        with patch('proteus86.native_simulation.owned',side_effect=RuntimeError('owner changed')):
            with self.assertRaisesRegex(RuntimeError,'owner changed'):
                reader._widget(window(200,300))


if __name__=='__main__':
    unittest.main()
