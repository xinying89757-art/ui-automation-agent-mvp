import copy
import datetime as dt
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uia_core import common, remote_checks as remote

FAQ_BODY = '''## FAQ
- **Q: UIA FAQ uia-0b66f30241cd450fa08f93aafdb8746d-TC-0033 5**
A: UIA answer 5
- **Q: UIA FAQ uia-0b66f30241cd450fa08f93aafdb8746d-TC-0033 4**
A: UIA answer 4
- **Q: UIA FAQ uia-0b66f30241cd450fa08f93aafdb8746d-TC-0033 3**
A: UIA answer 3
- **Q: UIA FAQ uia-0b66f30241cd450fa08f93aafdb8746d-TC-0033 2**
A: UIA answer 2
- **Q: faq标题**
A: 内容内容
'''
FAQ_PAIRS = [[f'UIA FAQ uia-0b66f30241cd450fa08f93aafdb8746d-TC-0033 {n}', f'UIA answer {n}'] for n in (5,4,3,2)] + [['faq标题','内容内容']]

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
                'results':[{'id':'check1','checked_at':common.now(),'status':status,'variant':'cache_busted' if self.check.get('cache_bust') else 'default','http_status':200 if status!='unreachable' else None,
                            'conditions':[True] if status=='pass' else [False] if status!='unreachable' else [],
                            'reason':{'pass':'conditions_met','fail':'conditions_mismatch','still-cached':'cache_window','unreachable':'network'}[status]}]}
    def ingest(self, payload):
        f=self.base/'fake-results.json'; common.atomic_write(f,payload); return remote.ingest(self.base,self.m,f)
    def configure_faq(self):
        self.check['conditions']=[{'op':'ordered_pairs','section':'FAQ','value':FAQ_PAIRS}]
        common.atomic_write(self.request, {'schema_version':'uia-remote-request.v1','run_id':'R','checks':[self.check]})
    def evidence(self, text):
        return [{'section_sha256':hashlib.sha256(text.encode()).hexdigest(),'excerpt':text}]
    def test_ordered_pairs_parser_matches_exact_markdown_and_legacy(self):
        condition={'op':'ordered_pairs','section':'FAQ','value':FAQ_PAIRS}
        self.assertTrue(remote.evaluate_condition(FAQ_BODY,condition))
        self.assertFalse(remote.evaluate_condition(FAQ_BODY.replace('answer 5','answer 4',1),condition))
        missing=FAQ_BODY.replace('- **Q: UIA FAQ uia-0b66f30241cd450fa08f93aafdb8746d-TC-0033 3**\nA: UIA answer 3\n','')
        self.assertFalse(remote.evaluate_condition(missing,condition))
        self.assertTrue(remote.evaluate_condition('## FAQ\nQ1\nA1\nQ2\nA2\n',{'op':'ordered_pairs','section':'faq','value':[['Q1','A1'],['Q2','A2']]}))
        self.assertTrue(remote.evaluate_condition('### FAQ\n- **问：你好**\n答：世界\nQ: one A: two\n### Else\nignored',{'op':'ordered_pairs','section':'FAQ','value':[['你好','世界'],['one','two']]}))

    def test_not_contains_length_truncation_and_faq_jsonld_are_exact(self):
        self.assertTrue(remote.evaluate_condition('short text', {'op':'not_contains','value':'secret'}))
        self.assertFalse(remote.evaluate_condition('short secret', {'op':'not_contains','value':'secret'}))
        self.assertTrue(remote.evaluate_condition('12345', {'op':'max_length','value':5}))
        self.assertFalse(remote.evaluate_condition('123456', {'op':'max_length','value':5}))
        self.assertTrue(remote.evaluate_condition('12345', {'op':'truncated_at','value':5,'text':'123456'}))
        self.assertFalse(remote.evaluate_condition('123456', {'op':'truncated_at','value':5,'text':'123456'}))
        one={'@context':'https://schema.org','@type':'FAQPage','mainEntity':[{'@type':'Question','name':'Q1','acceptedAnswer':{'text':'A1'}}]}
        two={'@type':'FAQPage','mainEntity':[{'@type':'Question','name':'Q2','acceptedAnswer':{'text':'A2'}}]}
        body='<script type="application/ld+json">'+json.dumps({'@graph':[one,two]})+'</script>'
        condition={'op':'faq_page','value':{'count':2,'objects':[{'pairs':[['Q1','A1']]},{'pairs':[['Q2','A2']]}]}}
        self.assertTrue(remote.evaluate_condition(body,condition))
        crossed={'op':'faq_page','value':{'count':2,'objects':[{'pairs':[['Q1','A1'],['Q2','A2']]},{'pairs':[]}]}}
        self.assertFalse(remote.evaluate_condition(body,crossed))

    def test_save_not_persisted_suppresses_remote_verdict_and_success_reports_readback(self):
        self.assertEqual(remote.judge_watch({}, {}, common.now(), None, save_not_persisted=True),
                         ('save_not_persisted', 'unreachable', None, '前置保存未生效，公开检查不判定'))
        payload = self.real_watch_payload('request_start')
        request = common.read_json(self.base/'remote-checks/watch/w1/request.json')
        request['read_back'] = {'ok':True,'actual':'phase2-immediate-public-overview'}
        code, status, _, report = remote.judge_watch(payload, request, self.check['saved_at'], None)
        self.assertEqual((code, status), ('immediate_not_met', 'fail'))
        self.assertIn('后台读回：phase2-immediate-public-overview ✓', report)
    def test_fail_with_matching_evidence_is_checker_automation_failure(self):
        self.configure_faq(); p=self.payload('fail'); p['results'][0]['evidence']=self.evidence(FAQ_BODY)
        self.assertEqual(self.ingest(p)['cases']['C'],'automation_failure')
        history=self.m['remote_checks']['check1']['history'][0]
        self.assertTrue(history['local_reevaluation']['all_conditions'])
        self.assertEqual(history['local_reevaluation']['evaluator_version'],'2')
    def test_fail_with_nonmatching_evidence_is_business_failure(self):
        self.configure_faq(); p=self.payload('fail'); p['results'][0]['evidence']=self.evidence(FAQ_BODY.replace('UIA answer 5','wrong'))
        self.assertEqual(self.ingest(p)['cases']['C'],'business_failure')
    def test_evidence_redaction_and_manual_reevaluation_path(self):
        self.configure_faq()
        fake_jwt='.'.join(('eyJabcdefghijk','abcdefghijk','abcdefghijk'))
        text='## FAQ\n- **Q: contact person@example.com '+fake_jwt+' 13812345678 1234567890123**\nA: secret'
        clean=remote.redact_evidence(text)
        for secret in ('person@example.com','eyJabcdefghijk','13812345678','1234567890123'): self.assertNotIn(secret,clean)
        self.assertTrue(remote.evaluate_condition(FAQ_BODY, self.check['conditions'][0]))
        self.assertEqual(self.ingest(self.payload('fail'))['cases']['C'],'business_failure')
        evidence=self.base/'evidence.json'; common.atomic_write(evidence,{'id':'check1','section':FAQ_BODY})
        result=remote.reevaluate(self.base,self.m,evidence)
        self.assertEqual(result['result'],'passed')
        self.assertEqual(self.m['cases']['C']['remote_status'],'pass_reevaluated')
        self.assertEqual(self.m['remote_checks']['check1']['history'][-1]['evidence_source'],'local_reevaluation')
        self.assertTrue((self.base/self.m['remote_checks']['check1']['history'][-1]['evidence_file']).is_file())
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
        for kind in ('run','hash','unknown','duplicate','condition','cleanup','obsolete','future','extra','variant'):
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
                if kind=='variant':p['results'][0]['variant']='cache_busted'
                with self.assertRaises(common.UiaError):self.ingest(p)
                self.m=original
    def test_rejects_restored_or_late_immediate_pass(self):
        self.check['restored_at']=self.check['saved_at']
        with self.assertRaises(common.UiaError): self.ingest(self.payload())
        del self.check['restored_at'];self.check['max_latency_seconds']=5
        with self.assertRaises(common.UiaError): self.ingest(self.payload())
    def test_pending_local_result_never_becomes_case_pass(self):
        remote.fold(self.m,'C'); self.assertEqual(self.m['cases']['C']['result'],'remote_pending')

    def test_arm_watch_writes_static_credential_free_request_and_refuses_dynamic_values(self):
        import yaml
        runner=self.base/'runner/knowledge'; runner.mkdir(parents=True)
        (runner/'page-map.yaml').write_text(yaml.safe_dump({'targets':{'public.llms.immediate':{'resource':{'path':'/llms.txt','max_latency_seconds':5}}}}))
        folder=self.base/'cases/C'; folder.mkdir(parents=True)
        (folder/'case-spec.yaml').write_text(yaml.safe_dump({'steps':[{'id':'S2','verb':'defer_public','target':'public.llms.immediate'}],
          'assertions':[{'id':'A2','after':'S2','excel':'2. 公开文件立即显示新的网站概述。','checks':[{'op':'remote_file','target':'public.llms.immediate','value':{'op':'contains','value':'new overview'}}]}]}))
        self.m['cases']['C']['case_spec']='cases/C/case-spec.yaml'; self.m['config'].update(targets={'public':'https://example.test'},environment={'entry_url':'https://example.test'})
        with patch.object(remote,'_clock_offset',return_value=23):
            armed=remote.arm_watch(self.base,self.m,'C',lead_minutes=0,watch_minutes=2,interval_ms=500)
        request=common.read_json(self.base/armed['request'])
        self.assertEqual(request['schema_version'],'uia-remote-watch.v1'); self.assertEqual(request['max_latency_seconds'],5)
        self.assertEqual(request['conditions'][0]['value'],'new overview'); self.assertNotIn('box_clock_offset_ms',request)
        self.assertEqual(self.m['remote_watches'][armed['watch_id']]['box_clock_offset_ms'],23)
        data=(folder/'case-spec.yaml').read_text().replace('new overview','$fixture.overview')
        (folder/'case-spec.yaml').write_text(data)
        with self.assertRaisesRegex(common.UiaError,'static'):
            remote.arm_watch(self.base,self.m,'C')

    def test_watch_scheduler_waits_and_rejects_more_than_hour(self):
        base=dt.datetime(2026,1,1,tzinfo=dt.timezone.utc); current=[base]; sleeps=[]
        watch={'save_not_before':(base+dt.timedelta(seconds=7)).isoformat()}
        def sleep(seconds): sleeps.append(seconds); current[0]+=dt.timedelta(seconds=seconds)
        beats=[]
        remote.wait_for_watch(self.base,watch,clock=lambda:current[0],sleeper=sleep,heartbeat=lambda *_:beats.append(True))
        self.assertEqual(current[0],base+dt.timedelta(seconds=7)); self.assertTrue(sleeps); self.assertGreaterEqual(len(beats),2)
        with self.assertRaisesRegex(common.UiaError,'60 minutes'):
            remote.wait_for_watch(self.base,{'save_not_before':(base+dt.timedelta(hours=1,seconds=1)).isoformat()},clock=lambda:base,sleeper=lambda _:None)

    def watch_payload(self, verdict='pass'):
        saved=dt.datetime(2026,1,1,tzinfo=dt.timezone.utc)
        self.check.update(saved_at=saved.isoformat(),max_latency_seconds=5,earliest_check_at=saved.isoformat(),deadline=(saved+dt.timedelta(hours=2)).isoformat())
        folder=self.base/'remote-checks/watch/w1'; folder.mkdir(parents=True,exist_ok=True)
        common.atomic_write(folder/'request.json',{'schema_version':'uia-remote-watch.v1','run_id':'R','watch_id':'w1',
          'max_latency_seconds':5,'interval_ms':1000,'timeout_ms':10000,'url':self.check['url'],'conditions':self.check['conditions']})
        self.m['remote_watches']={'w1':{'watch_id':'w1','case_id':'C','assertion_id':'A2','status':'armed','armed_at':(saved-dt.timedelta(minutes=1)).isoformat(),'request_file':'remote-checks/watch/w1/request.json','request_sha256':common.file_hash(folder/'request.json'),'box_clock_offset_ms':None}}
        first=saved-dt.timedelta(seconds=1)
        times=[0,1000,2000,3000,4000]
        polls=[{'t_ms':t,'ok':True,'present': t >= 2000} for t in times]
        payload={'schema_version':'uia-remote-watch-results.v1','run_id':'R','watch_id':'w1','request_sha256':common.file_hash(folder/'request.json'),
          'first_poll_at':first.isoformat(),'last_poll_at':(first+dt.timedelta(milliseconds=times[-1])).isoformat(),'poll_count':5,'error_count':0,'max_gap_ms':1000,
          'baseline_absent':True,'last_absent_at':(first+dt.timedelta(milliseconds=1000)).isoformat(),'first_present_at':(first+dt.timedelta(milliseconds=2000)).isoformat(),
          'confirmed_present':True,'clock_offset_ms':0,'evidence':{'excerpt':'new','section_sha256':hashlib.sha256(b'new').hexdigest()},
          'timeline':[{'t_ms':0,'state':'absent'},{'t_ms':2000,'state':'present'}],'polls':polls}
        if verdict=='late':
            payload['first_poll_at']=(saved+dt.timedelta(seconds=1)).isoformat()
        elif verdict=='baseline':
            payload['baseline_absent']=False; payload['polls'][0]['present']=True
            payload['timeline']=[{'t_ms':0,'state':'present'},{'t_ms':1000,'state':'absent'},{'t_ms':2000,'state':'present'}]
        elif verdict=='clock':
            payload['clock_offset_ms']=1500
        elif verdict=='gap':
            payload.update(poll_count=1,error_count=1,max_gap_ms=0,baseline_absent=False,last_absent_at=None,
                           first_present_at=None,confirmed_present=False,evidence=None,polls=[{'t_ms':0,'ok':False,'present':False}],timeline=[{'t_ms':0,'state':'error'}])
        elif verdict=='late_present_unproven':
            # First present after the window but no absent sample after the window: not proof of a slow update.
            payload['first_present_at']=(saved+dt.timedelta(seconds=8)).isoformat(); payload['last_absent_at']=(saved-dt.timedelta(seconds=1)).isoformat()
        elif verdict=='not_met':
            payload.update(poll_count=7,error_count=0,max_gap_ms=17000,first_present_at=(saved+dt.timedelta(seconds=8)).isoformat(),
              last_absent_at=(saved+dt.timedelta(seconds=18)).isoformat(),confirmed_present=True,
              polls=[{'t_ms':t,'ok':True,'present':t>=19000} for t in (0,17000,18000,18500,19000,20000,21000)],
              timeline=[{'t_ms':0,'state':'absent'},{'t_ms':19000,'state':'present'}])
        path=self.base/'watch-results.json'; common.atomic_write(path,payload); return path

    def test_watch_ingest_verdicts_and_idempotence(self):
        for kind,code,status in [('pass','immediate_met','pass'),('not_met','immediate_not_met','fail'),('late','watch_started_late','unreachable'),('baseline','baseline_present','unreachable'),('clock','clock_offset','unreachable'),('gap','watch_gap','unreachable'),('late_present_unproven','watch_gap','unreachable')]:
            with self.subTest(kind=kind):
                # Reinitialize because each ingest folds its case state.
                self.setUpCaseForWatch()
                path=self.watch_payload(kind); result=remote.ingest_watch(self.base,self.m,path)
                self.assertEqual(result['reason'],code); self.assertEqual(self.m['remote_checks']['check1']['status'],status)
                self.assertEqual(result['latency_ms'],8000 if kind in {'not_met','late_present_unproven'} else None if kind=='gap' else 1000)
                self.assertTrue(remote.ingest_watch(self.base,self.m,path)['duplicate'])
                self.assertEqual(len(self.m['remote_checks']['check1']['history']),1)

    def real_watch_payload(self, basis=None):
        saved=dt.datetime.fromisoformat('2026-10-22T06:27:37.010+00:00')
        self.setUpCaseForWatch(); self.check['saved_at']=saved.isoformat()
        folder=self.base/'remote-checks/watch/w1'; folder.mkdir(parents=True,exist_ok=True)
        request={'schema_version':'uia-remote-watch.v1','run_id':'R','watch_id':'w1','interval_ms':1000,'timeout_ms':10000,
                 'max_latency_seconds':5,'max_clock_offset_ms':1000,'url':self.check['url'],'conditions':self.check['conditions']}
        common.atomic_write(self.base/'remote-checks/watch/w1/request.json',request)
        self.m['remote_watches']={'w1':{'watch_id':'w1','case_id':'C','assertion_id':'A2','status':'armed',
          'armed_at':(saved-dt.timedelta(minutes=1)).isoformat(),'request_file':'remote-checks/watch/w1/request.json',
          'request_sha256':common.file_hash(self.base/'remote-checks/watch/w1/request.json'),'box_clock_offset_ms':None}}
        first=dt.datetime.fromisoformat('2026-10-22T06:08:34.971+00:00')
        values=list(range(0,872000,1600))+[872978,1233371]+list(range(1235088,1714000,1600))+[1714006]
        polls=[{'t_ms':t,'ok':t!=1233371,'present':False} for t in values]
        states=[{'t_ms':polls[0]['t_ms'],'state':'absent'}, {'t_ms':1233371,'state':'error'},
                {'t_ms':next(t for t in values if t>1233371),'state':'absent'}]
        payload={'schema_version':'uia-remote-watch-results.v1','run_id':'R','watch_id':'w1','request_sha256':common.file_hash(self.base/'remote-checks/watch/w1/request.json'),
          'first_poll_at':first.isoformat(),'last_poll_at':'2026-10-22T06:37:09.950+00:00','poll_count':len(polls),'error_count':1,
          'max_gap_ms':max((b['t_ms']-a['t_ms'] for a,b in zip(polls,polls[1:])),default=0),'baseline_absent':True,
          'last_absent_at':'2026-10-22T06:37:08.977+00:00','first_present_at':None,'confirmed_present':False,'clock_offset_ms':306,
          'evidence':None,'timeline':states,'polls':polls}
        if basis: payload['t_ms_basis']=basis
        return payload

    def test_real_long_hang_still_proves_immediate_failure_for_both_time_bases(self):
        for basis in (None,'request_start'):
            with self.subTest(basis=basis):
                payload=self.real_watch_payload(basis)
                path=self.base/'watch-results.json'; common.atomic_write(path,payload)
                with patch.object(remote,'restore',return_value=None): result=remote.ingest_watch(self.base,self.m,path)
                self.assertEqual((result['reason'],result['status']),('immediate_not_met','fail'))
                self.assertIn('572 秒',result['report']); self.assertIn('时限 5 秒',result['report'])

    def test_absence_continuous_from_before_save_through_end_is_not_met(self):
        payload=self.real_watch_payload('request_start'); request=common.read_json(self.base/'remote-checks/watch/w1/request.json')
        values=list(range(0,1714000,1600))
        payload['polls']=[{'t_ms':t,'ok':True,'present':False} for t in values]
        payload.update(poll_count=len(values),error_count=0,max_gap_ms=1600,timeline=[{'t_ms':0,'state':'absent'}])
        code,status,_,report=remote.judge_watch(payload,request,self.check['saved_at'],None)
        self.assertEqual((code,status),('immediate_not_met','fail')); self.assertIn('仍未出现新内容',report)
        # A trailing error poll means the absent run no longer reaches the end; stay undecided.
        payload['polls'][-1]={'t_ms':values[-1],'ok':False,'present':False}
        self.assertEqual(remote.judge_watch(payload,request,self.check['saved_at'],None)[0],'watch_gap')

    def test_gap_present_with_no_dense_tail_remains_unreachable(self):
        payload=self.real_watch_payload('request_start'); request=common.read_json(self.base/'remote-checks/watch/w1/request.json')
        payload['polls']=[{'t_ms':0,'ok':True,'present':False},{'t_ms':600000,'ok':False,'present':False},
                          {'t_ms':700000,'ok':True,'present':True}]
        payload.update(poll_count=3,error_count=1,max_gap_ms=100000,confirmed_present=False,first_present_at='2026-10-22T06:27:37.010+00:00',
                       evidence={'excerpt':'new','section_sha256':hashlib.sha256(b'new').hexdigest()})
        self.assertEqual(remote.judge_watch(payload,request,self.check['saved_at'],None)[:2],('watch_gap','unreachable'))

    def test_late_present_after_dense_absence_is_not_met(self):
        payload=self.real_watch_payload('request_start'); request=common.read_json(self.base/'remote-checks/watch/w1/request.json')
        saved=dt.datetime.fromisoformat(self.check['saved_at']); first=dt.datetime.fromisoformat(payload['first_poll_at'])
        t=lambda sec: int((saved+dt.timedelta(seconds=sec)-first).total_seconds()*1000)
        payload['polls']=[{'t_ms':t(sec),'ok':True,'present':False} for sec in (10,11,12)]+[
          {'t_ms':t(sec),'ok':True,'present':True} for sec in (30,31,32)]
        payload.update(poll_count=6,error_count=0,max_gap_ms=19000,confirmed_present=True,
          first_present_at=(saved+dt.timedelta(seconds=30)).isoformat(),last_absent_at=(saved+dt.timedelta(seconds=12)).isoformat(),
          timeline=[{'t_ms':payload['polls'][0]['t_ms'],'state':'absent'},{'t_ms':t(30),'state':'present'}],
          evidence={'excerpt':'new','section_sha256':hashlib.sha256(b'new').hexdigest()})
        code,status,_,report=remote.judge_watch(payload,request,self.check['saved_at'],None)
        self.assertEqual((code,status),('immediate_not_met','fail')); self.assertIn('首次出现',report)

    def test_reevaluate_watch_updates_archived_gap_without_restore_and_is_idempotent(self):
        payload=self.real_watch_payload('request_start')
        path=self.base/'watch-results.json'; common.atomic_write(path,payload)
        # Ingest once to establish the immutable result archive, then model the earlier verdict.
        remote.ingest_watch(self.base,self.m,path)
        watch=self.m['remote_watches']['w1']; entry=self.m['remote_checks']['check1']
        watch['verdict']='watch_gap'; entry['status']='unreachable'; entry['watch_verdict']['reason']='watch_gap'
        with patch.object(remote,'restore',side_effect=AssertionError('restore must not run')):
            first=remote.reevaluate_watch(self.base,self.m,'w1')
            second=remote.reevaluate_watch(self.base,self.m,'w1')
        self.assertFalse(first['results'][0]['duplicate']); self.assertTrue(second['results'][0]['duplicate'])
        self.assertEqual(watch['verdict'],'immediate_not_met'); self.assertEqual(entry['status'],'fail')
        self.assertEqual(entry['history'][-1]['variant'],'watch_reevaluation')

    def setUpCaseForWatch(self):
        # Restore the common fixture between verdict scenarios without recreating temp paths.
        saved=dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=5)
        self.check.update(saved_at=saved.isoformat(),max_latency_seconds=5,earliest_check_at=saved.isoformat(),deadline=(saved+dt.timedelta(hours=2)).isoformat())
        common.atomic_write(self.request,{'schema_version':'uia-remote-request.v1','run_id':'R','checks':[self.check]})
        self.m['remote_checks']={'check1':{'request':self.check,'version':'v','batch_id':'b','status':'pending','active':True,'history':[]}}
        self.m['cases']['C']['attempts'][-1].update(cleanup_verified=True,cleanup_pending=False,setup_verified=True,result='passed')

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
        common.atomic_write(directory/'remote-C.json',[{**{k:self.check[k] for k in ('assertion_id','expected','url','method','saved_at','conditions')},'max_latency_seconds':5}])
        common.atomic_write(directory/'case-results.json',{'schema_version':'uia-batch-results.v1','batch_id':'b','complete':True,
          'cases':[{'case_id':'C','result':'passed','playwright_status':'passed','setup_started':True,'retry':0,
                    'lifecycle':{'batch_id':'b','setup_verified':True,'cleanup_verified':False,'cleanup_pending':True}}]})
        self.m['remote_checks']={}
        with patch.object(runtime,'case_version',return_value='v'), patch('uia_core.remote_checks.ROOT', self.base):
            result=runtime.consume_batch(self.base,self.m)
            hold=remote.hold_path(self.m)
            self.assertTrue(hold.is_file())
            self.assertEqual(common.read_json(hold)['run_id'],'R')
            remote.finalize(self.base,self.m)
        self.assertEqual(result['results']['C'],'remote_pending')
        self.assertEqual(self.m['contaminated_fixtures'],{})
        self.assertEqual(self.m['questions'],{})
        self.assertEqual(c['pass_streak'],0)
        request=common.read_json(self.request)
        self.assertEqual(request['checks'][0]['expected'],self.check['expected'])
        self.assertTrue((self.base/'remote-checks/check.mjs').is_file())
        self.assertTrue(request['checks'][0]['cache_bust'])
        self.assertEqual(remote.timestamp(request['checks'][0]['earliest_check_at']), remote.timestamp(request['checks'][0]['saved_at']))
