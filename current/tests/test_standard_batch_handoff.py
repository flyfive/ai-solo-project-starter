"""Real initialized projects/CLI/state rereads; SH01-SH30 plus binding adversaries."""
import copy
import hashlib
import json
import os
import unittest
from test_regression import ProjectHarness, write_json

ACTIVE='.ai/runtime/active_batch.json'
MARKER='.ai/runtime/pending_batch_handoff.json'
STATE='.ai/project_state.json'
INPUT='.ai/runtime/batch_handoff.json'

class StandardBatchHandoffTests(unittest.TestCase):
    def read(self,h,path):return json.loads((h.root/path).read_text(encoding='utf-8'))
    def ref(self,h,path):return {'path':path,'sha256':hashlib.sha256((h.root/path).read_bytes()).hexdigest()}
    def fixture(self,status='blocked',mode='standard'):
        h=ProjectHarness(self,governance_mode=mode)
        h.start_batch()
        if status in {'blocked','partial'}:
            result=h.result_payload(status,[{'name':'synthetic observation','status':'blocked','details':'Unfinished fixture obligation'}],['Waiting for defined successor'])
            write_json(h.root/'.ai/runtime/batch_result.json',result);h.tool('ai-finish',expect=1)
        elif status in {'awaiting_acceptance','feedback_received'}:
            result=h.result_payload('pass',[{'name':'synthetic executed check','status':'pass','details':'Fixture result'}])
            result['manual_acceptance']='pending'
            write_json(h.root/'.ai/runtime/batch_result.json',result);h.tool('ai-finish',expect=1)
            if status=='feedback_received':
                write_json(h.root/'.ai/runtime/acceptance.json',{'scope':'batch','batch_id':'P1-001','status':'failed','note':'Observed unresolved condition'})
                h.tool('ai-acceptance',expect={0,1})
            self.assertEqual(self.read(h,ACTIVE)['status'],status)
        elif status!='active':
            a=self.read(h,ACTIVE);a['status']=status;write_json(h.root/ACTIVE,a) # malformed/guard-state injection only
        contract={'batch_id':'P1-002','stage_id':'P1','title':'Named successor','goal':'Complete outstanding fixture obligation',
                  'scope':['fixture responsibility'],'acceptance_criteria':['Verify remaining condition'],'status':'planned'}
        write_json(h.root/'docs/successor.json',contract)
        (h.root/'docs/owner.txt').write_text('Owner authorizes P1-001 responsibility handoff only to P1-002; no acceptance.',encoding='utf-8')
        request={'actor_role':'project_manager_agent','source_batch_id':'P1-001','successor_batch_id':'P1-002',
          'reason':'Preserve non-success and transfer remaining duty','unfinished_work':['Remaining fixture condition'],
          'transferred_obligations':['Retain evidence and obtain acceptance'],
          'successor_contract':{**self.ref(h,'docs/successor.json'),'successor_batch_id':'P1-002'},
          'owner_authorization':{'source_batch_id':'P1-001','successor_batch_id':'P1-002','granted':True,
                                 'source_ref':self.ref(h,'docs/owner.txt'),'note':'Explicit bound owner approval'}}
        return h,request
    def handoff(self,h,r,expect=0,env=None):
        write_json(h.root/INPUT,r);return h.tool('ai-handoff-batch',expect=expect,env=env)
    def start(self,h,batch_id='P1-002',expect=0,env=None):
        request=self.read(h,'docs/successor.json');request['batch_id']=batch_id
        write_json(h.root/'.ai/runtime/batch_request.json',request)
        return h.tool('ai-start',expect=expect,env=env)
    def record(self,h):return self.read(h,self.read(h,MARKER)['record_path'])
    def snapshot(self,h):
        return {p.relative_to(h.root).as_posix():p.read_bytes() for folder in ['.ai','docs'] for p in (h.root/folder).rglob('*') if p.is_file()}
    def rejected(self,h,r):
        before=(h.root/ACTIVE).read_bytes() if (h.root/ACTIVE).exists() else None
        output=self.handoff(h,r,expect=1)
        self.assertEqual(before,(h.root/ACTIVE).read_bytes() if (h.root/ACTIVE).exists() else None)
        self.assertTrue((h.root/INPUT).exists());return output
    def test_SH01_blocked(self):
        h,r=self.fixture();self.handoff(h,r)
        self.assertFalse((h.root/ACTIVE).exists());self.assertFalse((h.root/INPUT).exists())
        self.assertEqual(self.record(h)['status'],'handed_off')
    def test_SH02_partial(self):
        h,r=self.fixture('partial');self.handoff(h,r);self.assertEqual(self.record(h)['source_status'],'partial')
    def test_SH03_active_rejected(self):
        h,r=self.fixture('active');self.rejected(h,r)
    def test_SH04_awaiting_acceptance_rejected(self):
        h,r=self.fixture('awaiting_acceptance');self.rejected(h,r)
    def test_SH05_feedback_received_rejected(self):
        h,r=self.fixture('feedback_received');self.rejected(h,r)
    def test_SH06_pass_rejected(self):
        h,r=self.fixture('pass');self.rejected(h,r)
    def test_SH07_lite_rejected_promotion_unchanged(self):
        h,r=self.fixture(mode='lite');self.rejected(h,r)
        write_json(h.root/'.ai/runtime/governance_suspension.json',{'actor_role':'project_manager_agent','owner_authorization':True,
          'owner_note':'Owner permits promotion','reason':'Formal design required','unfinished_work':['Fixture work'],
          'test_status':'blocked','resume_after_promotion':True})
        h.tool('ai-suspend-for-promotion');self.assertTrue((h.root/'.ai/runtime/suspended_batch_for_promotion.json').exists())
    def test_SH08_no_active(self):
        h,r=self.fixture();(h.root/ACTIVE).unlink();self.rejected(h,r)
    def test_SH09_source_mismatch(self):
        h,r=self.fixture();r['source_batch_id']='wrong';self.rejected(h,r)
    def test_SH10_same_successor(self):
        h,r=self.fixture();r['successor_batch_id']='P1-001';r['successor_contract']['successor_batch_id']='P1-001';self.rejected(h,r)
    def test_SH11_missing_contract(self):
        h,r=self.fixture();(h.root/'docs/successor.json').unlink();self.rejected(h,r)
    def test_SH12_bad_sha(self):
        h,r=self.fixture();r['successor_contract']['sha256']='0'*64;self.rejected(h,r)
    def test_SH13_identity_mismatch(self):
        h,r=self.fixture();c=self.read(h,'docs/successor.json');c['batch_id']='other';write_json(h.root/'docs/successor.json',c)
        r['successor_contract'].update(self.ref(h,'docs/successor.json'));self.rejected(h,r)
    def test_SH14_open_changes(self):
        h,r=self.fixture();h.register_ready_bug_change()
        self.assertIn('STANDARD_BATCH_HANDOFF_OPEN_CHANGES_BLOCKED',self.rejected(h,r).stderr)
    def test_SH15_requirement_acceptance_unchanged(self):
        h,r=self.fixture();before=(h.root/'.ai/requirement_registry.json').read_bytes();self.handoff(h,r)
        self.assertEqual(before,(h.root/'.ai/requirement_registry.json').read_bytes())
    def test_SH16_stage_unchanged(self):
        h,r=self.fixture();before=self.read(h,STATE)['stage_acceptance'];self.handoff(h,r)
        self.assertEqual(before,self.read(h,STATE)['stage_acceptance']);self.assertNotEqual(before['status'],'passed')
    def test_SH17_last_closed_unchanged(self):
        h,r=self.fixture();before=self.read(h,STATE)['last_closed_batch'];self.handoff(h,r)
        self.assertEqual(before,self.read(h,STATE)['last_closed_batch'])
    def test_SH18_source_facts_retained(self):
        h,r=self.fixture();before=(h.root/ACTIVE).read_bytes();self.handoff(h,r);record=self.record(h)
        source=h.root/self.read(h,MARKER)['record_path'];source=source.with_name('source_active.json')
        self.assertEqual(source.read_bytes(),before);self.assertEqual(record['source_status'],'blocked')
        self.assertEqual(record['source_active_snapshot_sha256'],hashlib.sha256(before).hexdigest())
    def rollback_handoff(self,point):
        h,r=self.fixture();write_json(h.root/INPUT,r);before=self.snapshot(h)
        self.handoff(h,r,expect=1,env={**os.environ,'AI_STARTER_TEST_FAIL_BATCH_HANDOFF_AFTER':str(point)})
        self.assertEqual(before,self.snapshot(h))
    def test_SH19_first_write_rollback(self):self.rollback_handoff(1)
    def test_SH20_middle_write_rollback(self):self.rollback_handoff(6)
    def test_SH21_named_lock(self):
        h,r=self.fixture();self.handoff(h,r);out=self.start(h,'P1-003',expect=1)
        self.assertIn('named successor is pending',out.stderr);self.assertTrue((h.root/MARKER).exists())
    def test_SH22_successor_starts(self):
        h,r=self.fixture();self.handoff(h,r);self.start(h);a=self.read(h,ACTIVE)
        self.assertEqual(a['batch_id'],'P1-002');self.assertEqual(a['status'],'active')
        self.assertEqual(a['inherited_handoff']['transferred_obligations'],r['transferred_obligations'])
        for key in ['manual_acceptance','manager_review','release_approval']:self.assertNotIn(key,a)
    def test_SH23_contract_drift(self):
        h,r=self.fixture();self.handoff(h,r);p=h.root/'docs/successor.json';p.write_bytes(p.read_bytes()+b'\n')
        self.start(h,expect=1);self.assertTrue((h.root/MARKER).exists())
    def test_SH24_start_rollback(self):
        h,r=self.fixture();self.handoff(h,r)
        write_json(h.root/'.ai/runtime/batch_request.json',self.read(h,'docs/successor.json'));before=self.snapshot(h)
        self.start(h,expect=1,env={**os.environ,'AI_STARTER_TEST_FAIL_HANDOFF_START_AFTER':'5'})
        self.assertEqual(before,self.snapshot(h));self.assertEqual(self.record(h)['activation_status'],'pending_successor')
    def test_SH25_consumed_durable(self):
        h,r=self.fixture();self.handoff(h,r);path=self.read(h,MARKER)['record_path'];before=self.read(h,path);self.start(h)
        self.assertFalse((h.root/MARKER).exists());after=self.read(h,path)
        self.assertEqual(after['activation_status'],'consumed');self.assertEqual(after['consumed_by_batch_id'],'P1-002')
        self.assertTrue(after['consumed_at'])
        state=self.read(h,STATE);digest=hashlib.sha256((h.root/path).read_bytes()).hexdigest()
        self.assertEqual(state['last_handed_off_batch']['record_sha256'],digest)
        self.assertEqual(state['handoff_history'][-1]['record_sha256'],digest)
        for key in before:
            if key not in {'activation_status','consumed_at','consumed_by_batch_id'}:self.assertEqual(before[key],after[key])
    def test_SH26_repeat_source_rejected(self):
        h,r=self.fixture();self.handoff(h,r);self.handoff(h,r,expect=1)
    def test_SH27_repeat_consumption_rejected(self):
        h,r=self.fixture();self.handoff(h,r);self.start(h);before=(h.root/ACTIVE).read_bytes()
        self.start(h,expect=1);self.assertEqual(before,(h.root/ACTIVE).read_bytes())
    def test_SH28_pending_not_overwritten(self):
        h,r=self.fixture();self.handoff(h,r);before=(h.root/MARKER).read_bytes();r['successor_batch_id']='P1-003'
        self.handoff(h,r,expect=1);self.assertEqual(before,(h.root/MARKER).read_bytes())
    def test_SH29_resume_successor(self):
        h,r=self.fixture();self.handoff(h,r);m=json.loads(h.tool('ai-resume','--json',expect={0,1}).stdout)
        self.assertEqual(m['priority'],'start_handoff_successor');self.assertIn('P1-002',m['next_step'])
        self.assertFalse(m['metrics']['cold_history_loaded'])
        for path in ['docs/PROJECT_MEMORY.md','.ai/runtime/HANDOFF_CURRENT.md','docs/CURRENT_STATE.md']:
            self.assertIn('P1-002',(h.root/path).read_text(encoding='utf-8'))
    def test_SH30_health_missing_record(self):
        h,r=self.fixture();self.handoff(h,r);(h.root/self.read(h,MARKER)['record_path']).unlink()
        report=json.loads(h.tool('health','--json',expect=2).stdout)
        self.assertTrue(any('HANDOFF' in x for x in report['fail']))
    def test_authorization_requires_bound_object(self):
        h,r=self.fixture()
        for auth in [True,{**r['owner_authorization'],'granted':False},{**r['owner_authorization'],'successor_batch_id':'wrong'},
                     {**r['owner_authorization'],'source_ref':{'path':'../outside','sha256':'0'*64}}]:
            bad=copy.deepcopy(r);bad['owner_authorization']=auth;self.rejected(h,bad)
    def test_contract_path_and_planned_status(self):
        h,r=self.fixture();bad=copy.deepcopy(r);bad['successor_contract']['path']='../outside';self.rejected(h,bad)
        c=self.read(h,'docs/successor.json');c['status']='active';write_json(h.root/'docs/successor.json',c)
        r['successor_contract'].update(self.ref(h,'docs/successor.json'));self.rejected(h,r)
    def test_request_cannot_change_frozen_scope(self):
        h,r=self.fixture();self.handoff(h,r);req=self.read(h,'docs/successor.json');req['goal']='Unrelated goal'
        write_json(h.root/'.ai/runtime/batch_request.json',req);h.tool('ai-start',expect=1)
        self.assertTrue((h.root/MARKER).exists())
    def test_missing_marker_and_consumed_marker_detected(self):
        h,r=self.fixture();self.handoff(h,r);marker=self.read(h,MARKER)
        (h.root/MARKER).unlink();h.tool('health','--json',expect=2);self.start(h,expect=1)
        write_json(h.root/MARKER,marker);self.start(h);write_json(h.root/MARKER,marker)
        h.tool('health','--json',expect=2)
    def test_final_write_rollbacks(self):
        self.rollback_handoff(12)
        h,r=self.fixture();self.handoff(h,r);write_json(h.root/'.ai/runtime/batch_request.json',self.read(h,'docs/successor.json'))
        before=self.snapshot(h);self.start(h,expect=1,env={**os.environ,'AI_STARTER_TEST_FAIL_HANDOFF_START_AFTER':'11'})
        self.assertEqual(before,self.snapshot(h))
    def test_cli_help(self):
        h=ProjectHarness(self,governance_mode='lite');text=h.tool('ai-handoff-batch','--help').stdout
        for token in ['Standard only','BLOCKED/PARTIAL','owner-authorized','not PASS','--input']:self.assertIn(token,text)
