"""Real initialized projects/CLI/subprocess evidence; no simulated browser claims."""
import copy
import hashlib
import json
import os
import sys
import unittest
from pathlib import Path
from test_regression import ProjectHarness, PYTHON, write_json, run

HARNESS = r"""import json, os, pathlib, subprocess, sys
c=json.loads(pathlib.Path(os.environ['AI_ACCEPTANCE_CONTRACT']).read_text('utf-8'))
r=pathlib.Path(os.environ['AI_EVIDENCE_DIR'])
p=subprocess.run([sys.executable, c['candidate']['entrypoint']], capture_output=True)
(r/'candidate.log').write_bytes(p.stdout+p.stderr)
rows=[]
for item in c['coverage']:
 rows.append(dict(item, evidence_kind='runtime', actual_evidence=['candidate.log'], status='pass' if p.returncode==0 else 'fail'))
(r/'runtime-result.json').write_text(json.dumps({'candidate_runtime_status':'PASS' if p.returncode==0 else 'FAIL','coverage':rows}), encoding='utf-8')
"""

class AcceptanceHardeningTests(unittest.TestCase):
    def fixture(self, mode='lite', harness=HARNESS):
        h=ProjectHarness(self, governance_mode=mode)
        (h.root/'candidate.py').write_text("print('actual candidate output')\n",encoding='utf-8')
        (h.root/'harness.py').write_text(harness,encoding='utf-8')
        def entry(name):
            return {'path':name,'sha256':hashlib.sha256((h.root/name).read_bytes()).hexdigest()}
        exe=str(Path(PYTHON).resolve())
        c={'schema':'acceptance/1','revision':'AC-1','approval_id':'fixture-approval',
           'authorization':{'granted':True,'note':'Isolated local fixture execution'},
           'candidate':{'revision':'candidate-1','files':[entry('candidate.py')], 'entrypoint':'candidate.py','capabilities':['basic']},
           'harness':{'revision':'harness-1','files':[entry('harness.py')], 'entrypoint':'harness.py',
                      'executable':exe,'executable_sha256':hashlib.sha256(Path(exe).read_bytes()).hexdigest(),
                      'supported_schema':['acceptance/1'],'argv':[exe,'harness.py']},
           'required_capabilities':['basic'],'participants':['worker'], 'timeout_seconds':20,
           'acceptance_rule_version':'rules-1','coverage':[{'criterion_id':'G1','requirement':'Actual output',
             'required_evidence_kind':'runtime','actual_entrypoint':'candidate.py','actual_participants':['worker']} ]}
        return h,c

    def evidence(self,h,c,run='run-1',action='run',expect=0,**extra):
        write_json(h.root/'.ai/runtime/evidence_request.json',{'actor_role':'code_executor','level':'L3',
          'action':action,'run_id':run,'acceptance_contract':c, **extra})
        proc=h.tool('ai-evidence',expect=expect)
        return json.loads(proc.stdout) if proc.stdout.strip().startswith('{') else proc.stderr

    def read(self,h,ref):
        return json.loads((h.root/ref).read_text('utf-8'))

    def test_t1_run_id_independent_of_candidate(self):
        h,c=self.fixture(); before=(h.root/'candidate.py').read_bytes()
        a=self.evidence(h,c); b=self.evidence(h,c,'run-2')
        self.assertEqual(a['candidate_source_hash'],b['candidate_source_hash'])
        self.assertEqual(a['acceptance_contract_hash'],b['acceptance_contract_hash'])
        self.assertNotEqual(a['evidence_run_id'],b['evidence_run_id'])
        self.assertEqual(before,(h.root/'candidate.py').read_bytes())

    def test_t2_contract_revision_creates_new_run_keeps_old_failure(self):
        h,c=self.fixture(harness=HARNESS.replace("evidence_kind='runtime'","evidence_kind='model'"))
        a=self.evidence(h,c,expect=1); raw=(h.root/a['summary']).read_bytes()
        c['revision']='AC-2'; c['coverage'][0]['required_evidence_kind']='model'
        b=self.evidence(h,c,'run-2')
        self.assertEqual(a['candidate_source_hash'],b['candidate_source_hash'])
        self.assertNotEqual(a['acceptance_contract_hash'],b['acceptance_contract_hash'])
        self.assertEqual(raw,(h.root/a['summary']).read_bytes())
        self.assertEqual(self.read(h,a['summary'])['status'],'fail')

    def test_t3_directory_mtime_is_audit_only(self):
        h,c=self.fixture(); a=self.evidence(h,c)
        os.utime(h.root,(1000000000,1000000000))
        b=self.evidence(h,c,'run-2',action='preflight')
        self.assertEqual(a['candidate_source_hash'],b['candidate_source_hash'])
        self.assertEqual(b['status'],'ready')

    def test_t4_changed_candidate_stales_evidence(self):
        h,c=self.fixture(); a=self.evidence(h,c)
        (h.root/'candidate.py').write_text("print('changed')\n",encoding='utf-8')
        b=self.evidence(h,c,action='audit',summary=a['summary'],expect=1)
        self.assertEqual(b['failure_class'],'EVIDENCE_INSUFFICIENT')
        self.assertIn('identity',b['reason'].lower())

    def test_t5_model_and_static_cannot_close_runtime(self):
        for kind in ['model','static']:
            h,c=self.fixture(harness=HARNESS.replace("evidence_kind='runtime'",f"evidence_kind='{kind}'"))
            a=self.evidence(h,c,expect=1)
            self.assertEqual(a['failure_class'],'EVIDENCE_INSUFFICIENT')
            self.assertEqual(a['candidate_runtime_status'],'PASS')

    def test_t6_runtime_evidence_covers_criterion(self):
        h,c=self.fixture(); a=self.evidence(h,c)
        summary=self.read(h,a['summary']); self.assertEqual(summary['coverage'][0]['status'],'pass')
        self.assertEqual(summary['coverage'][0]['evidence_kind'],'runtime')
        self.assertTrue(summary['raw']); self.assertEqual(a['candidate_runtime_status'],'PASS')

    def test_t7_harness_failure_is_not_candidate_failure(self):
        h,c=self.fixture(harness="raise ImportError('fixture scanner unavailable')\n")
        a=self.evidence(h,c,expect=1)
        self.assertEqual(a['failure_class'],'HARNESS_FAILURE')
        # A started harness without a final report cannot prove candidate absence.
        self.assertEqual(a['candidate_runtime_status'],'UNKNOWN')

    def test_t8_auditor_failure_cannot_change_runtime(self):
        h,c=self.fixture(); a=self.evidence(h,c)
        raw=h.root/'docs/evidence/run-1/runtime.json'; before=raw.read_bytes()
        b=self.evidence(h,c,action='audit',summary=a['summary'], auditor_error='fixture auditor TypeError',expect=1)
        self.assertEqual(b['failure_class'],'AUDITOR_FAILURE')
        self.assertEqual(raw.read_bytes(),before)
        self.assertEqual(self.read(h,a['summary'])['status'],'pass')

    def test_t9_preflight_incompatible_does_not_execute(self):
        h,c=self.fixture(); c['required_capabilities']=['new-capability']
        a=self.evidence(h,c,action='preflight',expect=1)
        self.assertEqual(a['compatibility'],'requires_candidate_change')
        self.assertFalse((h.root/'docs/evidence/run-1').exists())
        self.assertEqual(a['candidate_runtime_status'],'NOT_RUN')

    def investigation(self,h,data,expect=0):
        write_json(h.root/'.ai/runtime/investigation_request.json',data)
        proc=h.tool('ai-context','investigation',expect=expect)
        return json.loads(proc.stdout)

    def test_t10_stop_loss_blocks_next_run_and_start(self):
        h,c=self.fixture()
        self.investigation(h,{'action':'start','actor_role':'project_manager_agent','investigation_id':'I1',
          'risk_level':'high','max_iterations':1,'scope_expansion_forbidden':True})
        self.evidence(h,c)
        state=self.read(h,'.ai/runtime/investigation.json')
        self.assertEqual(state['status'],'blocked'); self.assertTrue(state['owner_decision_required'])
        rejected=self.evidence(h,c,'run-2',expect=1)
        self.assertIn('OWNER',str(rejected))
        write_json(h.root/'.ai/runtime/batch_request.json',{})
        self.assertIn('OWNER',h.tool('ai-start',expect=1).stderr)
        manifest=json.loads(h.tool('ai-resume','--json',expect={0,1}).stdout)
        self.assertTrue(manifest['investigation']['owner_decision_required'])
        self.assertNotIn('attempts',manifest['investigation'])

    def test_t11_scope_expansion_persists_owner_block(self):
        h,c=self.fixture()
        a=self.investigation(h,{'action':'scope','actor_role':'project_manager_agent',
           'scope_expansion':['native_helper'],'reason':'New fixture infrastructure'},expect=1)
        self.assertEqual(a['reason_code'],'OWNER_SCOPE_DECISION_REQUIRED')
        self.assertIn('OWNER',str(self.evidence(h,c,expect=1)))

    def test_t12_old_request_path_remains_usable_without_new_assurances(self):
        h=ProjectHarness(self,governance_mode='lite'); h.start_batch()
        write_json(h.root/'.ai/runtime/evidence_request.json',{'actor_role':'code_executor','action':'run','level':'L1',
          'execution_authorized':True,'argv':[PYTHON,'-c',"print('legacy')"]})
        result=json.loads(h.tool('ai-evidence').stdout)
        self.assertNotIn('candidate_revision',self.read(h,result['summary']))

    def test_t13_run_directory_never_reused_even_after_fail(self):
        h,c=self.fixture(harness="raise RuntimeError('failed gate')\n")
        a=self.evidence(h,c,expect=1); before=(h.root/a['summary']).read_bytes()
        self.evidence(h,c,expect=1)
        self.assertEqual(before,(h.root/a['summary']).read_bytes())

    def test_t14_independent_identities_and_harness_change(self):
        h,c=self.fixture(); a=self.evidence(h,c)
        c['harness']['revision']='harness-2'; c['revision']='AC-2'
        b=self.evidence(h,c,'run-2'); s=self.read(h,b['summary'])
        for key in ['candidate_revision','candidate_source_hash','acceptance_contract_revision',
                    'acceptance_contract_hash','harness_revision','evidence_run_id']:
            self.assertIn(key,s)
        self.assertEqual(a['candidate_source_hash'],b['candidate_source_hash'])
        self.assertEqual(s['harness_revision'],'harness-2')

    def test_t15_modes_health_and_context_remain_valid(self):
        for mode in ['lite','standard']:
            h,c=self.fixture(mode); self.evidence(h,c)
            self.assertFalse(json.loads(h.tool('health','--json',expect={0,1}).stdout)['fail'])
            h.tool('ai-resume','--json',expect={0,1})

    def test_invalid_path_and_missing_authorization_preflight_reject(self):
        h,c=self.fixture(); c['authorization']['granted']=False
        a=self.evidence(h,c,action='preflight',expect=1)
        self.assertNotEqual(a['status'],'ready')
        c['authorization']['granted']=True; c['candidate']['files'][0]['path']='../escape'
        self.evidence(h,c,action='preflight',expect=1)
        self.assertFalse((h.root/'docs/evidence/run-1').exists())

    def test_plain_boolean_or_missing_raw_is_not_runtime_coverage(self):
        for text in ["{'G1':True}","[dict(c['coverage'][0],evidence_kind='runtime',status='pass',actual_evidence=[])]"]:
            body=HARNESS[:HARNESS.index('p=subprocess.run')]+f"(r/'runtime-result.json').write_text(json.dumps({{'candidate_runtime_status':'PASS','coverage':{text}}}),encoding='utf-8')\n"
            h,c=self.fixture(harness=body)
            expected='HARNESS_FAILURE' if text == "{'G1':True}" else 'EVIDENCE_INSUFFICIENT'
            self.assertEqual(self.evidence(h,c,expect=1)['failure_class'],expected)

    def test_high_risk_investigation_requires_stop_loss(self):
        h,c=self.fixture()
        write_json(h.root/'.ai/runtime/investigation_request.json',{'action':'start','actor_role':'project_manager_agent',
           'investigation_id':'I1','risk_level':'high'})
        self.assertIn('stop-loss',h.tool('ai-context','investigation',expect=1).stderr)


    def test_owner_extension_retains_counters_and_needs_real_authorization_record(self):
        h,c=self.fixture()
        self.investigation(h,{'action':'start','actor_role':'project_manager_agent','investigation_id':'I1','max_iterations':1})
        self.evidence(h,c)
        (h.root/'owner.txt').write_text('Fixture owner permits one more isolated attempt',encoding='utf-8')
        req={'action':'owner-decision','actor_role':'code_executor','owner_authorization':True,'decision':'continue',
             'reason':'fixture extension','decision_evidence':'owner.txt','max_iterations':2}
        write_json(h.root/'.ai/runtime/investigation_request.json',req)
        self.assertIn('project_owner',h.tool('ai-context','investigation',expect=1).stderr)
        req['actor_role']='project_owner';self.investigation(h,req)
        self.assertEqual(self.read(h,'.ai/runtime/investigation.json')['iterations'],1)
        self.evidence(h,c,'run-2')
        self.assertTrue(self.read(h,'.ai/runtime/investigation.json')['owner_decision_required'])

    def test_latest_checkpoint_only_survives_takeover(self):
        h,c=self.fixture()
        self.investigation(h,{'action':'start','actor_role':'project_manager_agent','investigation_id':'I1','max_iterations':4})
        (h.root/'attempt.log').write_text('observed fixture output',encoding='utf-8')
        cp={'symptom':'observed','expected':'expected','hypothesis':'old hypothesis','next_check':'old check',
            'evidence_refs':['attempt.log'],'eliminated':[{'cause':'excluded cause','evidence_refs':['attempt.log']}]}
        for hypothesis in ['old hypothesis','latest hypothesis']:
            cp['hypothesis']=hypothesis
            self.investigation(h,{'action':'record','actor_role':'analysis_review_agent','debug_checkpoint':cp})
        m=json.loads(h.tool('ai-resume','--json',expect={0,1}).stdout)
        self.assertEqual(m['investigation']['debug_checkpoint']['hypothesis'],'latest hypothesis')
        self.assertNotIn('old hypothesis',json.dumps(m))
        self.assertGreaterEqual(len(list((h.root/'.ai/history/investigations').glob('*.json'))),3)

    def test_contract_batch_finish_rejects_old_contract_pass_after_revision(self):
        h,c=self.fixture();write_json(h.root/'contract.json',c)
        request={'batch_id':'P1-001','stage_id':'P1','title':'Regression batch','goal':'fixture',
                 'scope':['candidate.py'],'acceptance_criteria':['G1'],'acceptance_contract':'contract.json','required_test_level':'L3'}
        write_json(h.root/'.ai/runtime/batch_request.json',request);h.tool('ai-start')
        a=self.evidence(h,c)
        c['revision']='AC-2';write_json(h.root/'contract.json',c)
        h.tool('ai-context','refresh','--accept-changes','--actor-role','project_manager_agent','--reason','Auditor-only contract revision')
        payload=h.result_payload('pass',[{'name':'runtime','status':'pass','details':'actual captured output'}])
        payload['evidence_refs']=[a['summary']]
        write_json(h.root/'.ai/runtime/batch_result.json',payload)
        self.assertIn('contract',h.tool('ai-finish',expect=1).stderr)
        b=self.evidence(h,c,'run-2');payload['evidence_refs']=[b['summary']]
        write_json(h.root/'.ai/runtime/batch_result.json',payload)
        h.tool('ai-finish',expect={0,1})
        self.assertFalse((h.root/'.ai/runtime/active_batch.json').exists())

    def test_legacy_batch_cannot_use_narrow_candidate_to_bypass_old_fingerprint(self):
        h,c=self.fixture();h.start_batch()
        rejection=self.evidence(h,c,expect=1)
        self.assertIn('Bind the acceptance contract',str(rejection))

    def test_raw_tampering_and_manual_claim_do_not_pass(self):
        h,c=self.fixture();a=self.evidence(h,c)
        (h.root/'docs/evidence/run-1/candidate.log').write_text('tampered',encoding='utf-8')
        self.assertEqual(self.evidence(h,c,action='audit',summary=a['summary'],expect=1)['failure_class'],'EVIDENCE_INSUFFICIENT')
        h,c=self.fixture(harness=HARNESS.replace("evidence_kind='runtime'","evidence_kind='manual'"))
        c['coverage'][0]['required_evidence_kind']='manual'
        self.assertEqual(self.evidence(h,c,expect=1)['failure_class'],'EVIDENCE_INSUFFICIENT')

    def test_candidate_failure_and_environment_failure_are_distinct(self):
        h,c=self.fixture();(h.root/'candidate.py').write_text("print('original failure');raise SystemExit(1)\n",encoding='utf-8')
        c['candidate']['files'][0]['sha256']=hashlib.sha256((h.root/'candidate.py').read_bytes()).hexdigest()
        a=self.evidence(h,c,expect=1)
        self.assertEqual(a['failure_class'],'CANDIDATE_FAILURE');self.assertEqual(a['candidate_runtime_status'],'FAIL')
        h,c=self.fixture(harness="import time;time.sleep(3)\n");c['timeout_seconds']=1
        a=self.evidence(h,c,expect=1);self.assertEqual(a['failure_class'],'ENVIRONMENT_BLOCKED')
        before=(h.root/a['summary']).read_bytes();self.evidence(h,c,expect=1)
        self.assertEqual(before,(h.root/a['summary']).read_bytes())

    def test_compatibility_preflight_all_outcomes_and_no_side_effects(self):
        h,c=self.fixture()
        before={x.relative_to(h.root).as_posix():x.read_bytes() for x in h.root.rglob('*') if x.is_file() and '.git' not in x.parts and x.name!='evidence_request.json'}
        self.assertEqual(self.evidence(h,c,action='preflight')['compatibility'],'compatible_without_candidate_change')
        c['harness']['supported_schema']=[]
        self.assertEqual(self.evidence(h,c,action='preflight',expect=1)['compatibility'],'requires_harness_change')
        c['compatibility_decision']='incompatible'
        self.assertEqual(self.evidence(h,c,action='preflight',expect=1)['compatibility'],'incompatible')
        after={x.relative_to(h.root).as_posix():x.read_bytes() for x in h.root.rglob('*') if x.is_file() and '.git' not in x.parts and x.name!='evidence_request.json'}
        self.assertEqual(before,after)

    def test_explicit_volatile_gate_requires_reason_and_enforces_value(self):
        h,c=self.fixture();(h.root/'volatile').mkdir()
        c['volatile_identity']=[{'path':'volatile','field':'directory_mtime_ns','expected':0}]
        self.assertNotEqual(self.evidence(h,c,action='preflight',expect=1)['status'],'ready')
        c['volatile_identity'][0].update(reason='Fixture explicit identity policy',expected=(h.root/'volatile').stat().st_mtime_ns)
        self.evidence(h,c,action='preflight')
        os.utime(h.root/'volatile',(1000000000,1000000000))
        self.evidence(h,c,action='preflight',expect=1)

    def test_missing_coverage_is_rejected_before_batch_start(self):
        h,c=self.fixture();write_json(h.root/'contract.json',c)
        write_json(h.root/'.ai/runtime/batch_request.json',{'batch_id':'P1-001','stage_id':'P1','title':'Regression batch',
             'goal':'fixture','scope':['candidate.py'],'acceptance_criteria':['G1','G2'],'acceptance_contract':'contract.json'})
        self.assertIn('Coverage map',h.tool('ai-start',expect=1).stderr)
        self.assertFalse((h.root/'.ai/runtime/active_batch.json').exists())


    def test_actual_auditor_exception_preserves_completed_runtime(self):
        h,c=self.fixture();a=self.evidence(h,c)
        raw=h.root/'docs/evidence/run-1/runtime.json';before=raw.read_bytes()
        write_json(h.root/'.ai/runtime/evidence_request.json',{'actor_role':'integration_reviewer','action':'audit',
          'level':'L3','acceptance_contract':c,'summary':a['summary']})
        script="import sys;sys.path.insert(0,'tools');import project;context_engine,_=project.context_extension();defect=lambda *a:(_ for _ in ()).throw(TypeError('fixture auditor bug'));context_engine.read_runtime_audit=defect;sys.argv=['project.py','ai-evidence'];raise SystemExit(project.main())"
        result=json.loads(run([PYTHON,'-B','-c',script],h.root,expect=1).stdout)
        self.assertEqual(result['failure_class'],'AUDITOR_FAILURE')
        self.assertEqual(result['candidate_runtime_status'],'PASS')
        self.assertEqual(raw.read_bytes(),before)

    def test_contract_is_not_raw_execution_proof(self):
        h,c=self.fixture(harness=HARNESS.replace("actual_evidence=['candidate.log']","actual_evidence=['contract.json']"))
        self.assertEqual(self.evidence(h,c,expect=1)['failure_class'],'EVIDENCE_INSUFFICIENT')

    def test_candidate_revision_and_failed_gate_limits(self):
        for boundary in ['max_candidate_revisions','max_failed_gates']:
            h,c=self.fixture(harness="raise ImportError('fixture unavailable scanner')\n")
            self.investigation(h,{'action':'start','actor_role':'project_manager_agent','investigation_id':'I1',boundary:1})
            self.evidence(h,c,expect=1)
            state=self.read(h,'.ai/runtime/investigation.json')
            self.assertTrue(state['owner_decision_required'])
            self.assertEqual(state['failed_gates'],1)
            self.assertEqual(len(state['candidate_hashes']),1)

    def test_scope_approval_does_not_allow_unapproved_different_scope(self):
        h,c=self.fixture()
        self.investigation(h,{'action':'scope','actor_role':'project_manager_agent','scope_expansion':['new_service'],'reason':'fixture'},expect=1)
        (h.root/'owner.txt').write_text('Fixture owner approved new_service',encoding='utf-8')
        self.investigation(h,{'action':'owner-decision','actor_role':'project_owner','owner_authorization':True,
          'decision':'continue','reason':'fixture','decision_evidence':'owner.txt','approved_scope_expansion':['new_service']})
        req={'batch_id':'P1-001','stage_id':'P1','title':'Regression batch','goal':'fixture','scope':['candidate.py'],
             'acceptance_criteria':['G1'],'scope_expansion':['new_database']}
        write_json(h.root/'.ai/runtime/batch_request.json',req)
        self.assertIn('OWNER_SCOPE_DECISION_REQUIRED',h.tool('ai-start',expect=1).stderr)


    def test_audit_cannot_map_old_pass_to_new_contract_or_run(self):
        h,c=self.fixture();a=self.evidence(h,c)
        original=(h.root/a['summary']).read_bytes()
        c['revision']='AC-2'
        result=self.evidence(h,c,action='audit',summary=a['summary'],expect=1)
        self.assertEqual(result['failure_class'],'CONTRACT_INCOMPATIBLE')
        c['revision']='AC-1'
        result=self.evidence(h,c,run='different-run',action='audit',summary=a['summary'],expect=1)
        self.assertEqual(result['failure_class'],'CONTRACT_INCOMPATIBLE')
        self.assertEqual(original,(h.root/a['summary']).read_bytes())
        self.assertTrue(self.read(h,'.ai/project_state.json')['layered_test_contract'])


    def review_start(self, h, c):
        write_json(h.root/'contract.json', c)
        write_json(h.root/'.ai/runtime/batch_request.json', {'batch_id':'P1-001','stage_id':'P1',
          'title':'Regression batch','goal':'Audit recovery','scope':['candidate.py'],
          'acceptance_criteria':['G1'],'acceptance_contract':'contract.json','required_test_level':'L3'})
        h.tool('ai-start')

    def review_broken_auditor(self, h, c, action='run', summary=None):
        request={'actor_role':'integration_reviewer','action':action,'level':'L3','run_id':'run-1','acceptance_contract':c}
        if summary: request['summary']=summary
        write_json(h.root/'.ai/runtime/evidence_request.json',request)
        script="import sys;sys.path.insert(0,'tools');import project;e,_=project.context_extension();e.read_runtime_audit=lambda *a:(_ for _ in ()).throw(TypeError('actual injected auditor defect'));sys.argv=['project.py','ai-evidence'];raise SystemExit(project.main())"
        return json.loads(run([PYTHON,'-B','-c',script],h.root,expect=1).stdout)

    def review_finish(self,h,ref,expect=1):
        result=h.result_payload('pass',[{'name':'captured runtime','status':'pass','details':'Original captured runtime, appended audit'}])
        result['evidence_refs']=[ref]
        write_json(h.root/'.ai/runtime/batch_result.json',result)
        return h.tool('ai-finish',expect=expect)

    def test_review_initial_auditor_failure_reaudit_finishes_without_rerun(self):
        for mode in ['lite','standard']:
            counter="counter=pathlib.Path('harness-count.txt');counter.write_text(str(int(counter.read_text())+1) if counter.exists() else '1')\n"
            h,c=self.fixture(mode,harness=HARNESS.replace('p=subprocess.run',counter+'p=subprocess.run'))
            self.review_start(h,c)
            first=self.review_broken_auditor(h,c)
            self.assertEqual(first['failure_class'],'AUDITOR_FAILURE')
            self.assertEqual(first['candidate_runtime_status'],'PASS')
            self.review_finish(h,first['summary'])
            failed_audit=self.review_broken_auditor(h,c,'audit',first['summary'])
            run_dir=h.root/'docs/evidence/run-1'
            originals={p:p.read_bytes() for p in run_dir.rglob('*') if p.is_file()}
            originals.update({h.root/name:(h.root/name).read_bytes() for name in ['candidate.py','harness.py','contract.json']})
            success=self.evidence(h,c,action='audit',summary=first['summary'])
            self.assertIn('summary',success,'Reaudit must return consumable evidence, not only an audit note')
            summary=self.read(h,success['summary'])
            self.assertEqual(summary['status'],'pass')
            self.assertEqual(summary['evidence_run_id'],'run-1')
            self.assertEqual(summary['origin_summary'],first['summary'])
            self.review_finish(h,success['summary'],expect={0,1})
            self.assertFalse((h.root/'.ai/runtime/active_batch.json').exists())
            self.assertEqual((h.root/'harness-count.txt').read_text(),'1')
            for path,content in originals.items():self.assertEqual(path.read_bytes(),content,str(path))

    def test_review_reaudit_binding_and_failed_audit_cannot_close(self):
        h,c=self.fixture();self.review_start(h,c)
        first=self.review_broken_auditor(h,c)
        failed=self.review_broken_auditor(h,c,'audit',first['summary'])
        self.assertIn('summary',failed)
        self.review_finish(h,failed['summary'])
        good=self.evidence(h,c,action='audit',summary=first['summary'])
        payload=self.read(h,good['summary'])
        for field in ['origin_summary_sha256','audit_sha256','runtime_sha256','identity','raw']:
            forged=copy.deepcopy(payload);del forged[field]
            ref='docs/evidence/run-1/summary-audit-forged.json';write_json(h.root/ref,forged)
            self.review_finish(h,ref)
            self.assertTrue((h.root/'.ai/runtime/active_batch.json').exists())
        (h.root/payload['audit_record']).write_text('{}',encoding='utf-8')
        self.review_finish(h,good['summary'])

    def test_review_tampered_original_blocks_reaudit(self):
        h,c=self.fixture();first=self.review_broken_auditor(h,c)
        (h.root/'docs/evidence/run-1/candidate.log').write_text('tampered raw',encoding='utf-8')
        bad=self.evidence(h,c,action='audit',summary=first['summary'],expect=1)
        self.assertEqual(bad['failure_class'],'EVIDENCE_INSUFFICIENT')
        self.assertEqual(self.read(h,first['summary'])['failure_class'],'AUDITOR_FAILURE')

    def test_review_candidate_ran_before_report_crash_is_unknown_and_retained(self):
        body=HARNESS[:HARNESS.index('rows=[]')]+"raise RuntimeError('harness crashed after observable candidate output')\n"
        h,c=self.fixture(harness=body)
        result=self.evidence(h,c,expect=1)
        self.assertIn('actual candidate output',(h.root/'docs/evidence/run-1/candidate.log').read_text())
        self.assertEqual(result['candidate_runtime_status'],'UNKNOWN')
        self.assertEqual(result['failure_class'],'HARNESS_FAILURE')
        raw=self.read(h,result['summary'])['raw']
        self.assertIn('docs/evidence/run-1/candidate.log',{x['path'] for x in raw})
        self.assertFalse(any(x['path'].endswith('runtime-result.json') for x in raw))

    def test_review_explicit_candidate_failure_exit_one_is_not_harness_failure(self):
        body=HARNESS.replace("'coverage':rows","'coverage':rows,'harness_status':'completed'")+"raise SystemExit(p.returncode)\n"
        h,c=self.fixture(harness=body)
        (h.root/'candidate.py').write_text("print('observable failed check');raise SystemExit(1)\n",encoding='utf-8')
        c['candidate']['files'][0]['sha256']=hashlib.sha256((h.root/'candidate.py').read_bytes()).hexdigest()
        result=self.evidence(h,c,expect=1)
        self.assertEqual(result['candidate_runtime_status'],'FAIL')
        self.assertEqual(result['failure_class'],'CANDIDATE_FAILURE')

    def test_review_conflicting_exit_and_damaged_report_are_facility_failures(self):
        bodies=[HARNESS+"raise SystemExit(1)\n",
                HARNESS[:HARNESS.index('rows=[]')]+"(r/'runtime-result.json').write_text('{broken',encoding='utf-8')\n",
                HARNESS+"(r/'runtime-result.json').write_text('{broken',encoding='utf-8');raise SystemExit(2)\n"]
        for body in bodies:
            h,c=self.fixture(harness=body);result=self.evidence(h,c,expect=1)
            self.assertEqual(result['failure_class'],'HARNESS_FAILURE')
            self.assertEqual(result['candidate_runtime_status'],'UNKNOWN')
            raw={x['path'] for x in self.read(h,result['summary'])['raw']}
            self.assertIn('docs/evidence/run-1/candidate.log',raw)
            self.assertIn('docs/evidence/run-1/runtime-result.json',raw)

    def test_review_facility_error_cannot_be_overridden_by_candidate_declaration(self):
        body=HARNESS.replace("'coverage':rows","'coverage':rows,'failure_class':'CANDIDATE_FAILURE'")+"raise SystemExit(2)\n"
        h,c=self.fixture(harness=body);result=self.evidence(h,c,expect=1)
        self.assertEqual(result['failure_class'],'HARNESS_FAILURE')
        stored=self.read(h,'docs/evidence/run-1/runtime.json')
        self.assertEqual(stored['report']['failure_class'],'CANDIDATE_FAILURE')
        self.assertEqual(stored['exit_code'],2)

    def test_review_not_run_needs_pre_spawn_or_recorded_setup_evidence(self):
        body=HARNESS[:HARNESS.index('p=subprocess.run')]+"(r/'setup.log').write_text('dependency preparation failed; candidate was not started',encoding='utf-8')\n(r/'runtime-result.json').write_text(json.dumps({'candidate_runtime_status':'NOT_RUN','harness_status':'failed','not_run_evidence':['setup.log'],'coverage':[]}),encoding='utf-8')\nraise SystemExit(2)\n"
        h,c=self.fixture(harness=body);result=self.evidence(h,c,expect=1)
        self.assertEqual(result['candidate_runtime_status'],'NOT_RUN')
        raw={x['path'] for x in self.read(h,result['summary'])['raw']}
        self.assertIn('docs/evidence/run-1/setup.log',raw)
        h,c=self.fixture(harness=body.replace("'not_run_evidence':['setup.log'],",''))
        self.assertEqual(self.evidence(h,c,expect=1)['candidate_runtime_status'],'UNKNOWN')


    def test_review_runtime_and_origin_summary_tampering_rejected(self):
        for name in ['runtime.json','summary.json']:
            h,c=self.fixture();self.review_start(h,c)
            first=self.review_broken_auditor(h,c)
            good=self.evidence(h,c,action='audit',summary=first['summary'])
            path=h.root/'docs/evidence/run-1'/name
            path.write_bytes(path.read_bytes()+b'\n')
            self.review_finish(h,good['summary'])
            self.assertTrue((h.root/'.ai/runtime/active_batch.json').exists())

    def test_review_malformed_failure_class_is_preserved_as_facility_failure(self):
        body=HARNESS.replace("'coverage':rows","'coverage':rows,'failure_class':[]")
        h,c=self.fixture(harness=body);result=self.evidence(h,c,expect=1)
        self.assertEqual(result['candidate_runtime_status'],'UNKNOWN')
        self.assertEqual(result['failure_class'],'HARNESS_FAILURE')
        self.assertEqual(self.read(h,'docs/evidence/run-1/runtime.json')['report']['failure_class'],[])
