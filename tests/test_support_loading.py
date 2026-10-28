"""Checkout helpers use the exact approved files without generic import collisions."""
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

from proteus86.support import helper


class SupportLoadingTests(unittest.TestCase):
    def test_checkout_loader_ignores_unrelated_generic_packages(self):
        root = Path(__file__).resolve().parents[1]
        helper.cache_clear()
        try:
            with patch.dict(sys.modules, {'examples': ModuleType('examples'), 'scripts': ModuleType('scripts')}):
                builder = helper('examples.build_matrix_firmware')
                generator = helper('examples.draw_matrix_display')
                verifier = helper('scripts.verify_matrix_display')
                self.assertEqual(Path(generator.__file__).resolve(), root / 'examples/draw_matrix_display.py')
                self.assertEqual(Path(verifier.__file__).resolve(), root / 'scripts/verify_matrix_display.py')
                self.assertIs(verifier.generate, generator.generate)
                self.assertIs(verifier.build_firmware, builder.build)
                self.assertIs(verifier, helper('scripts.verify_matrix_display'))
        finally:
            helper.cache_clear()

    def test_unapproved_helpers_are_rejected_before_import(self):
        with self.assertRaisesRegex(ValueError, 'Unknown supporting tool'):
            helper('scripts.unreviewed_local_probe')


if __name__ == '__main__':
    unittest.main()
