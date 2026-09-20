"""Real CLI/filesystem boundaries; skips report unavailable link privileges explicitly."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from test_regression import ProjectHarness, ROOT, PYTHON, make_temp_dir, remove_tree, run, write_json

COMMANDS=[('ai-audit','--input'),('ai-register-change','--input'),('ai-start','--request'),('ai-finish','--result'),
 ('ai-acceptance','--input'),('new-decision','--input'),('ai-suspend-for-promotion','--input'),('ai-promote-standard','--input'),
 ('ai-requirement','--input'),('ai-release-baseline','--input'),('ai-generate-delivery','--input'),('ai-final-acceptance','--input'),
 ('ai-close-project','--input'),('ai-reopen-project','--input'),('ai-handoff-batch','--input'),('ai-evidence','--input'),('ai-unit','--input')]

class SecurityBoundaryTests(unittest.TestCase):
    def temp(self):
        p=make_temp_dir('security-boundary-');self.addCleanup(remove_tree,p);return p
    def link(self,path,target,directory=False,junction=False):
        if junction:
            if os.name!='nt':self.skipTest('Windows junction runtime case only')
            run(['cmd.exe','/d','/c','mklink','/J',str(path),str(target)])
            self.addCleanup(lambda:path.rmdir() if path.exists() else None)
        else:
            try:path.symlink_to(target,target_is_directory=directory)
            except OSError as exc:self.skipTest('Symlink creation unavailable: '+str(exc))
            self.addCleanup(lambda:path.unlink() if path.is_symlink() else None)
    def denied_inputs(self,kind):
        h=ProjectHarness(self,governance_mode='standard');h.start_batch()
        outside=h.root.parent/'outside.json';outside.write_bytes(b'{"evidence":"must survive"}\n');before=outside.read_bytes()
        values={'traversal':'../outside.json','absolute':str(outside.resolve()),'drive':r'C:\outside.json',
                'drive_relative':r'C:outside.json','unc':r'\\server\share\outside.json','posix':'/outside.json'}
        for cmd,flag in COMMANDS:
            with self.subTest(command=cmd,kind=kind):
                original=(h.root/'.ai/runtime/active_batch.json').read_bytes()
                proc=h.tool(cmd,flag,values[kind],expect=1)
                self.assertIn('path',proc.stderr.lower())
                self.assertEqual(outside.read_bytes(),before)
                self.assertEqual((h.root/'.ai/runtime/active_batch.json').read_bytes(),original)
    def test_cli_traversal(self):self.denied_inputs('traversal')
    def test_cli_absolute(self):self.denied_inputs('absolute')
    def test_cli_windows_drive(self):self.denied_inputs('drive')
    def test_cli_drive_relative(self):self.denied_inputs('drive_relative')
    def test_cli_unc(self):self.denied_inputs('unc')
    def test_cli_posix_absolute(self):self.denied_inputs('posix')
    def linked_input(self,junction=False,internal=False):
        h=ProjectHarness(self,governance_mode='standard');h.start_batch()
        target=(h.root/'docs' if internal else h.root.parent)/'payload';target.mkdir()
        outside=target/'request.json';outside.write_bytes(b'{"unchanged":true}\n');before=outside.read_bytes()
        link=h.root/'linked'
        self.link(link,target,directory=True,junction=junction)
        for cmd,flag in [('ai-register-change','--input'),('ai-start','--request'),('ai-finish','--result')]:
            h.tool(cmd,flag,'linked/request.json',expect=1)
            self.assertTrue(outside.exists());self.assertEqual(outside.read_bytes(),before)
    def test_cli_external_symlink(self):self.linked_input()
    def test_cli_internal_symlink_also_rejected(self):self.linked_input(internal=True)
    def test_cli_windows_junction(self):self.linked_input(junction=True)
    def test_custom_and_default_requests_still_consumed(self):
        h=ProjectHarness(self,governance_mode='standard')
        request={'batch_id':'P1-001','stage_id':'P1','title':'Regression batch','goal':'Fixture','scope':['fixture'],'acceptance_criteria':['fixture']}
        custom=h.root/'docs/custom-request.json';write_json(custom,request)
        h.tool('ai-start','--request','docs/custom-request.json');self.assertFalse(custom.exists())
        result=h.result_payload('blocked',[{'name':'fixture','status':'blocked','details':'real incomplete request'}],['pending'])
        custom=h.root/'docs/custom-result.json';write_json(custom,result)
        h.tool('ai-finish','--result','docs/custom-result.json',expect=1);self.assertFalse(custom.exists())
        self.assertEqual(json.loads((h.root/'.ai/runtime/active_batch.json').read_text())['status'],'blocked')
        default=h.root/'.ai/runtime/batch_result.json';write_json(default,result)
        h.tool('ai-finish',expect=1);self.assertFalse(default.exists())
    def template(self):
        base=self.temp();repo=base/'template-workspace';src=repo/'current';src.mkdir(parents=True)
        (repo/'START_HERE.md').write_text('Fixture workspace',encoding='utf-8')
        for name in ['starter.py','profiles.toml','path_safety.py']:shutil.copyfile(ROOT/name,src/name)
        shutil.copytree(ROOT/'scaffold',src/'scaffold',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        return base,repo,src
    def init(self,src,target,expect=0,force=False):
        return run([PYTHON,'-B',str(src/'starter.py'),'init','--target',str(target),'--name','Boundary fixture','--description','Synthetic boundary','--profile','generic','--governance-mode','lite',*(['--force'] if force else [])],expect=expect)
    def snapshot(self,root):return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    def test_initializer_overlap_rejected_before_staging(self):
        base,repo,src=self.template();before=self.snapshot(base)
        for target in [repo,src,repo/'new-child',src/'new-child',base]:
            with self.subTest(target=str(target)):
                result=self.init(src,target,expect=1,force=True)
                self.assertIn('目标目录与模板工作区重叠，拒绝初始化',result.stderr)
                self.assertEqual(before,self.snapshot(base));self.assertFalse(list(base.glob('.*.init-*')))
    def test_external_initializer_and_force_backup_preserved(self):
        base,repo,src=self.template();target=base/'separate-project';self.init(src,target)
        marker=target/'keep.txt';marker.write_bytes(b'original bytes')
        self.init(src,target,force=True)
        backups=list(base.glob('separate-project.backup-*'))
        self.assertEqual(len(backups),1);self.assertEqual((backups[0]/'keep.txt').read_bytes(),b'original bytes')
        self.assertTrue((target/'.git').is_dir())
    def package_link(self,kind,junction=False):
        base=self.temp();src=base/'source';src.mkdir();(src/'VERSION').write_text('1.9.2\n',encoding='utf-8')
        target=base/'outside' if kind=='outside' else src/('.git' if kind=='excluded' else 'ordinary')
        target.mkdir();(target/'config').write_bytes(b'fixture configuration')
        link=src/'alias';self.link(link,target,directory=True,junction=junction)
        result=run([PYTHON,'-B',str(ROOT/'build_package.py'),'--source',str(src),'--output-dir',str(base/'output')],expect=1)
        self.assertIn('forbidden',result.stderr);self.assertFalse(list((base/'output').glob('*.zip')))
        self.assertEqual((target/'config').read_bytes(),b'fixture configuration')
    def test_package_outside_link(self):self.package_link('outside')
    def test_package_internal_link(self):self.package_link('inside')
    def test_package_excluded_alias(self):self.package_link('excluded')
    def test_package_windows_junction_alias(self):self.package_link('excluded',junction=True)
    def scaffold_link(self,junction=False):
        base,repo,src=self.template();external=base/'external';external.mkdir();(external/'leak.txt').write_bytes(b'not copied')
        self.link(src/'scaffold'/'alias',external,directory=True,junction=junction)
        result=self.init(src,base/'target',expect=1)
        self.assertIn('forbidden',result.stderr);self.assertFalse((base/'target').exists());self.assertFalse(list(base.glob('.target.init-*')))
        self.assertEqual((external/'leak.txt').read_bytes(),b'not copied')
    def test_scaffold_symlink(self):self.scaffold_link()
    def test_scaffold_windows_junction(self):self.scaffold_link(junction=True)
    def test_report_default_and_explicit_ci_path(self):
        base=self.temp();src=base/'current';src.mkdir();shutil.copyfile(ROOT/'run_tests.py',src/'run_tests.py')
        tests=src/'tests';tests.mkdir();(tests/'test_fixture.py').write_text('import unittest\nclass T(unittest.TestCase):\n def test_ok(self):self.assertTrue(True)\n',encoding='utf-8')
        run([PYTHON,'-B',str(src/'run_tests.py')],base)
        self.assertEqual(len(list((base/'validation/local-run').glob('run-*/summary.json'))),1)
        self.assertFalse((base/'current_validation').exists())
        run([PYTHON,'-B',str(src/'run_tests.py'),'--report-dir','../validation/ci'],src)
        self.assertEqual(len(list((base/'validation/ci').glob('run-*/summary.json'))),1)

    @unittest.skipUnless(os.name=='nt','Windows launcher runtime case only')
    def test_cmd_default_report_and_argument_forwarding(self):
        base=self.temp();src=base/'current';src.mkdir()
        for name in ['RUN_TESTS.cmd','run_tests.py']:shutil.copyfile(ROOT/name,src/name)
        tests=src/'tests';tests.mkdir();(tests/'test_fixture.py').write_text('import unittest\nclass T(unittest.TestCase):\n def test_ok(self):self.assertTrue(True)\n',encoding='utf-8')
        run(['cmd.exe','/d','/c',str(src/'RUN_TESTS.cmd')],base)
        self.assertEqual(len(list((base/'validation/local-run').glob('run-*/summary.json'))),1)
        self.assertFalse((base/'current_validation').exists())
        explicit=base/'validation/custom output'
        run(['cmd.exe','/d','/c',str(src/'RUN_TESTS.cmd'),'--report-dir',str(explicit)],base)
        self.assertEqual(len(list(explicit.glob('run-*/summary.json'))),1)

    def test_cli_direct_file_symlink_keeps_external_bytes(self):
        h=ProjectHarness(self,governance_mode='standard');h.start_batch()
        outside=h.root.parent/'outside.json';outside.write_bytes(b'{"unchanged":true}\n')
        self.link(h.root/'alias.json',outside)
        for cmd,flag in [('ai-register-change','--input'),('ai-start','--request'),('ai-finish','--result')]:
            h.tool(cmd,flag,'alias.json',expect=1)
            self.assertEqual(outside.read_bytes(),b'{"unchanged":true}\n')
    def test_package_file_alias_to_excluded_config(self):
        base=self.temp();src=base/'source';src.mkdir();(src/'VERSION').write_text('1.9.2\n',encoding='utf-8')
        (src/'.git').mkdir();secret=src/'.git/config';secret.write_bytes(b'private fixture')
        self.link(src/'public-config',secret)
        result=run([PYTHON,'-B',str(ROOT/'build_package.py'),'--source',str(src),'--output-dir',str(base/'output')],expect=1)
        self.assertIn('forbidden',result.stderr);self.assertEqual(secret.read_bytes(),b'private fixture')
        self.assertFalse(list((base/'output').glob('*.zip')))

    def test_valid_external_requests_never_read_or_consumed(self):
        for command,flag in [('ai-register-change','--input'),('ai-start','--request'),('ai-finish','--result')]:
            with self.subTest(command=command):
                h=ProjectHarness(self,governance_mode='standard')
                if command=='ai-register-change':
                    payload={'source':'development','origin_batch_id':'','raw_feedback':'Synthetic defect','change_types':['bug_fix'],'affected_implementation':[],'requires_reacceptance':False}
                elif command=='ai-start':
                    payload={'batch_id':'P1-001','stage_id':'P1','title':'Regression batch','goal':'Fixture','scope':['fixture'],'acceptance_criteria':['fixture']}
                else:
                    h.start_batch();payload=h.result_payload('blocked',[{'name':'fixture','status':'blocked','details':'pending'}],['pending'])
                outside=h.root.parent/'outside.json';write_json(outside,payload);before=outside.read_bytes()
                state=(h.root/'.ai/project_state.json').read_bytes()
                proc=h.tool(command,flag,'../outside.json',expect=1)
                self.assertIn('path',proc.stderr.lower());self.assertTrue(outside.exists());self.assertEqual(before,outside.read_bytes())
                self.assertEqual(state,(h.root/'.ai/project_state.json').read_bytes())
