"""Complete instruction/resource installs, checked backups and failure recovery."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/install_codex_skill.py'
spec = importlib.util.spec_from_file_location('install_codex_skill', SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class SkillInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'source checkout/skills/proteus86-files'
        self.source.mkdir(parents=True)
        (self.source / 'references').mkdir()
        (self.source / 'SKILL.md').write_text('---\nname: proteus86-files\n---\nInstructions\n', encoding='utf-8')
        (self.source / 'references/shared.md').write_text('Shared reference\n', encoding='utf-8')
        (self.source / 'references/obsolete.md').write_text('Old resource\n', encoding='utf-8')
        (self.source / 'assets').mkdir()
        (self.source / 'assets/示例 空格.bin').write_bytes(b'\x00\x81example')
        self.home = self.root / 'Codex home 中文'
        self.destination = self.home / 'skills/proteus86-files'

    def tearDown(self):
        self.temp.cleanup()

    def install(self, **options):
        return installer.install_skill(self.source, self.home, **options)

    def test_complete_resource_tree_and_local_checkout_locator_are_installed(self):
        result = self.install()
        self.assertEqual(result['status'], 'installed')
        self.assertEqual(result['files'], 4)
        for name in ('SKILL.md', 'references/shared.md', 'references/obsolete.md', 'assets/示例 空格.bin'):
            self.assertEqual((self.source / name).read_bytes(), (self.destination / name).read_bytes())
        manifest = json.loads((self.destination / installer.MANIFEST).read_text(encoding='utf-8'))
        self.assertEqual(Path(manifest['checkout_root']), self.source.parent.parent)
        (self.destination / 'local-notes.txt').write_text('Keep local notes')
        again = self.install()
        self.assertEqual(again['status'], 'already_installed')
        self.assertIsNone(again['backup'])
        self.assertEqual((self.destination / 'local-notes.txt').read_text(), 'Keep local notes')

    def test_update_requires_flag_then_preserves_extras_and_verified_full_backup(self):
        self.install()
        (self.destination / 'local-notes.txt').write_text('Unrelated local configuration')
        (self.destination / 'local-empty-directory').mkdir()
        before = installer._snapshot(self.destination)
        (self.source / 'SKILL.md').write_text('Updated instructions\n')
        (self.source / 'references/new.md').write_text('New nested resource\n')
        (self.source / 'references/obsolete.md').unlink()
        with self.assertRaises(FileExistsError):
            self.install()
        self.assertEqual(installer._snapshot(self.destination), before)
        result = self.install(update=True)
        backup = Path(result['backup'])
        self.assertEqual(result['status'], 'updated')
        self.assertFalse(backup.is_relative_to(self.home / 'skills'))
        self.assertEqual(installer._snapshot(backup), before)
        self.assertTrue((self.destination / 'references/new.md').is_file())
        self.assertFalse((self.destination / 'references/obsolete.md').exists())
        self.assertEqual((self.destination / 'local-notes.txt').read_text(), 'Unrelated local configuration')
        self.assertTrue((self.destination / 'local-empty-directory').is_dir())

    def test_user_modified_obsolete_resource_is_retained(self):
        self.install()
        (self.destination / 'references/obsolete.md').write_text('User-edited reference')
        (self.source / 'references/obsolete.md').unlink()
        self.install(update=True)
        self.assertEqual((self.destination / 'references/obsolete.md').read_text(), 'User-edited reference')

    def test_source_mutation_during_copy_refuses_publication(self):
        self.install()
        before = installer._snapshot(self.destination)
        (self.source / 'SKILL.md').write_text('Requested new instructions')
        original_copy = installer._copy_file
        changed = False

        def mutate(source, target):
            nonlocal changed
            original_copy(source, target)
            if source == self.source / 'references/shared.md' and not changed:
                changed = True
                source.write_text('Concurrent source modification')

        with patch.object(installer, '_copy_file', mutate):
            with self.assertRaisesRegex(RuntimeError, 'changed'):
                self.install(update=True)
        self.assertTrue(changed)
        self.assertEqual(installer._snapshot(self.destination), before)

    def test_destination_mutation_during_staging_is_not_overwritten(self):
        self.install()
        (self.destination / 'local-notes.txt').write_text('Original local value')
        old_skill = (self.destination / 'SKILL.md').read_bytes()
        (self.source / 'SKILL.md').write_text('Requested update')
        original_copy = installer._copy_file

        def mutate(source, target):
            original_copy(source, target)
            if source == self.source / 'SKILL.md':
                (self.destination / 'local-notes.txt').write_text('Concurrent user edit')

        with patch.object(installer, '_copy_file', mutate):
            with self.assertRaisesRegex(RuntimeError, 'changed'):
                self.install(update=True)
        self.assertEqual((self.destination / 'SKILL.md').read_bytes(), old_skill)
        self.assertEqual((self.destination / 'local-notes.txt').read_text(), 'Concurrent user edit')

    def test_interrupt_between_directory_renames_restores_previous_install(self):
        self.install()
        before = installer._snapshot(self.destination)
        (self.source / 'SKILL.md').write_text('Requested update')
        interruption = KeyboardInterrupt('Controlled publication interruption')
        with patch.object(installer, '_publish', side_effect=interruption):
            with self.assertRaises(KeyboardInterrupt) as caught:
                self.install(update=True)
        self.assertIs(caught.exception, interruption)
        self.assertEqual(installer._snapshot(self.destination), before)
        backups = list((self.home / 'skill-backups/proteus86-files').iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(installer._snapshot(backups[0]), before)

    def test_interrupt_immediately_after_publication_also_rolls_back(self):
        self.install()
        before = installer._snapshot(self.destination)
        (self.source / 'SKILL.md').write_text('Requested update')
        original_publish = installer._publish
        interruption = SystemExit(41)

        def publish_then_interrupt(source, target):
            original_publish(source, target)
            raise interruption

        with patch.object(installer, '_publish', publish_then_interrupt):
            with self.assertRaises(SystemExit) as caught:
                self.install(update=True)
        self.assertIs(caught.exception, interruption)
        self.assertEqual(installer._snapshot(self.destination), before)
        retained = list((self.home / '.skill-staging').glob('*/failed-publication/SKILL.md'))
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0].read_text(), 'Requested update')

    def test_fresh_install_failure_does_not_leave_a_live_partial_tree(self):
        with patch.object(installer, '_publish', side_effect=OSError('Controlled disk failure')):
            with self.assertRaises(OSError):
                self.install()
        self.assertFalse(self.destination.exists())

    def test_cleanup_lock_reports_verified_install_and_retains_private_staging(self):
        with patch.object(installer, '_remove_staging', side_effect=PermissionError('Controlled cleanup lock')):
            result = self.install()
        self.assertEqual(result['status'], 'installed')
        self.assertIn('cleanup lock', result['cleanup_warning'])
        self.assertTrue(Path(result['staging_retained']).is_dir())
        self.assertEqual((self.destination / 'references/shared.md').read_bytes(),
                         (self.source / 'references/shared.md').read_bytes())

    def test_cleanup_failure_does_not_mask_original_publication_interruption(self):
        self.install()
        before = installer._snapshot(self.destination)
        (self.source / 'SKILL.md').write_text('Requested update')
        interruption = KeyboardInterrupt('Keep original exception')
        with patch.object(installer, '_publish', side_effect=interruption), patch.object(
                installer, '_remove_staging', side_effect=PermissionError('Controlled cleanup lock')):
            with self.assertRaises(KeyboardInterrupt) as caught:
                self.install(update=True)
        self.assertIs(caught.exception, interruption)
        self.assertTrue(Path(caught.exception.skill_staging_retained).is_dir())
        self.assertEqual(installer._snapshot(self.destination), before)

    def test_blocked_recovery_retains_original_tree_and_verified_backup(self):
        self.install()
        before = installer._snapshot(self.destination)
        (self.source / 'SKILL.md').write_text('Requested update')
        original_rename = installer.os.rename

        def block_recovery(source, target):
            if Path(source).name == 'previous' and Path(target) == self.destination:
                raise PermissionError('Controlled recovery lock')
            return original_rename(source, target)

        with patch.object(installer, '_publish', side_effect=OSError('Controlled publication failure')), patch.object(
                installer.os, 'rename', block_recovery):
            with self.assertRaisesRegex(RuntimeError, 'original retained'):
                self.install(update=True)
        self.assertFalse(self.destination.exists())
        retained = list((self.home / '.skill-staging').glob('*/previous'))
        self.assertEqual(len(retained), 1)
        self.assertEqual(installer._snapshot(retained[0]), before)
        backups = list((self.home / 'skill-backups/proteus86-files').iterdir())
        self.assertEqual(installer._snapshot(backups[0]), before)

    def test_unsafe_managed_manifest_and_overlapping_paths_are_rejected(self):
        self.install()
        before = (self.destination / 'SKILL.md').read_bytes()
        path = self.destination / installer.MANIFEST
        path.write_text(json.dumps({'format': 1, 'files': {'../../victim.txt': '0' * 64}}))
        with self.assertRaises(ValueError):
            self.install(update=True)
        self.assertEqual((self.destination / 'SKILL.md').read_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'overlap'):
            installer.install_skill(self.source, self.source, update=True)


if __name__ == '__main__':
    unittest.main()
