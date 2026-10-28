import copy
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
import subprocess
import sys
import os
from unittest.mock import patch
from zipfile import ZipFile

from proteus86 import Circuit, PropertyError, Project, diagnose_project, from_spec, package_project, prepare_run
from proteus86.installation import ROOT
from proteus86.resources import sha256


class ResourcesDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.firmware=self.root/'中文 固件目录'/'流水 灯.hex'
        self.firmware.parent.mkdir();shutil.copyfile(ROOT/'examples/blink8051.hex',self.firmware)

    def mcu(self):
        c=Circuit();c.add_mm('AT89C52','U1','AT89C52',0,0)
        return c

    def test_unicode_space_paths_are_portable_after_whole_folder_move(self):
        c=self.mcu()
        c.set_property_visibility('U1',PROGRAM=False)
        c.set_properties('U1',PROGRAM=str(self.firmware))
        source=c.save(self.root/'生成 项目'/'电路 图.pdsprj')
        before=sha256(self.firmware)
        reopened=Circuit.open(source)
        raw=reopened.components()[0]['properties']['PROGRAM']
        self.assertTrue(raw.isascii());self.assertFalse(Path(raw).is_absolute())
        self.assertEqual(sha256(source.parent/raw),before)
        self.assertIn('{PROGRAM=',reopened._template(reopened._parts[0])['properties'])
        shutil.copytree(source.parent,self.root/'移动后的 工程')
        self.firmware.unlink()  # Only this test's temporary fixture, never a course/user file.
        moved=self.root/'移动后的 工程'/source.name
        with patch('subprocess.Popen',side_effect=AssertionError('file packaging launched UI')):
            bundle=prepare_run(moved,self.root/'运行 包')
        self.assertEqual(bundle['firmware']['U1']['sha256'],before)
        self.assertEqual(Circuit.open(bundle['project']).nets(),reopened.nets())

    def test_reopening_and_saving_into_another_folder_carries_resources(self):
        c=self.mcu();c.bind_firmware('U1',self.firmware)
        first=c.save(self.root/'first'/'a.pdsprj')
        loaded=Circuit.open(first)
        other=loaded.save(self.root/'第二 个文件夹'/'b.pdsprj')
        raw=Circuit.open(other).components()[0]['properties']['PROGRAM']
        self.assertEqual(sha256(other.parent/raw),sha256(self.firmware))
        self.assertEqual(Circuit.open(first).components(),Circuit.open(other).components())

    def test_json_generation_resolves_resources_relative_to_design_and_orders_visibility(self):
        spec={'components':[dict(device='AT89C52',ref='U1',value='AT89C52',x=0,y=0,
                    properties={'PROGRAM':str(self.firmware.relative_to(self.root))},property_visibility={'PROGRAM':False})]}
        original=copy.deepcopy(spec)
        c=from_spec(spec,resource_base=self.root)
        saved=c.save(self.root/'json result'/'c.pdsprj')
        raw=Circuit.open(saved).components()[0]['properties']['PROGRAM']
        self.assertEqual(sha256(saved.parent/raw),sha256(self.firmware))
        self.assertEqual(spec,original)

    def test_cli_json_build_and_package_handle_unicode_paths_under_legacy_locale(self):
        spec={'components':[dict(device='AT89C52',ref='U1',value='AT89C52',x=0,y=0,
                        properties={'PROGRAM':str(self.firmware.relative_to(self.root))},property_visibility={'PROGRAM':False})]}
        design=self.root/'设计 输入.json';design.write_text(json.dumps(spec,ensure_ascii=False),encoding='utf-8')
        project=self.root/'输出 文件夹'/'测试 电路.pdsprj'
        environment=dict(os.environ,PYTHONUTF8='0')
        built=subprocess.run([sys.executable,'-m','proteus86','build',str(design),'-o',str(project)],cwd=ROOT,env=environment,capture_output=True)
        self.assertEqual(built.returncode,0,built.stderr.decode('utf-8'))
        self.assertEqual(json.loads(built.stdout.decode('utf-8'))['project'],str(project))
        packaged=subprocess.run([sys.executable,'-m','proteus86','package',str(project),'-o',str(self.root/'便携 包')],cwd=ROOT,env=environment,capture_output=True)
        self.assertEqual(packaged.returncode,0,packaged.stderr.decode('utf-8'))
        bundle=json.loads(packaged.stdout.decode('utf-8'))
        self.assertEqual(sha256(Path(bundle['project']).parent/bundle['firmware']['U1']['relative']),sha256(self.firmware))

    def test_changed_firmware_or_resource_collision_never_publishes_a_project(self):
        c=self.mcu();c.bind_firmware('U1',self.firmware)
        original=self.firmware.read_bytes()
        self.firmware.write_bytes(original+b'\n')
        with self.assertRaisesRegex(RuntimeError,'changed since binding'):c.save(self.root/'changed.pdsprj')
        self.assertFalse((self.root/'changed.pdsprj').exists())
        self.firmware.write_bytes(original)
        raw=c.components()[0]['properties']['PROGRAM']
        corrupt=self.root/raw;corrupt.parent.mkdir(parents=True,exist_ok=True);corrupt.write_bytes(b'user data')
        with self.assertRaisesRegex(RuntimeError,'collision'):c.save(self.root/'collision.pdsprj')
        self.assertEqual(corrupt.read_bytes(),b'user data')
        self.assertFalse((self.root/'collision.pdsprj').exists())

    def test_property_errors_have_component_property_cause_and_remedy(self):
        c=self.mcu()
        for key,value in [('CLOCK','中文'),('CLOCK','12MHz\nINJECT=1'),('BAD KEY','value')]:
            with self.assertRaises(PropertyError) as result:c.set_properties('U1',**{key:value})
            self.assertIn('U1.'+key,str(result.exception));self.assertIn('修复方法',str(result.exception))
        with self.assertRaisesRegex(PropertyError,'PROGRAM'):c.set_properties('U1',PROGRAM=str(self.root/'不存在 文件.hex'))
        c.add_mm('RESISTOR','R1','10k',70,0)
        with self.assertRaises(PropertyError):c.set_property_visibility('R1',PROGRAM=False)
        with self.assertRaises(PropertyError):c.set_properties('R1',PROGRAM='firmware.hex')
        with self.assertRaises(PropertyError):c.set_property_visibility('U1',PROGARM=False)

    def test_visibility_before_after_or_in_same_update_and_batch_rollback(self):
        for order in ('before','after','same'):
            c=self.mcu()
            if order=='before':c.set_property_visibility('U1',PROGRAM=False)
            if order=='same':c.update('U1',properties={'PROGRAM':'later.hex'},property_visibility={'PROGRAM':False})
            else:
                c.set_properties('U1',PROGRAM='later.hex')
                if order=='after':c.set_property_visibility('U1',PROGRAM=False)
            self.assertIn('{PROGRAM=later.hex}',c._template(c._parts[0])['properties'])
        c=self.mcu()
        with self.assertRaises(PropertyError):
            with c.batch():
                c.set_property_visibility('U1',PROGRAM=False)
                c.bind_firmware('U1',self.firmware)
                c.set_property_visibility('U1',PROGARM=False)
        self.assertEqual(c._resources,{})
        self.assertEqual(c._pending_visibility,{})
        self.assertNotIn('PROGRAM',c.components()[0]['properties'])

    def test_package_override_uses_same_checked_copy_without_launching(self):
        c=self.mcu();c.set_properties('U1',PROGRAM='missing.hex')
        original=c.save(self.root/'source.pdsprj');before=sha256(original)
        with patch('subprocess.Popen',side_effect=AssertionError('package launched UI')):
            report=package_project(original,self.root/'可移动 包',firmware={'U1':self.firmware})
        self.assertEqual(before,sha256(original))
        info=report['firmware']['U1']
        self.assertEqual(sha256(Path(report['project']).parent/info['relative']),info['sha256'])

    def test_pending_visibility_follows_copy_and_rename_but_not_deleted_reference(self):
        c=self.mcu();c.set_property_visibility('U1',PROGRAM=False)
        c.copy_component('U1','U2',10000000,0);c.rename('U2','U3')
        c.set_properties('U3',PROGRAM='later.hex')
        self.assertIn('{PROGRAM=later.hex}',c._template(c._parts[c._index('U3')])['properties'])
        c.delete_component('U1');c.add_mm('AT89C52','U1','AT89C52',0,0)
        c.set_properties('U1',PROGRAM='new.hex')
        self.assertNotIn('{PROGRAM=new.hex}',c._template(c._parts[c._index('U1')])['properties'])

    def test_binding_does_not_silently_override_an_embedded_build_project(self):
        source=self.mcu().save(self.root/'external.pdsprj')
        embedded=self.root/'embedded.pdsprj'
        with ZipFile(source) as incoming,ZipFile(embedded,'w') as outgoing:
            for name in incoming.namelist():outgoing.writestr(name,incoming.read(name))
            outgoing.writestr('FIRMWARE.XML',b'<FIRMWARE/>')
        c=Circuit.open(embedded);before=sha256(embedded)
        with self.assertRaisesRegex(PropertyError,'嵌入式'):c.bind_firmware('U1',self.firmware)
        self.assertEqual(c._resources,{})
        self.assertEqual(sha256(embedded),before)

    def test_version_and_component_table_diagnostics_remain_guarded(self):
        source=self.mcu().save(self.root/'known.pdsprj')
        project=Project(source)
        table=min(item['cdb_offset'] for item in project._components.values())
        for kind in ('version','structure'):
            output=self.root/(kind+'.pdsprj')
            with ZipFile(source) as incoming,ZipFile(output,'w') as outgoing:
                for name in incoming.namelist():
                    data=incoming.read(name)
                    if name=='ROOT.CDB':
                        data=bytearray(data)
                        struct.pack_into('<I',data,0 if kind=='version' else table-4,3 if kind=='version' else 0)
                    outgoing.writestr(name,data)
            report=diagnose_project(output)
            self.assertFalse(report['readable']);self.assertTrue(report['source_unchanged'])
            self.assertIn(kind,[f['category'] for f in report['findings'] if f['severity']=='error'])
            with self.assertRaises(ValueError):Circuit.open(output)

    def test_actual_teacher_reference_diagnostics_are_read_only(self):
        reference_root=os.environ.get('PROTEUS86_REFERENCE_ROOT')
        if not reference_root:self.skipTest('Optional private reference fixtures not configured')
        root=Path(reference_root)
        if not root.is_dir():self.skipTest('Local read-only reference files not available')
        results=[diagnose_project(p) for p in sorted(root.rglob('*.pdsprj'))]
        self.assertEqual(len(results),2)
        self.assertEqual([r['format']['CDB'] for r in results],[3,5])
        self.assertTrue(all(r['source_unchanged'] and not r['readable'] for r in results))
        codes={f['code'] for f in results[1]['findings']}
        self.assertIn('anonymous_entity',codes);self.assertIn('component_record_layout',codes)
        self.assertIn('non_ascii_component_properties',codes)
