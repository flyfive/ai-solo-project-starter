"""Public entry static checks plus actual initializer preservation checks."""
import re
import shutil
import json
import os
import unittest
from pathlib import Path
from test_regression import PYTHON, ROOT, STARTER, ProjectHarness, make_temp_dir, remove_tree, run

class PublicReadinessTests(unittest.TestCase):
    def test_public_document_links_do_not_require_private_reports(self):
        files=[ROOT.parent/'README.md',ROOT.parent/'START_HERE.md',ROOT/'README.md',ROOT/'QUICK_START.md',ROOT/'LICENSE_STATUS.md']
        for path in files:
            text=path.read_text('utf-8')
            for target in re.findall(r'\]\(([^)]+)\)',text):
                if target.startswith(('https://','http://','#')):continue
                self.assertNotIn('maintenance/',target)
                self.assertNotIn('validation/',target)
                self.assertTrue((path.parent/target.split('#')[0]).exists(),(path.name,target))

    def test_author_example_is_labeled_and_empty_target_stays_unset(self):
        html=(ROOT/'使用说明.html').read_text('utf-8')
        self.assertIn('placeholder 仅为作者示例',html)
        field=re.search(r'<input id="targetPath"[^>]*>',html).group()
        self.assertNotIn('value=',field)
        self.assertIn('执行前必须核对上述模板目录在本机存在',html)
        self.assertIn('未填写或不正确时先更正',html)

    def test_existing_license_is_not_overwritten_by_initialization(self):
        base=make_temp_dir('public-license-');self.addCleanup(remove_tree,base)
        target=base/'existing';target.mkdir();license_path=target/'LICENSE'
        license_path.write_text('Existing owner license fixture\n',encoding='utf-8')
        before=license_path.read_bytes()
        run([PYTHON,'-B',str(STARTER),'init','--target',str(target),'--name','License fixture','--description','Preserve existing license','--profile','generic','--governance-mode','lite'],expect=2)
        self.assertEqual(license_path.read_bytes(),before)
        self.assertEqual({p.name for p in target.iterdir()},{'LICENSE'})

    def test_first_standard_takeover_keeps_git_clean(self):
        h=ProjectHarness(self,governance_mode='standard')
        self.assertEqual(run(['git','status','--porcelain'],h.root).stdout,'')
        h.tool('ai-resume','--json',expect={0,1})
        self.assertEqual(run(['git','status','--porcelain'],h.root).stdout,'')

    def test_mit_license_copies_and_template_scope(self):
        license_text=(ROOT/'LICENSE').read_text('utf-8')
        self.assertEqual((ROOT.parent/'LICENSE').read_text('utf-8'),license_text)
        self.assertIn('Copyright (c) 2026 FeiXiaorong',license_text)
        self.assertIn('Permission is hereby granted, free of charge',license_text)
        notice=(ROOT/'scaffold/NOTICE.template.txt').read_text('utf-8')
        self.assertTrue(notice.endswith(license_text))
        self.assertIn('does not license your new business code',notice)
        self.assertIn('third-party',notice)

    def test_both_modes_retain_template_notice_without_business_license(self):
        for mode in ['lite','standard']:
            h=ProjectHarness(self,governance_mode=mode)
            self.assertEqual((h.root/'NOTICE.template.txt').read_bytes(),(ROOT/'scaffold/NOTICE.template.txt').read_bytes())
            self.assertFalse((h.root/'LICENSE').exists())
            for path in ['tools/project.py','tools/context_engine.py','.githooks/pre-commit']:
                text=(h.root/path).read_text('utf-8')
                self.assertIn('SPDX-License-Identifier: MIT',text)
                self.assertIn('FeiXiaorong',text)
                self.assertIn('NOTICE.template.txt',text)
            self.assertEqual(json.loads(h.tool('health','--json',expect={0,1}).stdout)['fail'],[])
            h.tool('ai-resume','--json',expect={0,1})
            self.assertEqual(run(['git','status','--porcelain'],h.root).stdout,'')

    def test_current_only_distribution_carries_license_into_project(self):
        base=make_temp_dir('current-only-license-');self.addCleanup(remove_tree,base)
        template=base/'template only';template.mkdir()
        for name in ['starter.py','path_safety.py','profiles.toml','LICENSE','LICENSE_STATUS.md']:
            shutil.copy2(ROOT/name,template/name)
        shutil.copytree(ROOT/'scaffold',template/'scaffold')
        target=base/'new project'
        run([PYTHON,'-B',str(template/'starter.py'),'init','--target',str(target),'--name','License fixture','--description','Current-only initialization fixture','--profile','generic','--governance-mode','lite'])
        self.assertTrue((target/'NOTICE.template.txt').read_text('utf-8').endswith((template/'LICENSE').read_text('utf-8')))
        self.assertFalse((target/'LICENSE').exists())

    def test_workflow_runner_context_is_step_scoped_and_config_is_shared(self):
        # Narrow checks for this workflow's known layout, not a general YAML parser.
        text=(ROOT.parent/'.github/workflows/regression.yml').read_text('utf-8')
        job_env=text.split('    env:\n',1)[1].split('    steps:\n',1)[0]
        self.assertNotIn('runner.',job_env)
        self.assertNotIn('GIT_CONFIG_GLOBAL:',job_env)
        prepare=text.split('      - name: Check runner Git and installed test dependencies\n',1)[1].split('      - name:',1)[0]
        regression=text.split('      - name: Run isolated regression\n',1)[1]
        setting='          GIT_CONFIG_GLOBAL: ${{ runner.temp }}/template-test.gitconfig'
        self.assertIn(setting,prepare)
        self.assertIn(setting,regression)
        self.assertEqual(text.count(setting),2)
        self.assertIn('python -B run_tests.py --report-dir ../validation/ci',regression)
        self.assertNotIn('continue-on-error',text)
        self.assertIn('fail-fast: false',text)
        self.assertIn("os: [ubuntu-latest, windows-latest]",text)
        self.assertIn("python-version: ['3.11', '3.14']",text)
        base=make_temp_dir('ci-env-');self.addCleanup(remove_tree,base)
        path=base/'template-test.gitconfig'
        env=os.environ.copy();env['GIT_CONFIG_GLOBAL']=str(path)
        match=re.search(r'python -c "([^"\n]+)"',prepare)
        self.assertIsNotNone(match)
        run([PYTHON,'-c',match.group(1)],env=env)
        # A real child process using the regression step's same environment, no full suite.
        output=run([PYTHON,'-c',"import os,pathlib; p=pathlib.Path(os.environ['GIT_CONFIG_GLOBAL']); assert p.read_bytes()==b''; print(p)"] ,env=env)
        self.assertEqual(output.stdout.strip(),str(path))

    def test_workflow_is_at_root_with_no_publish_or_log_upload(self):
        # Configuration text check, not a remote CI execution claim.
        text=(ROOT.parent/'.github/workflows/regression.yml').read_text('utf-8')
        for required in ['working-directory: current','contents: read','persist-credentials: false','actions/setup-python@v7','actions/setup-node@v7','node-version:', '--report-dir ../validation/ci']:
            self.assertIn(required,text)
        for forbidden in ['--global','upload-artifact','contents: write','pull_request_target']:
            self.assertNotIn(forbidden,text)

if __name__=='__main__': unittest.main()
