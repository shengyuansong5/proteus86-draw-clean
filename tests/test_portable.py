"""Portable entries reuse the full checked installer and preserve runtime isolation."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.install_codex_skill import install_platform_skill
from portable.install import write_config, main
from contextlib import redirect_stdout
import io
from scripts.build_portable import extract
from portable.mcp import prepare_output
import zipfile


class PortableTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.app=self.root/'bundle 中文 & space/app'
        skill=self.app/'skills/proteus86-files'
        (skill/'references').mkdir(parents=True)
        (skill/'SKILL.md').write_text('Common instructions\n',encoding='utf-8')
        (skill/'references/shared.md').write_text('Same resource\n',encoding='utf-8')
        for platform in ('codex','dsh'):
            folder=self.app/'adapters'/platform
            folder.mkdir(parents=True)
            (folder/'skill.md').write_text(platform+' entry',encoding='utf-8')
        (self.app/'portable').mkdir()
        (self.app/'portable/skill.md').write_text('Use the bundled runtime only.',encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_portable_runtime_rejects_before_installation(self):
        home=self.root/'home'
        with self.assertRaises(FileNotFoundError):
            install_platform_skill(self.app,home,'codex',portable=True)
        self.assertFalse(home.exists())

    def test_both_entries_use_canonical_resources_and_portable_runtime_instructions(self):
        runtime=self.app.parent/'runtime'
        runtime.mkdir()
        (runtime/'python.exe').write_bytes(b'test placeholder, never executed')
        installed=[]
        for platform in ('codex','dsh'):
            home=self.root/platform
            install_platform_skill(self.app,home,platform,portable=True)
            target=home/'skills/proteus86-files'
            text=(target/'SKILL.md').read_text(encoding='utf-8')
            self.assertIn(platform+' entry',text)
            self.assertIn('Use the bundled runtime only.',text)
            manifest=json.loads((target/'.proteus86-install.json').read_text(encoding='utf-8'))
            self.assertEqual(Path(manifest['checkout_root']),self.app.resolve())
            installed.append((target/'references/shared.md').read_bytes())
        self.assertEqual(installed[0],installed[1])

    def test_mcp_config_preserves_profiles_and_retains_backup_on_location_change(self):
        bundle=self.app.parent
        profile=bundle/'existing-profile.yml'
        profile.write_text('Unrelated existing profile',encoding='utf-8')
        target=write_config(bundle)
        text=target.read_text(encoding='utf-8')
        command=json.loads(text.split('        command: ',1)[1].splitlines()[0])
        self.assertEqual(Path(command),bundle/'runtime/python.exe')
        self.assertEqual(profile.read_text(encoding='utf-8'),'Unrelated existing profile')
        target.write_text('Custom old patch',encoding='utf-8')
        write_config(bundle)
        backups=list(target.parent.glob('*.backup.yml'))
        self.assertEqual(len(backups),1)
        self.assertEqual(backups[0].read_text(encoding='utf-8'),'Custom old patch')

    def test_untrusted_archive_cannot_escape_extraction_root(self):
        archive=self.root/'bad.zip'
        with zipfile.ZipFile(archive,'w') as zipped:
            zipped.writestr('../outside.txt','unexpected')
        with self.assertRaises(ValueError):
            extract(archive,self.root/'extracted')
        self.assertFalse((self.root/'outside.txt').exists())

    def test_agent_argument_error_returns_json_and_nonzero_without_prompt(self):
        output=io.StringIO()
        with redirect_stdout(output),self.assertRaises(SystemExit) as caught:
            main(['--json'])
        self.assertEqual(caught.exception.code,2)
        result=json.loads(output.getvalue())
        self.assertFalse(result['passed'])
        self.assertEqual(result['error']['type'],'ArgumentError')

    def test_startup_output_creation_keeps_shared_workspace_guards(self):
        workspace=self.root/'workspace'
        workspace.mkdir()
        outside=self.root/'outside'
        with self.assertRaises(ValueError):
            prepare_output(workspace,outside)
        self.assertFalse(outside.exists())
        expected=workspace/'output/proteus86'
        self.assertEqual(prepare_output(workspace,expected),expected)
        self.assertTrue(expected.is_dir())


if __name__=='__main__':
    unittest.main()
