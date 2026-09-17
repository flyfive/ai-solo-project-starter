"""Page-script regression using Node's simulated DOM, not browser/OS clipboard tests.
Run with python -B -m unittest -v test_page_prompts from tests.
Node comes from PATH or AI_STARTER_TEST_NODE; no npm packages are required.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
STANDARD = """1. 只有状态为 ready 的正式交付物才能验收和结案；
2. 项目所有者验收后，如果交付物或交付文档发生变化，必须重新验收；
3. 项目结案后不得修改交付清单；继续开发必须由项目所有者明确授权并使用更高版本重开。"""
SCRIPT = r"""
const fs=require('fs'),vm=require('vm');
const html=fs.readFileSync(process.argv[1],'utf8');
const code=html.match(/<script>([\s\S]*?)<\/script>/)[1];
const elements={}; let selected='',copied=''; const listeners={};
for(const match of html.matchAll(/<(?:input|select|textarea|span)\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
 const id=match[1],value=(match[0].match(/\bvalue="([^"]*)"/)||[])[1]||'';
 elements[id]={value,textContent:'',focus(){},select(){selected=id},addEventListener(event,fn){listeners[id]=fn}};
}
elements.projectName.value='示例'; elements.description.value='测试描述'; elements.targetPath.value='E:\\sample'; elements.profile.value='generic';
const context=vm.createContext({document:{getElementById:id=>elements[id],execCommand:()=>{copied=elements[selected].value;return true}},navigator:{clipboard:{writeText:async t=>{copied=t}}},window:{isSecureContext:true,getSelection:()=>({removeAllRanges(){}})},setTimeout(){}});
const results=[];
(async()=>{
for(const mode of ['lite','standard','auto']) {
 elements.governanceMode.value=mode;
 for(const path of [html.match(/id="templatePath" value="([^"]*)"/)[1],'  ',' E:\\custom-template ',process.argv[2]]) {
 elements.templatePath.value=path;
 if(results.length) listeners.governanceMode(); else vm.runInContext(code,context);
 const copies=[];
 for(const secure of [true,false]) for(const [prompt,status] of [['initPrompt','initStatus'],['startPrompt','startStatus']]) {
 context.window.isSecureContext=secure; await vm.runInContext(`copyPrompt('${prompt}','${status}')`,context);
 copies.push({prompt,secure,value:copied,status:elements[status].textContent});
 }
 results.push({mode,path,init:elements.initPrompt.value,start:elements.startPrompt.value,copies});
 }
}
console.log(JSON.stringify(results));
})().catch(e=>{console.error(e);process.exitCode=1});
"""

class PagePromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = os.environ.get('AI_STARTER_TEST_NODE') or shutil.which('node')
        if not node:
            raise RuntimeError('Node required: set AI_STARTER_TEST_NODE or add Node to PATH; page tests were not run')
        result = subprocess.run([node, '-e', SCRIPT, str(ROOT/'使用说明.html'), str(ROOT)], capture_output=True, text=True, encoding='utf-8', timeout=30)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.rows = json.loads(result.stdout)

    def prompt(self, mode):
        return next(r['start'] for r in self.rows if r['mode']==mode)

    def test_lite_has_lightweight_acceptance_without_delivery_gates(self):
        text=self.prompt('lite')
        for forbidden in ['发布基线','正式交付','结案','重开']:
            self.assertNotIn(forbidden,text)
        for required in ['需求基线','测试','人工验收','状态','历史']:
            self.assertIn(required,text)

    def test_standard_preserves_all_existing_delivery_rules(self):
        self.assertIn(STANDARD,self.prompt('standard'))

    def test_auto_uses_persisted_mode_and_guards_standard_rules(self):
        text=self.prompt('auto')
        for required in ['先读取新项目 PROJECT.toml','[governance].mode','初始化后实际落地','不凭项目描述重新猜测','Auto 不是第三种治理模式','实际模式为 Lite','不得套用 Standard 交付纪律','仅当实际模式为 Standard']:
            self.assertIn(required,text)
        self.assertIn(STANDARD,text)
        self.assertLess(text.index('仅当实际模式为 Standard'),text.index(STANDARD))

    def test_common_takeover_flow_is_retained(self):
        for row in self.rows:
            with self.subTest(mode=row['mode'],path=row['path']):
                for phrase in ['START_HERE.md','PROJECT.toml','当前状态与活动批次manifest','按R/C/DEC引用加载相关正式正文与AC','不默认全文读取','先建立或确认需求基线，不要立即开始写代码','项目持久文档']:
                    self.assertIn(phrase,row['start'])

    def test_initialization_and_paths_remain_unchanged(self):
        modes={'lite':'lite，极简治理','standard':'standard，标准治理','auto':'auto，由 AI 根据项目描述建议并说明理由；客户交付、权限、敏感数据、支付、迁移、生产部署、多平台或硬件必须建议 Standard'}
        for row in self.rows:
            path=row['path'].strip() or r'D:\project\AI_Solo_Project_Starter\current'
            with self.subTest(mode=row['mode'],path=path):
                self.assertIn('模板目录：'+path,row['init'])
                self.assertIn('治理模式：'+modes[row['mode']],row['init'])
                for phrase in ['项目名称：示例','项目简介与最终交付目标：测试描述',r'目标目录：E:\sample','项目类型：generic','初始化必须完成 Git 仓库、初始提交、Git Hook 和健康检查']:
                    self.assertIn(phrase,row['init'])
                self.assertEqual(self.rows[0]['path'],r'D:\project\AI_Solo_Project_Starter\current')

    def test_actual_checkout_path_is_preserved(self):
        rows=[r for r in self.rows if r['path']==str(ROOT)]
        self.assertEqual({r['mode'] for r in rows},{'lite','standard','auto'})
        for row in rows:
            self.assertIn('模板目录：'+str(ROOT),row['init'])

    def test_both_copy_buttons_keep_generated_content(self):
        html=(ROOT/'使用说明.html').read_text('utf-8')
        for prompt,status in [('initPrompt','initStatus'),('startPrompt','startStatus')]:
            self.assertIn(f"copyPrompt('{prompt}', '{status}')",html)
        for row in self.rows:
            self.assertEqual(len(row['copies']),4)
            for copy in row['copies']:
                self.assertEqual(copy['value'],row['init' if copy['prompt']=='initPrompt' else 'start'])
                self.assertEqual(copy['status'],'已复制')

if __name__=='__main__':
    unittest.main()
