import copy
import json
import unittest
from test_regression import ProjectHarness, PYTHON, write_json

class LightweightTests(unittest.TestCase):
    def project(self, mode='lite'):
        return ProjectHarness(self, governance_mode=mode)

    def contract(self, **extra):
        return {'kind':'small_change', 'work_type':'fix', 'risk_reason':'One local deterministic behavior, no authorization or data changes',
                'unchanged_behaviors':['Stored data and public interface'], 'reference_paths':['tools/project.py'], **extra}

    def start(self,h,expect=0,**extra):
        payload={'batch_id':'P1-001','stage_id':'P1','title':'Regression batch','goal':'Repair one behavior',
                 'scope':['src/one.py'],'acceptance_criteria':['Selected condition'], 'task_contract':self.contract(), **extra}
        write_json(h.root/'.ai/runtime/batch_request.json',payload)
        return h.tool('ai-start',expect=expect)

    def active(self,h):
        return json.loads((h.root/'.ai/runtime/active_batch.json').read_text('utf-8'))

    def checkpoint(self,h, hypothesis='Current hypothesis'):
        path=h.root/'docs/evidence/observation.txt'; path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists(): path.write_text('Actual diagnostic fixture observation',encoding='utf-8')
        return {'symptom':'Original visible failure','expected':'Expected visible result','reproduction':'not_reproduced',
                'hypothesis':hypothesis,'eliminated':[{'cause':'Earlier guess','evidence_refs':['docs/evidence/observation.txt']}],
                'evidence_refs':['docs/evidence/observation.txt'],'next_check':'Inspect the input boundary','root_cause_status':'unknown'}

    def evidence(self,h):
        write_json(h.root/'.ai/runtime/evidence_request.json',{'actor_role':'code_executor','action':'run','level':'L1',
            'execution_authorized':True,'argv':[PYTHON,'-B','-c',"from pathlib import Path; assert Path('PROJECT.toml').is_file(); print('fixture checked')"]})
        return json.loads(h.tool('ai-evidence').stdout)['summary']

    def result(self,h,status='pass',**extra):
        result=h.result_payload(status,[{'name':'ordinary tests','status':'pass','details':'fixture'}],['Investigation pending'] if status!='pass' else [])
        result.update(extra); write_json(h.root/'.ai/runtime/batch_result.json',result)
        return result

    def checks(self,ev):
        return {key:{'status':'pass','evidence':ev,'details':'Executed fixture for this declared check'} for key in ['Selected condition','original_symptom']}

    def test_investigation_does_not_create_implementation_batch(self):
        h=self.project(); before=(h.root/'.ai/requirement_registry.json').read_bytes()
        r=self.start(h,expect=1,task_contract=self.contract(kind='investigation'))
        self.assertIn('investigation',r.stderr)
        self.assertFalse((h.root/'.ai/runtime/active_batch.json').exists())
        self.assertEqual(before,(h.root/'.ai/requirement_registry.json').read_bytes())

    def test_small_task_records_scope_without_new_planning_files(self):
        h=self.project(); files={p.relative_to(h.root).as_posix() for p in h.root.rglob('*') if p.is_file() and '.git' not in p.parts}
        self.start(h); a=self.active(h)
        self.assertEqual(a['task_contract']['kind'],'small_change')
        self.assertEqual(a['acceptance_criteria'],['Selected condition'])
        self.assertEqual(a['task_contract']['reference_paths'],['tools/project.py'])
        after={p.relative_to(h.root).as_posix() for p in h.root.rglob('*') if p.is_file() and '.git' not in p.parts}
        self.assertLessEqual(after-files,{'.ai/runtime/active_batch.json'})

    def test_small_task_cannot_hide_high_risk_or_bypass_existing_block(self):
        h=self.project()
        for extra in [{'risk_level':'high'},{'risk_tags':['migration']},{'requires_user_authorization':True,'authorization_granted':False}]:
            self.start(h,expect=1,**extra); self.assertFalse((h.root/'.ai/runtime/active_batch.json').exists())
        self.start(h); old=self.active(h); self.start(h,expect=1); self.assertEqual(old,self.active(h))

    def test_invalid_reference_rejected_and_no_reference_reason_supported(self):
        h=self.project()
        for path in ['missing.py','../outside.py']:
            self.start(h,expect=1,task_contract=self.contract(reference_paths=[path]))
        self.start(h,expect=1,task_contract=self.contract(reference_paths=[]))
        self.start(h,task_contract=self.contract(reference_paths=[],no_reference_reason='New isolated entry; no matching implementation'))
        self.assertEqual(self.active(h)['task_contract']['reference_paths'],[])

    def test_formal_context_still_overrides_reference_implementation(self):
        h=self.project('standard'); self.start(h,context_refs={'architecture':['C03']})
        path=h.root/'docs/ARCHITECTURE.md'; path.write_text(path.read_text('utf-8').replace('## C03 | 技术栈', '## C03 | 技术栈\n\nChanged selected formal rule.'),encoding='utf-8')
        self.result(h); self.assertIn('stale',h.tool('ai-finish',expect=1).stderr)
        self.assertIn('先遵守正式需求和架构', (h.root/'AGENTS.md').read_text('utf-8'))  # Rule-text check only.

    def test_interrupted_debug_restores_only_latest_checkpoint(self):
        h=self.project(); self.start(h)
        for status,hypothesis in [('partial','Old long attempt '+('old-trace '*200)),('blocked','Latest input hypothesis')]:
            self.result(h,status,debug_checkpoint=self.checkpoint(h,hypothesis)); h.tool('ai-finish',expect=1)
        a=self.active(h); self.assertEqual(a['debug_checkpoint']['hypothesis'],'Latest input hypothesis')
        manifest=json.loads(h.tool('ai-resume','--json',expect={0,1}).stdout)
        self.assertEqual(manifest['active_batch']['debug_checkpoint']['next_check'],'Inspect the input boundary')
        self.assertEqual(manifest['next_step'],'Inspect the input boundary')
        self.assertNotIn('old-trace',json.dumps(manifest))
        self.assertFalse(manifest['metrics']['cold_history_loaded'])
        handoff=(h.root/'.ai/runtime/HANDOFF_CURRENT.md').read_text('utf-8'); self.assertIn('Latest input hypothesis',handoff)
        attempts=list((h.root/'.ai/history/batches').rglob('*.json')); self.assertGreaterEqual(len(attempts),2)
        self.assertTrue(any('Old long attempt' in p.read_text('utf-8') for p in attempts))

    def test_invalid_checkpoint_does_not_change_active_state(self):
        h=self.project(); self.start(h); old=self.active(h); cp=self.checkpoint(h); cp['eliminated'][0]['evidence_refs']=['missing.log']
        self.result(h,'partial',debug_checkpoint=cp); h.tool('ai-finish',expect=1); self.assertEqual(old,self.active(h))
        cp=self.checkpoint(h); cp['root_cause_status']='confirmed'; cp['reproduction']='environment_blocked'
        self.result(h,'partial',debug_checkpoint=cp); h.tool('ai-finish',expect=1); self.assertEqual(old,self.active(h))

    def test_passing_tests_do_not_replace_symptom_or_selected_conditions(self):
        h=self.project(); self.start(h); ev=self.evidence(h)
        for checks in [{}, {'Selected condition':self.checks(ev)['Selected condition']},
                       {**self.checks(ev),'original_symptom':{'status':'not_run','reason':'Cannot reproduce'}}]:
            self.result(h,evidence_refs=[ev],checks=checks); h.tool('ai-finish',expect=1)
            self.assertTrue((h.root/'.ai/runtime/active_batch.json').exists())
        self.result(h,checks=self.checks(ev)); h.tool('ai-finish',expect={0,1})
        self.assertFalse((h.root/'.ai/runtime/active_batch.json').exists())

    def test_tampered_evidence_cannot_verify_scoped_goals(self):
        h=self.project(); self.start(h); ev=self.evidence(h)
        evidence=json.loads((h.root/ev).read_text('utf-8')); (h.root/evidence['raw'][0]['path']).write_text('tampered',encoding='utf-8')
        self.result(h,checks=self.checks(ev)); self.assertIn('evidence',h.tool('ai-finish',expect=1).stderr.lower())

    def test_feature_requires_entry_wiring_and_does_not_forge_manual_acceptance(self):
        h=self.project(); self.start(h,task_contract=self.contract(work_type='feature')); ev=self.evidence(h)
        checks={'Selected condition':self.checks(ev)['Selected condition']}
        self.result(h,checks=checks); h.tool('ai-finish',expect=1)
        checks['entry_wiring']={'status':'pass','evidence':ev,'details':'Fixture verifies real entry connection'}
        self.result(h,checks=checks,manual_acceptance='passed'); h.tool('ai-finish',expect=1)
        self.result(h,checks=checks,manual_acceptance='pending'); h.tool('ai-finish',expect=1)
        self.assertEqual(self.active(h)['status'],'awaiting_acceptance')
        submitted=json.loads((h.root/'.ai/runtime/submitted_result.json').read_text('utf-8'))
        self.assertEqual(submitted['manual_acceptance'],'pending')

    def test_verified_debug_checkpoint_survives_pending_manual_acceptance(self):
        h=self.project(); self.start(h)
        self.result(h,'partial',debug_checkpoint=self.checkpoint(h,'Initial unconfirmed hypothesis'))
        h.tool('ai-finish',expect=1)
        checkpoint=self.checkpoint(h,'Latest reproduced hypothesis'); checkpoint['reproduction']='reproduced'
        ev=self.evidence(h)
        self.result(h,checks=self.checks(ev),debug_checkpoint=checkpoint,manual_acceptance='pending')
        h.tool('ai-finish',expect=1)
        self.assertEqual(self.active(h)['status'],'awaiting_acceptance')
        self.assertEqual(self.active(h)['debug_checkpoint']['hypothesis'],'Latest reproduced hypothesis')
        manifest=json.loads(h.tool('ai-resume','--json',expect={0,1}).stdout)
        self.assertNotEqual(manifest['next_step'],'Inspect the input boundary')
        write_json(h.root/'.ai/runtime/acceptance.json', {'batch_id':'P1-001','scope':'batch','status':'passed','note':'Explicit owner fixture confirmation'})
        h.tool('ai-acceptance',expect={0,1})
        self.assertFalse((h.root/'.ai/runtime/active_batch.json').exists())

    def test_daily_rules_and_checkpoint_are_not_duplicated(self):
        h=self.project(); self.start(h)
        manifest=json.loads(h.tool('ai-resume','--json',expect={0,1}).stdout)
        self.assertNotIn('debug_checkpoint',manifest['active_batch'])
        self.assertFalse(manifest['metrics']['cold_history_loaded'])
        self.assertNotIn('README.md',manifest['reading_plan']['must_read'])
        # Rule-text assertions: daily rules route details, rather than repeating the schema.
        rules=(h.root/'AGENTS.md').read_text('utf-8')
        self.assertNotIn('status=pass/fail/not_run',rules)
        self.assertNotIn('root_cause_evidence',rules)
        self.assertIn('任务字段与结束核对',rules)
        self.assertIn('## 排错字段', (h.root/'README.md').read_text('utf-8'))
        self.result(h,'partial',debug_checkpoint=self.checkpoint(h,'Unique checkpoint hypothesis'))
        h.tool('ai-finish',expect=1)
        manifest=json.loads(h.tool('ai-resume','--json',expect={0,1}).stdout)
        self.assertEqual(manifest['active_batch']['debug_checkpoint']['hypothesis'],'Unique checkpoint hypothesis')
        state=(h.root/'docs/CURRENT_STATE.md').read_text('utf-8')
        self.assertNotIn('Unique checkpoint hypothesis',state)
        self.assertNotIn('Earlier guess',state)
        self.assertIn('active_batch.debug_checkpoint',state)
        handoff=(h.root/'.ai/runtime/HANDOFF_CURRENT.md').read_text('utf-8')
        self.assertIn('Unique checkpoint hypothesis',handoff)
        self.assertNotIn('Earlier guess',handoff)

    def test_checkpoint_evidence_tampering_blocks_hook(self):
        h=self.project(); self.start(h)
        self.result(h,'partial',debug_checkpoint=self.checkpoint(h)); h.tool('ai-finish',expect=1)
        (h.root/'docs/evidence/observation.txt').write_text('changed observation',encoding='utf-8')
        self.assertIn('Checkpoint evidence changed',h.tool('pre-commit-check',expect=2).stdout)

    def test_small_task_cannot_bypass_captured_change(self):
        h=self.project('standard')
        write_json(h.root/'.ai/runtime/change_request.json', {'source':'user_feedback','raw_feedback':'Behavior must change',
                    'change_types':['bug_fix'],'affected_implementation':[],'requires_reacceptance':True})
        h.tool('ai-register-change')
        self.start(h,expect=1); self.assertFalse((h.root/'.ai/runtime/active_batch.json').exists())
        manifest=json.loads(h.tool('ai-resume','--json',expect=2).stdout)
        self.assertEqual(manifest['priority'],'complete_document_writeback')

    def test_unrelated_requirement_conditions_are_not_added_to_batch_checks(self):
        h=self.project()
        write_json(h.root/'.ai/runtime/requirement_update.json', {'actor_role':'project_manager_agent','action':'create',
            'title':'Broader requirement','description':'Contains another condition outside this batch','status':'active',
            'acceptance_criteria':[{'description':'Selected condition','method':'automatic','status':'pending'},
                                   {'description':'Deferred condition','method':'manual','status':'pending'}]})
        h.tool('ai-requirement')
        self.start(h,context_refs={'requirements':['R-001']}); ev=self.evidence(h)
        self.result(h,checks=self.checks(ev),evidence_refs=[ev]); h.tool('ai-finish',expect={0,1})
        self.assertFalse((h.root/'.ai/runtime/active_batch.json').exists())
        registry=json.loads((h.root/'.ai/requirement_registry.json').read_text('utf-8'))
        self.assertIn('pending',json.dumps(registry))

    def test_legacy_input_keeps_contract_without_claiming_new_checks(self):
        h=self.project(); h.start_batch(); self.assertFalse(self.active(h).get('task_contract'))
        self.result(h); h.tool('ai-finish',expect={0,1})
        self.assertFalse((h.root/'.ai/runtime/active_batch.json').exists())
        latest=json.loads((h.root/'.ai/runtime/latest_summary.json').read_text('utf-8'))
        self.assertNotEqual(latest.get('goal_verification'),'pass')

if __name__=='__main__': unittest.main()
