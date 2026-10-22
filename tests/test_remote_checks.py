import copy
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uia_core import common, remote_checks as remote

class RemoteChecksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); (self.base/'remote-checks').mkdir()
        saved = dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=70)
        self.check = {'id':'check1', 'case_id':'C', 'assertion_id':'A2','expected':'2. 原始完整期望。',
                      'url':'http://example.test/file.txt','method':'GET','saved_at':saved.isoformat(),
                      'earliest_check_at':(saved+dt.timedelta(hours=1)).isoformat(),
                      'deadline':(saved+dt.timedelta(hours=2)).isoformat(), 'timeout_ms':10000,
                      'conditions':[{'op':'contains','value':'new value'}]}
        self.m = {'run_id':'R', 'config':{'execution':{'stability_passes':1}}, 'history':[],
                  'cases':{'C':{'version':'v','attempts':[{'batch_id':'b','version':'v','result':'passed',
                               'setup_verified':True,'cleanup_verified':True}]}},
                  'remote_checks':{'check1':{'request':self.check,'version':'v','batch_id':'b','status':'pending','history':[]}}}
        self.request = self.base/'remote-checks/request.json'
        common.atomic_write(self.request, {'schema_version':'uia-remote-request.v1','run_id':'R','checks':[self.check]})
    def payload(self, status='pass'):
        return {'schema_version':'uia-remote-results.v1','run_id':'R', 'request_sha256':common.file_hash(self.request),
                'results':[{'id':'check1','checked_at':common.now(),'status':status,'http_status':200 if status!='unreachable' else None,
                            'conditions':[True] if status=='pass' else [False] if status!='unreachable' else [],
                            'reason':{'pass':'conditions_met','fail':'conditions_mismatch','still-cached':'cache_window','unreachable':'network'}[status]}]}
    def ingest(self, payload):
        f=self.base/'fake-results.json'; common.atomic_write(f,payload); return remote.ingest(self.base,self.m,f)
    def test_pass_requires_local_and_remote_and_is_idempotent(self):
        payload=self.payload(); self.assertEqual(self.ingest(payload)['cases']['C'],'passed')
        self.assertEqual(self.m['cases']['C']['stability'],'stable')
        self.assertTrue(self.ingest(payload)['duplicate'])
        self.assertEqual(len(self.m['remote_checks']['check1']['history']),1)
    def test_fail_is_business_failure(self):
        self.assertEqual(self.ingest(self.payload('fail'))['cases']['C'],'business_failure')
    def test_unreachable_is_pending_not_pass_or_human_wait(self):
        self.assertEqual(self.ingest(self.payload('unreachable'))['cases']['C'],'remote_unreachable')
        self.assertEqual(self.m['cases']['C']['work_status'],'remote_pending')
    def test_cached_before_earliest_stays_pending(self):
        self.check['earliest_check_at']=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(minutes=30)).isoformat()
        self.assertEqual(self.ingest(self.payload('still-cached'))['cases']['C'],'remote_cached')
    def test_rejects_wrong_run_hash_unknown_duplicate_and_inconsistent_pass_atomically(self):
        for kind in ('run','hash','unknown','duplicate','condition','cleanup','obsolete','future','extra'):
            with self.subTest(kind=kind):
                original=copy.deepcopy(self.m); p=self.payload()
                if kind=='run':p['run_id']='other'
                if kind=='hash':p['request_sha256']='0'*64
                if kind=='unknown':p['results'][0]['id']='other'
                if kind=='duplicate':p['results']*=2
                if kind=='condition':p['results'][0]['conditions']=[False]
                if kind=='cleanup':self.m['cases']['C']['attempts'][0]['cleanup_verified']=False
                if kind=='obsolete':self.m['cases']['C']['version']='changed'
                if kind=='future':p['results'][0]['checked_at']='2999-01-01T00:00:00Z'
                if kind=='extra':p['results'][0]['body']='not allowed'
                with self.assertRaises(common.UiaError):self.ingest(p)
                self.m=original
    def test_rejects_restored_or_late_immediate_pass(self):
        self.check['restored_at']=self.check['saved_at']
        with self.assertRaises(common.UiaError): self.ingest(self.payload())
        del self.check['restored_at'];self.check['max_latency_seconds']=5
        with self.assertRaises(common.UiaError): self.ingest(self.payload())
    def test_pending_local_result_never_becomes_case_pass(self):
        remote.fold(self.m,'C'); self.assertEqual(self.m['cases']['C']['result'],'remote_pending')

    def test_held_cleanup_is_restored_in_reverse_order_before_case_pass(self):
        attempt = self.m['cases']['C']['attempts'][-1]
        attempt.update(cleanup_verified=False, cleanup_pending=True, at=common.now())
        directory=self.base/'state/fixture-snapshots';directory.mkdir(parents=True)
        common.atomic_write(directory/'b-C.json', {'original':{}})
        self.m['cases']['D']=copy.deepcopy(self.m['cases']['C'])
        self.m['cases']['D']['attempts'][-1].update(batch_id='later',at=common.now())
        common.atomic_write(directory/'later-D.json', {'original':{}})
        def fake_restore(*args, **kwargs):
            leases=common.read_json(kwargs['env']['UIA_REMOTE_LEASES'])
            self.assertEqual([r['case_id'] for r in leases],['D','C'])
            return SimpleNamespace(stdout=json.dumps({'cleanup_verified':True,'proofs':[
                {'case_id':r['case_id'],'cleanup_verified':True,'restored_at':common.now()} for r in leases]}),returncode=0)
        with patch('subprocess.run',side_effect=fake_restore):
            result=self.ingest(self.payload())
        self.assertTrue(result['cleanup']['cleanup_verified'])
        self.assertEqual(self.m['cases']['C']['result'],'passed')
        self.assertFalse(attempt['cleanup_pending'])
        self.assertTrue(self.check['restored_at'])

    def test_clean_local_phase_hands_off_without_pass_or_contamination(self):
        import yaml
        from uia_core import runtime
        c=self.m['cases']['C']
        c.update(attempts=[],case_id='C',fixture_ids=['f'],registration={'fixture':{'mutates':True}},repair_rounds=0,
                 pass_streak=0,case_spec='cases/C/case-spec.yaml',stage='execution',work_status='running')
        self.m.update(questions={},contaminated_fixtures={},batches=[],delivery={})
        self.m['config']['execution']['repair_rounds']=2
        folder=self.base/'cases/C';folder.mkdir(parents=True)
        (folder/'case-spec.yaml').write_text(yaml.safe_dump({'assertions':[{'id':'A2','excel':self.check['expected']}]}))
        directory=self.base/'batches/b';directory.mkdir(parents=True)
        self.m['active_batch']={'id':'b','directory':'batches/b','case_ids':['C'],'report':'batches/b/case-results.json','versions':{'C':'v'}}
        common.atomic_write(directory/'remote-C.json',[{k:self.check[k] for k in ('assertion_id','expected','url','method','saved_at','conditions')}])
        common.atomic_write(directory/'case-results.json',{'schema_version':'uia-batch-results.v1','batch_id':'b','complete':True,
          'cases':[{'case_id':'C','result':'passed','playwright_status':'passed','setup_started':True,'retry':0,
                    'lifecycle':{'batch_id':'b','setup_verified':True,'cleanup_verified':False,'cleanup_pending':True}}]})
        self.m['remote_checks']={}
        with patch.object(runtime,'case_version',return_value='v'):
            result=runtime.consume_batch(self.base,self.m)
        self.assertEqual(result['results']['C'],'remote_pending')
        self.assertEqual(self.m['contaminated_fixtures'],{})
        self.assertEqual(self.m['questions'],{})
        self.assertEqual(c['pass_streak'],0)
        request=common.read_json(self.request)
        self.assertEqual(request['checks'][0]['expected'],self.check['expected'])
        self.assertTrue((self.base/'remote-checks/check.mjs').is_file())
