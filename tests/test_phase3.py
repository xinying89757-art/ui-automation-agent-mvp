import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uia_core import common, experience, workflow, profiles, specs, cli, metrics, reports
from openpyxl import Workbook

SOURCE = Path(__file__).resolve().parents[1]


class PhaseThreeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(module, 'ROOT', self.root) for module in (common, experience, workflow, profiles)]
        for p in self.patches:
            p.start()
        shutil.copytree(SOURCE / 'assets', self.root / 'assets', ignore=shutil.ignore_patterns('node_modules', 'results'))
        shutil.copytree(SOURCE / 'examples/phase2', self.root / 'examples/phase2')
        self.base = self.root / 'runs/R'
        self.base.mkdir(parents=True)
        self.m = {'cases': {}, 'config': {'environment': {'id': 'production'}, 'site': 'https://example.test',
                  'auth': {}, 'network': {'mode': 'direct'}, 'mutation': {'allowed': True, 'scope': ['llms.txt']}},
                  'questions': {}, 'history': [], 'interaction_mode': 'once', 'exploration': [], 'sources': []}
        self.add_case('TC-0002', ['no_settings_permission'])
        self.add_case('T2', [])

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def add_case(self, cid, env, questions=None):
        folder = self.base / 'cases' / cid
        folder.mkdir(parents=True, exist_ok=True)
        common.atomic_write(folder / 'source.json', {'case_id': cid, 'title': '测试', 'preconditions': '', 'expected': ['窗口显示']})
        common.atomic_write(folder / 'case-spec.yaml', {'required_env': env, 'mutation_scope': ['llms.txt'], 'questions': questions or []}, as_yaml=True)
        self.m['cases'][cid] = {'case_id': cid, 'case_spec': f'cases/{cid}/case-spec.yaml', 'source': f'cases/{cid}/source.json',
                              'stage': 'execution', 'work_status': 'runnable', 'result': None, 'attempts': [],
                              'registration': {'fixture': {'mutation_scope': ['llms.txt']}}}

    def test_one_sentence_memory_reuse_and_unavailable_case_only_waits(self):
        first = experience.sync_checklist(self.base, self.m)
        self.assertEqual(first['question_count'], 2)
        result = experience.answer_sentence(self.base, self.m, 'A 除 TC-0002 缺少外其余可用，B 同意，C 无歧义')
        self.assertEqual(result['waiting'], ['TC-0002'])
        self.assertEqual(self.m['cases']['T2']['work_status'], 'runnable')
        second = copy.deepcopy(self.m)
        second['questions'] = {}; second.pop('checklist_issued')
        self.assertEqual(experience.sync_checklist(self.base, second)['question_count'], 0)
        self.assertEqual(second['cases']['TC-0002']['work_status'], 'waiting_human')
        self.assertEqual(experience.memory_path(self.m).stat().st_mode & 0o777, 0o600)
        second['config']['site'] = 'https://other.example.test'
        second['questions'] = {}
        self.assertEqual(experience.sync_checklist(self.base, second)['question_count'], 2)

    def test_ambiguous_answers_do_not_persist_or_guess_business(self):
        self.add_case('T3', [], ['空值应如何处理？选项：阻止/允许'])
        experience.sync_checklist(self.base, self.m)
        with self.assertRaises(common.UiaError):
            experience.answer_sentence(self.base, self.m, 'A 都有，B 同意，C 按默认')
        self.assertFalse(experience.memory_path(self.m).exists())
        experience.answer_sentence(self.base, self.m, 'A 都有，B 同意，C 选阻止')
        self.assertEqual(experience.sync_checklist(self.base, self.m)['question_count'], 0)

    def test_late_permission_is_reviewed_never_reasked(self):
        experience.sync_checklist(self.base, self.m)
        experience.answer_sentence(self.base, self.m, 'A 都有，B 同意，C 无歧义')
        self.add_case('T3', ['editor_4_0'])
        result = experience.sync_checklist(self.base, self.m)
        self.assertEqual(result['question_count'], 0)
        self.assertEqual(result['pending_review_count'], 1)
        self.assertEqual(self.m['cases']['T3']['work_status'], 'waiting_human')
        q = workflow.question(self.m, 'demo', 'new-page', '请录制', ['T2'])
        self.assertEqual(q['status'], 'deferred')
        review = experience.review(self.base, self.m)
        self.assertFalse(review['blocking_delivery'])
        self.assertTrue(any('codegen' in x.get('command', '') for x in review['items']))

    def test_multiple_business_answers_use_numbered_choices(self):
        self.add_case('T3', [], ['甲选项：阻止/允许', '乙选项：阻止/允许'])
        experience.sync_checklist(self.base, self.m)
        experience.answer_sentence(self.base, self.m, 'A 都有，B 同意，C 1选阻止、2选允许')
        values = [v for k, v in experience.load_memory(self.m)['answers'].items() if k.startswith('business:')]
        self.assertEqual(values, ['阻止', '允许'])

    def test_interventions_count_turns_not_agent_commands(self):
        experience.session_turn(self.m, 'u1', '发起')
        experience.session_turn(self.m, 'u2', '计划外')
        experience.session_turn(self.m, 'u2', '计划外')
        self.m['unplanned_interventions'] = 77
        result = metrics.calculate(self.base, self.m)
        self.assertEqual(result['unplanned_interventions'], 1)
        self.assertEqual(result['session_turns'], 2)
        self.assertEqual(result['mid_run_questions'], 0)

    def test_assertion_signature_survives_manifest_json_roundtrip(self):
        signature = metrics.assertion_signature("await expect(x).toHaveText('原始期望');")
        self.assertEqual(signature, json.loads(json.dumps(signature)))

    def test_business_failure_review_preserves_repro_and_expectation(self):
        c = self.m['cases']['T2']
        c.update(result='business_failure', title='错误文案缺失', attempts=[{'errors': ['UIA_BUSINESS_FAILURE: expected error'], 'evidence': 'evidence/result.json'}])
        payload = experience.review(self.base, self.m)
        defect = next(x for x in payload['items'] if x['kind'] == 'suspected_defect')
        self.assertEqual(defect['expected'], ['窗口显示'])
        self.assertFalse(defect['applied'])
        self.assertIn('未采集', defect['screenshot_status'])

    def test_checklist_cannot_expand_configured_mutation_scope(self):
        self.m['config']['mutation'] = {'allowed': False, 'scope': []}
        experience.sync_checklist(self.base, self.m)
        experience.answer_sentence(self.base, self.m, 'A 都有，B 同意，C 无歧义')
        self.assertEqual(self.m['config']['mutation']['scope'], [])
        self.assertEqual(self.m['cases']['T2']['work_status'], 'waiting_human')

    def test_cn_report_opening_and_cli_backward_compatibility(self):
        flow = metrics.calculate(self.base, self.m)
        blocks = reports.opening(self.m, flow, {'items': []})
        self.assertEqual([x['title'] for x in blocks], ['结论', '需要你处理', '流程指标'])
        self.assertNotIn('runnable', json.dumps(blocks))
        self.assertEqual(cli.parser().parse_args(['answer', '--run', 'R', 'A 都有，B 同意']).sentence, 'A 都有，B 同意')
        self.assertEqual(cli.parser().parse_args(['answer', '--run', 'R', '--question', 'Q', '--file', 'a.json']).file, 'a.json')
        self.assertEqual(cli.parser().parse_args(['go', 'a.xlsx', '--cases', 'T1,T2']).cases, 'T1,T2')

    def test_go_runs_existing_first_and_resumes_without_duplicate_execution(self):
        # Fresh-clone path with an arbitrary workbook: existing specs first, no model invocation.
        auth = self.root / 'private.json'
        common.atomic_write(auth, {'account': 'fake-private-user', 'password': 'fake-private-password'})
        profiles.setup('offline', 'production', 'en.example.test', credentials_file=auth)
        workbook = self.root / 'sample.xlsx'
        wb = Workbook(); ws = wb.active
        ws.append(['用例ID', '用例标题', '前置条件', '操作步骤', '预期结果'])
        ws.append(['TC-0004', '窗口', '', '打开', '显示'])
        ws.append(['NEW-2', '新页面', '', '打开', '显示'])
        wb.save(workbook)
        def preflight(base, m, evidence):
            m['preflight'] = {'status': 'passed'}
        def run_existing(manifest, ready):
            with common.locked_run(manifest) as (path, m):
                for cid in ready:
                    m['cases'][cid].update(result='passed', work_status='finished')
                common.save(path, m)
        with patch.object(profiles, 'invoke_login', return_value={}), patch('uia_core.runtime.preflight', side_effect=preflight), patch.object(experience, '_run_ready', side_effect=run_existing) as run, patch.object(reports, 'make_report', return_value={}):
            first = experience.go(workbook, 'offline', 'TC-0004,NEW-2')
            self.assertEqual(first['question_count'], 0)
            self.assertEqual(run.call_args.args[1], ['TC-0004'])
            second = experience.go(workbook, 'offline', 'TC-0004,NEW-2')
            self.assertEqual(first['run_id'], second['run_id'])
            self.assertEqual(run.call_count, 1)
            self.assertEqual(second['spec_tasks'][0]['case_id'], 'NEW-2')

    def test_go_prefers_source_matched_generated_case_spec_before_legacy_binding(self):
        auth = self.root / 'private.json'
        common.atomic_write(auth, {'account': 'fake-private-user', 'password': 'fake-private-password'})
        profiles.setup('offline', 'production', 'en.example.test', credentials_file=auth)
        workbook = self.root / 'matched.xlsx'
        wb = Workbook(); ws = wb.active
        ws.append(['用例ID', '用例标题', '前置条件', '操作步骤', '预期结果'])
        ws.append(['TC-0004', '窗口', '', '打开', '显示'])
        wb.save(workbook)
        original_import = workflow.import_excel
        def import_with_matched_hash(base, manifest, source):
            result = original_import(base, manifest, source)
            manifest['cases']['TC-0004']['source_hash'] = common.read_json(self.root / 'examples/phase2/index.json')['TC-0004']['source_hash']
            return result
        def lint_contract(base, manifest, case_ids, **kwargs):
            for cid in case_ids:
                manifest['cases'][cid]['spec_lint'] = {'errors': [], 'automatable': 'yes'}
            return {'valid': True, 'cases': {cid: {'errors': []} for cid in case_ids}}
        def preflight(base, manifest, evidence):
            manifest['preflight'] = {'status': 'passed'}
        with patch.object(profiles, 'invoke_login', return_value={}), \
             patch.object(workflow, 'import_excel', side_effect=import_with_matched_hash), \
             patch.object(specs, 'lint', side_effect=lint_contract), \
             patch.object(specs, 'generate', return_value={}) as generate, \
             patch('uia_core.runtime.preflight', side_effect=preflight), \
             patch.object(experience, '_run_ready') as run, \
             patch.object(reports, 'make_report', return_value={}):
            result = experience.go(workbook, 'offline', 'TC-0004')
        case = common.read_json(self.root / 'runs' / result['run_id'] / 'run.json')['cases']['TC-0004']
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[1], ['TC-0004'])
        self.assertEqual(case['registration']['script'], 'runner/tests/generated/TC-0004.spec.ts')
        self.assertEqual(case['script_binding']['selected'], case['registration']['script'])
        self.assertIn('runner/tests/llms-txt.spec.ts', case['script_binding']['duplicates'])
        self.assertTrue(case['duplicate_script_warning'])
        report_metrics = {'checklist_questions': 0, 'checklist_answers': 0, 'mid_run_questions': 0,
                          'unplanned_interventions': 0, 'session_turns': 0,
                          'script_coverage': {'ratio': 1.0}, 'scope_violations': 0,
                          'leak_hits': 0, 'unreviewed_assertion_changes': 0}
        report = reports.opening({'cases': {'TC-0004': case}, 'questions': {}}, report_metrics, {'items': []})
        self.assertIn('重复脚本选择', report[1]['text'])

    def test_session_turn_is_allowed_during_active_batch(self):
        manifest = self.root / 'runs/R/run.json'
        self.m.update(schema_version='uia-run.v1', run_id='R', active_batch={'batch_id': 'B'},
                      delivery={}, contaminated_fixtures=[], preflight={})
        common.save(manifest, self.m)
        args = cli.parser().parse_args(['session-turn', '--run', 'R', '--id', 'turn-1', '--kind', '发起'])
        result = cli.execute(args)
        self.assertEqual(result['session_turns'], 1)
        self.assertEqual(common.read_json(manifest)['interaction_events'][0]['turn_id'], 'turn-1')

    def test_blocked_generation_falls_back_to_legacy_with_reported_duplicate(self):
        shutil.copytree(SOURCE / 'assets/playwright-runner', self.base / 'runner',
                        ignore=shutil.ignore_patterns('node_modules', 'results'))
        for existing in self.m['cases'].values():
            existing['registration'] = None
        self.add_case('TC-0004', [])
        case = self.m['cases']['TC-0004']
        case.update(spec_lint={'errors': []}, spec_generation_blocked='Restore held remote data before generating another version',
                    version='v1')
        with patch.object(workflow, 'case_errors', return_value=([], [])), \
             patch.object(workflow, 'case_version', return_value='v1'):
            result = workflow.bind_specs(self.base, self.m)
        self.assertEqual(case['registration']['script'], 'runner/tests/llms-txt.spec.ts')
        self.assertEqual(case['script_binding']['selected'], case['registration']['script'])
        self.assertEqual(case['script_binding']['duplicates'], ['runner/tests/generated/TC-0004.spec.ts'])
        self.assertIn('generation refused', case['script_binding']['reason'])
        self.assertIn('TC-0004', result['duplicate_warnings'])

    def test_busy_run_error_names_recovery_commands(self):
        manifest = self.root / 'runs/BUSY-RUN/run.json'
        manifest.parent.mkdir(parents=True)
        common.atomic_write(manifest, {'schema_version': 'uia-run.v1', 'run_id': 'BUSY-RUN'})
        import fcntl
        with patch('uia_core.common.time.monotonic', side_effect=[0, 11]), \
             patch('uia_core.common.time.sleep'), \
             patch.object(fcntl, 'flock', side_effect=BlockingIOError):
            with self.assertRaisesRegex(common.UiaError, r'BUSY-RUN.*go or run-batch.*wait --run BUSY-RUN.*status --run BUSY-RUN'):
                with common.locked_run(manifest):
                    pass

    def test_remote_checklist_does_not_gate_public_or_delayed_cases(self):
        import yaml
        for cid in ('TC-0033', 'TC-0055'):
            self.add_case(cid, ['public_frontend'] if cid == 'TC-0033' else ['delayed_save'])
            target=self.base/'cases'/cid/'case-spec.yaml'
            spec=common.read_yaml(target)
            spec['steps']=[{'id':'S1','verb':'defer_public' if cid=='TC-0033' else 'network_delay','target':'public.llms'}]
            target.write_text(yaml.safe_dump(spec, allow_unicode=True))
        result=experience.rows(self.base,self.m)
        self.assertFalse(any(row['key'] in {'env:public_frontend','env:delayed_save'} for row in result))
        text=experience.checklist_text({'entries': result})
        self.assertIn('公开文件检查在远程执行，不挂起关联用例',text)

    def test_remote_statuses_have_chinese_report_and_metrics(self):
        self.m['cases']['T2'].update(result='remote_unreachable',work_status='remote_pending')
        self.m['remote_checks']={'a':{'status':'unreachable'},'b':{'status':'pass','active':False}}
        flow=metrics.calculate(self.base,self.m)
        self.assertEqual(flow['remote_checks']['unreachable'],1)
        self.assertEqual(flow['remote_checks']['pass'],0)
        text=reports.opening(self.m,flow,{'items':[]})[0]['text']
        self.assertIn('远程不可达或无法验证',text)
        self.assertNotIn('remote_',text)


class DisabledStateTests(unittest.TestCase):
    def test_blocked_save_is_observation_and_native_or_aria_disabled(self):
        env, data, pages = specs.catalogs()
        spec = common.read_yaml(SOURCE / 'examples/phase2/TC-0048/case-spec.yaml')
        source = {'case_id': 'TC-0048', 'expected': [a['excel'] for a in spec['assertions']]}
        self.assertEqual(specs.schema_errors(spec, source, env, data, pages)[0], [])
        spec['steps'][1]['verb'] = 'click'
        self.assertTrue(specs.schema_errors(spec, source, env, data, pages)[0])
        spec['steps'][1]['verb'] = 'assert'
        spec['assertions'][0]['excel'] = '无法保存，按钮置灰'
        source['expected'].append('无法保存，按钮置灰')
        spec['assertions'][0]['checks'] = [{'target': 'txt.dialog', 'op': 'visible'}]
        self.assertTrue(any('disabled-state' in x for x in specs.schema_errors(spec, source, env, data, pages)[0]))
