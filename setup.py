"""Map canonical helpers into a unique wheel namespace without copying core."""
from setuptools import setup
from setuptools.command.build_py import build_py as BaseBuildPy


class BuildPy(BaseBuildPy):
    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        approved = {
            'proteus86_support.examples': {'__init__', 'draw_matrix_display', 'build_matrix_firmware'},
            'proteus86_support.scripts': {'__init__', 'verify_matrix_display'},
        }.get(package)
        return [item for item in modules if item[1] in approved] if approved is not None else modules


setup(cmdclass={'build_py': BuildPy})
