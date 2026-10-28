"""Resolve the same approved helpers from a checkout or an installed wheel."""
from functools import lru_cache
from importlib import import_module
from pathlib import Path
import sys
from types import ModuleType

_APPROVED = frozenset(('examples.build_matrix_firmware', 'examples.draw_matrix_display',
                       'scripts.verify_matrix_display'))


@lru_cache(maxsize=3)
def helper(name):
    if name not in _APPROVED:
        raise ValueError('Unknown supporting tool')
    root = Path(__file__).resolve().parents[1]
    if (root / 'pyproject.toml').is_file() and (root / (name.replace('.', '/') + '.py')).is_file():
        namespace = '_proteus86_checkout_support'
        existing = sys.modules.get(namespace)
        if existing is None:
            existing = ModuleType(namespace)
            existing.__path__ = [str(root)]
            sys.modules[namespace] = existing
        elif list(existing.__path__) != [str(root)]:
            raise RuntimeError('Supporting-tool namespace belongs to a different checkout')
        return import_module(namespace + '.' + name)
    return import_module('proteus86_support.' + name)
