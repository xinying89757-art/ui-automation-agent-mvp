"""Environment preflight, failure classes, report metrics, smoke gate, and two defect fixes."""
import datetime as dt
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from openpyxl import Workbook

from uia_core import cli, common, entries, experience, knowledge, metrics, profiles, reports, smoke, specs, workflow
from uia_core.actions import key_from_phrase, normalize_route_step
from uia_core.failure_class import case_class, failure_class, shares
from uia_core.preflight_gate import block_batch, ensure_environment

SOURCE = Path(__file__).resolve().parents[1]


class FailureClassTests(unittest.TestCase):
    def test_site_not_found_login_and_site_load_timeout_are_environment(self):
        for text in ('SITE_NOT_ACCESSIBLE', '当前账号下未找到目标网站', 'LOGIN_FAILED 登录未完成',
                     'page.goto: Timeout 30000ms exceeded.', 'net::ERR_CONNECTION_REFUSED', '环境不可达'):
            self.assertEqual(failure_class(text), 'environment', text)
        self.assertEqual(failure_class('Timeout 10000ms exceeded.\nwaiting for locator("#save")'), 'automation')
        self.assertEqual(failure_class('UIA_BUSINESS_FAILURE expected 管理txt文件'), 'product')
        self.assertEqual(failure_class('缺控件：保存按钮'), 'suspended')
        env = {'result': 'automation_failure', 'attempts': [{'errors': ['未找到目标网站']}]}
        self.assertEqual(case_class(env), 'environment')
        product = {'result': 'save_not_persisted', 'attempts': []}
        self.assertEqual(case_class(product), 'product')
        counted = shares([env, product, {'result': 'automation_failure', 'attempts': [{'errors': ['locator miss']}]},
                          {'result': 'suspended', 'attempts': []}])
        self.assertEqual(counted['environment']['count'], 1)
        self.assertEqual(counted['product']['share'], 0.25)
        self.assertEqual(counted['suspended']['count'], 1)


class ActionTests(unittest.TestCase):
    def test_press_enter_is_not_a_click(self):
        self.assertEqual(key_from_phrase('press Enter'), 'Enter')
        self.assertEqual(key_from_phrase('按回车'), 'Enter')
        self.assertEqual(key_from_phrase('click:text=press Enter'), 'Enter')
        self.assertIsNone(key_from_phrase('设置'))
        self.assertIsNone(key_from_phrase('Enter'))
        self.assertEqual(normalize_route_step('press Enter'), 'press:Enter')
        self.assertEqual(normalize_route_step('click:text=按回车'), 'press:Enter')
        self.assertEqual(normalize_route_step({'verb': 'click', 'target': 'press Enter'}),
                         {'verb': 'press', 'target': 'Enter', 'value': 'Enter'})

    def test_navigation_hint_compiles_press_enter(self):
        route = entries.navigation_hint({'path_text': '网站编辑 → press Enter'})
        self.assertEqual(route['node'], 'editor')
        self.assertEqual(route['steps'], ['press:Enter'])
        chinese = entries.navigation_hint({'path_text': '内容管理 → 产品 → 按回车'})
        self.assertEqual(chinese['steps'], ['click:text=产品', 'press:Enter'])

    def test_generated_click_of_press_enter_uses_keyboard(self):
        spec = {
            'schema_version': 'case-spec.v1', 'case_id': 'T1', 'intent': '按下回车',
            'automatable': {'status': 'yes', 'reason': 'known'}, 'required_env': [],
            'data_prep': {}, 'mutation_scope': [], 'start_page': 'editor',
            'steps': [{'id': 'S1', 'verb': 'click', 'target': 'txt.dialog', 'value': 'press Enter'}],
            'assertions': [{'id': 'A1', 'after': 'S1', 'excel': '1. 弹窗显示管理txt文件。',
                            'checks': [{'target': 'txt.dialog', 'op': 'visible'}]}], 'questions': []}
        source = {'case_id': 'T1', 'expected': ['1. 弹窗显示管理txt文件。']}
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            folder = base / 'cases/T1'
            folder.mkdir(parents=True)
            shutil.copytree(SOURCE / 'assets/playwright-runner', base / 'runner',
                            ignore=shutil.ignore_patterns('node_modules', 'results'))
            common.atomic_write(folder / 'source.json', source)
            common.atomic_write(folder / 'case-spec.yaml', spec, as_yaml=True)
            manifest = {'run_id': 'R', 'cases': {'T1': {'case_id': 'T1', 'source': 'cases/T1/source.json',
                        'case_spec': 'cases/T1/case-spec.yaml', 'source_hash': 'hash', 'attempts': [],
                        'intent': 'cases/T1/source.json', 'reuse_plan': 'cases/T1/source.json',
                        'fixture_ids': [], 'flow_ids': []}},
                        'config': {'mutation': {'allowed': False, 'scope': []},
                                   'execution': {'workers': 1, 'timeout_ms': 60000}},
                        'questions': {}, 'history': []}
            generated = specs.generate(base, manifest, 'T1')
            body = (base / generated['script']).read_text(encoding='utf-8')
        self.assertIn('page.keyboard.press("Enter")', body)
        self.assertNotIn('.click()', body)


class PromoteDefectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        know = self.tmp / 'assets/playwright-runner/knowledge'
        know.mkdir(parents=True)
        (know / 'entries.yaml').write_text('schema_version: entry-hints.v1\nentries: {}\n', encoding='utf-8')
        (know / 'page-map.yaml').write_text(
            'schema_version: page-map.v1\npages: {content-admin: {entry: 内容管理}}\ntargets: {}\n', encoding='utf-8')
        self.base = self.tmp / 'run'
        (self.base / 'exploration').mkdir(parents=True)
        (self.base / 'cases/C1').mkdir(parents=True)
        (self.base / 'cases/C1/case-spec.yaml').write_text(
            'start_page: content-admin\nsteps:\n  - id: S1\n    verb: click\n    target: ?faq_editor.add\n',
            encoding='utf-8')
        self.patch = patch.object(common, 'ROOT', self.tmp)
        self.patch.start()
        self.m = {'config': {}, 'cases': {'C1': {'case_id': 'C1', 'case_spec': 'cases/C1/case-spec.yaml'}},
                  'history': []}
        entries.add(self.m, '新版内容编辑器=内容管理 → 产品')

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.tmp)

    def test_underscore_target_and_press_enter_route(self):
        report = {'purpose': 'faq', 'entry': '新版内容编辑器', 'route': {
            'reached': True, 'reached_entry': True,
            'route': ['press Enter', {'verb': 'click', 'target': '按回车'}],
            'targets': {},
            'step_targets': [{'case_id': 'C1', 'step_id': 'S1', 'placeholder': '?faq_editor.add',
                              'target': 'faq_editor.add', 'locator': {'text': '添加'}, 'verified': True,
                              'match_count': 1}],
            'case_targets': [{'case_id': 'C1', 'targets': ['?faq_editor.add']}]}}
        (self.base / 'exploration/generator-faq.json').write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
        # case_targets on the report root is what promote reads.
        report['case_targets'] = [{'case_id': 'C1', 'targets': ['?faq_editor.add']}]
        (self.base / 'exploration/generator-faq.json').write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
        result = entries.promote(self.base, self.m, 'exploration/generator-faq.json')
        self.assertEqual(result['route_steps'], ['press:Enter', 'press:Enter'])
        self.assertEqual(result['placeholder_bindings']['?faq_editor.add'], 'faq_editor.add')
        catalog = common.read_yaml(self.tmp / 'assets/playwright-runner/knowledge/page-map.yaml')
        self.assertIn('faq_editor.add', catalog['targets'])


class SmokeAndPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(module, 'ROOT', self.root) for module in (common, experience, workflow, profiles)]
        for item in self.patches:
            item.start()
        shutil.copytree(SOURCE / 'assets', self.root / 'assets', ignore=shutil.ignore_patterns('node_modules', 'results'))
        (self.root / 'examples/phase2').mkdir(parents=True)
        (self.root / 'examples/phase2/index.json').write_text('{}', encoding='utf-8')
        self.auth = self.root / 'private.json'
        common.atomic_write(self.auth, {'account': 'fake-user', 'password': 'fake-password'})
        profiles.setup('offline', 'production', 'en.example.test', credentials_file=self.auth)

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.temp.cleanup()

    def workbook(self, rows, name='cases.xlsx'):
        path = self.root / name
        wb = Workbook()
        ws = wb.active
        ws.append(['用例ID', '模块', '优先级', '用例标题', '前置条件', '操作步骤', '预期结果'])
        for row in rows:
            ws.append(row)
        wb.save(path)
        return path

    def test_pick_is_representative_and_gate_holds_the_rest(self):
        cases = {
            'A2': {'priority': 'P1', 'module': '产品'},
            'A1': {'priority': 'P0', 'module': '产品'},
            'B1': {'priority': 'P0', 'module': '文章'},
            'C1': {'priority': 'P2', 'module': '设置'},
        }
        self.assertEqual(smoke.pick_smoke_cases(cases, 3), ['A1', 'B1', 'C1'])
        manifest = {'cases': {cid: {'result': None, 'work_status': 'runnable'} for cid in cases},
                    'history': [], 'selected_cases': list(cases), 'max_first_result_minutes': 26}
        for cid, row in cases.items():
            manifest['cases'][cid].update(row, case_id=cid)
        plan = smoke.plan_smoke(manifest, 3, 1)
        self.assertEqual(plan['status'], 'pending')
        self.assertEqual(smoke.allowed_cases(manifest, ['A1', 'A2', 'B1', 'C1']), ['A1', 'B1', 'C1'])
        for cid in plan['cases']:
            manifest['cases'][cid]['result'] = 'passed'
        manifest['cases']['A2']['result'] = None
        smoke.update_smoke(manifest)
        self.assertEqual(plan['status'], 'passed')
        self.assertEqual(smoke.allowed_cases(manifest, ['A2']), ['A2'])
        manifest['smoke_plan'] = {'status': 'pending', 'cases': ['A1', 'B1', 'C1'], 'bar': 1, 'size': 3}
        for cid in ('A1', 'B1', 'C1'):
            manifest['cases'][cid]['result'] = 'automation_failure'
        smoke.update_smoke(manifest)
        self.assertEqual(manifest['abort']['reason'], 'smoke_below_bar')
        self.assertEqual(smoke.allowed_cases(manifest, ['A2']), [])

    def test_first_result_over_26_minutes_aborts_and_a_fast_result_does_not(self):
        start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=30)).isoformat()
        slow = {'history': [], 'execution_started_at': start, 'max_first_result_minutes': 26, 'cases': {}}
        self.assertEqual(smoke.abort_reason(slow)['reason'], 'first_result_exceeded')
        fast_start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=10)).isoformat()
        fast = {'history': [], 'execution_started_at': fast_start, 'max_first_result_minutes': 26,
                'first_result_at': (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=9)).isoformat(),
                'cases': {}}
        self.assertIsNone(smoke.abort_reason(fast))

    def test_go_blocks_the_batch_when_the_site_is_missing(self):
        book = self.workbook([
            ['TC-1', '产品', 'P0', '窗口', '', '打开', '显示'],
            ['TC-2', '文章', 'P1', '列表', '', '打开', '显示'],
        ])
        calls = []

        def refused(*_args, **_kwargs):
            calls.append('run')

        with patch.object(profiles, 'invoke_login', side_effect=common.UiaError('SITE_NOT_ACCESSIBLE 未找到目标网站')), \
                patch.object(experience, '_run_ready', side_effect=refused), \
                patch.object(reports, 'make_report', return_value={'artifacts': {}}):
            result = experience.go(book, 'offline')
        self.assertEqual(calls, [])
        self.assertEqual(result['batch_outcome'], 'environment_blocked')
        self.assertEqual(result['failure_class'], 'environment')
        manifest = json.loads((self.root / 'runs' / result['run_id'] / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['batch_outcome'], 'environment_blocked')
        self.assertTrue(all(case['result'] == 'environment_blocked' and case['failure_class'] == 'environment'
                            for case in manifest['cases'].values()))
        self.assertNotIn('fake-password', json.dumps(result, ensure_ascii=False))
        self.assertIn('未找到目标网站', result['reason'])

    def test_go_smoke_runs_three_representatives_before_the_rest(self):
        book = self.workbook([
            ['A1', '产品', 'P0', '甲', '', '打开', '显示'],
            ['A2', '产品', 'P1', '乙', '', '打开', '显示'],
            ['B1', '文章', 'P0', '丙', '', '打开', '显示'],
            ['C1', '设置', 'P2', '丁', '', '打开', '显示'],
        ])
        calls = []

        def bind(base, manifest):
            for case in manifest['cases'].values():
                case.update(work_status='runnable', stage='execution',
                            registration={'script': 'runner/tests/generated/x.spec.ts', 'fixture': {'mutates': False}})
            return {'bound': list(manifest['cases'])}

        def run_ready(manifest, ready):
            calls.append(list(ready))
            with common.locked_run(manifest) as (path, manifest_state):
                for cid in ready:
                    manifest_state['cases'][cid].update(result='passed', work_status='finished', stage='finished',
                                                       attempts=[{'executed': True, 'result': 'passed'}])
                manifest_state.setdefault('first_result_at', common.now())
                manifest_state.setdefault('execution_started_at', common.now())
                common.save(path, manifest_state)

        def passed_preflight(base, manifest, evidence):
            manifest['preflight'] = {'status': 'passed', 'config_hash': manifest.get('config_hash')}

        with patch.object(profiles, 'invoke_login', return_value={
                'status': 'authenticated', 'editor': {'opened': True},
                'site': {'reachable': True, 'selected': True},
                'targets': {'admin': {'selected_site': 'en.example.test', 'selection': 'card'}}}), \
                patch('uia_core.runtime.preflight', side_effect=passed_preflight), \
                patch.object(workflow, 'bind_specs', side_effect=bind), \
                patch.object(experience, '_run_ready', side_effect=run_ready), \
                patch.object(reports, 'make_report', return_value={'artifacts': {}}):
            result = experience.go(book, 'offline', smoke_size=3, smoke_bar=1)
        self.assertEqual(calls[0], ['A1', 'B1', 'C1'])
        self.assertEqual(calls[1], ['A2'])
        self.assertNotIn('batch_outcome', result)
        failed = []

        def fail_ready(manifest, ready):
            failed.append(list(ready))
            with common.locked_run(manifest) as (path, manifest_state):
                for cid in ready:
                    manifest_state['cases'][cid].update(result='automation_failure', work_status='finished',
                                                       failure_class='automation', attempts=[{'executed': True}])
                manifest_state.setdefault('first_result_at', common.now())
                manifest_state.setdefault('execution_started_at', common.now())
                common.save(path, manifest_state)

        book2 = self.workbook([
            ['D1', '产品', 'P0', '甲', '', '打开', '显示'],
            ['D2', '产品', 'P1', '乙', '', '打开', '显示'],
            ['E1', '文章', 'P0', '丙', '', '打开', '显示'],
            ['F1', '设置', 'P2', '丁', '', '打开', '显示'],
        ], name='cases-stop.xlsx')
        with patch.object(profiles, 'invoke_login', return_value={}), \
                patch('uia_core.runtime.preflight', side_effect=passed_preflight), \
                patch.object(workflow, 'bind_specs', side_effect=bind), \
                patch.object(experience, '_run_ready', side_effect=fail_ready), \
                patch.object(reports, 'make_report', return_value={'artifacts': {}}):
            stopped = experience.go(book2, 'offline', smoke_size=3, smoke_bar=1)
        self.assertEqual(failed, [['D1', 'E1', 'F1']])
        stored = json.loads((self.root / 'runs' / stopped['run_id'] / 'run.json').read_text(encoding='utf-8'))
        self.assertEqual(stored['abort']['reason'], 'smoke_below_bar')
        self.assertIsNone(stored['cases']['D2'].get('result'))

    def test_live_preflight_requires_login_site_and_editor_without_passwords(self):
        book = self.workbook([['TC-1', '产品', 'P0', '窗口', '', '打开', '显示']])
        with patch.object(profiles, 'invoke_login', return_value={}), \
                patch('uia_core.runtime.preflight', side_effect=lambda base, manifest, evidence: manifest.update(
                    preflight={'status': 'passed'})), \
                patch.object(experience, '_run_ready'), \
                patch.object(reports, 'make_report', return_value={'artifacts': {}}):
            started = experience.go(book, 'offline')
        manifest_path = self.root / 'runs' / started['run_id'] / 'run.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        base = manifest_path.parent

        def editor_down(_base, state, _evidence):
            state['preflight'] = {'status': 'passed'}
            return {'status': 'authenticated', 'editor': {'opened': False, 'error': '内容编辑器未打开'},
                    'site': {'reachable': True, 'selected': True}}

        blocked = ensure_environment(base, manifest, probe=editor_down)
        self.assertEqual(blocked['failure_class'], 'environment')
        self.assertEqual(manifest['batch_outcome'], 'environment_blocked')
        self.assertIn('内容编辑器未打开', blocked['reason'])
        args = cli.parser().parse_args(['preflight', '--run', str(manifest_path)])
        self.assertIsNone(args.evidence)
        flags = cli.parser().parse_args(['go', 'a.xlsx', '--smoke-size', '3', '--smoke-bar', '0.5',
                                         '--max-first-result-minutes', '26'])
        self.assertEqual((flags.smoke_size, flags.smoke_bar, flags.max_first_result_minutes), (3, 0.5, 26))


class ReportMetricTests(unittest.TestCase):
    def test_json_and_markdown_include_the_metric_set(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / 'cases/C1').mkdir(parents=True)
            (base / 'cases/C1/case-spec.yaml').write_text(
                'start_page: editor\nsteps:\n  - {id: S1, verb: click, target: txt.entry}\n', encoding='utf-8')
            (base / 'cases/C1/source.json').write_text('{"title":"窗口","expected":["显示"]}', encoding='utf-8')
            common.atomic_write(base / 'knowledge-match.json', {
                'matched': {'C1': {
                    'target.txt.entry': {'id': 'target.txt.entry', 'page': 'editor'},
                    'target.other': {'id': 'target.other', 'page': 'editor'},
                }},
                'budgets': {'C1': {'used_tokens': 10}, 'C2': {'used_tokens': 20}, 'C3': {'used_tokens': 100}},
            })
            started = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=90)).isoformat()
            first = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=30)).isoformat()
            manifest = {
                'run_id': 'R', 'created_at': started, 'sources': [{'imported_at': started}],
                'first_result_at': first, 'exploration': [], 'questions': {}, 'history': [],
                'interaction_events': [{'kind': 'checklist_answer'}, {'kind': 'session_turn', 'category': '计划外'}],
                'checklist_question_count': 1, 'entry_question_count': 0,
                'config': {'execution': {'stability_passes': 1}, 'auth': {}, 'mutation': {'allowed': False, 'scope': []},
                           'environment': {'id': 'production'}},
                'smoke_plan': {'status': 'passed', 'cases': ['C1', 'C2'], 'bar': 1, 'pass_rate': 1, 'size': 3},
                'max_first_result_minutes': 26,
                'cases': {
                    'C1': {'case_id': 'C1', 'title': '窗口', 'module': '产品', 'priority': 'P0', 'sheet': 'S', 'rows': [2],
                           'stage': 'finished', 'work_status': 'finished', 'result': 'passed', 'stability': 'stable',
                           'pass_streak': 1, 'flow_ids': [], 'fixture_ids': [], 'repair_rounds': 0,
                           'attempts': [{'executed': True, 'result': 'passed', 'errors': [], 'evidence': ''}],
                           'case_spec': 'cases/C1/case-spec.yaml', 'source': 'cases/C1/source.json'},
                    'C2': {'case_id': 'C2', 'title': '站点', 'module': '产品', 'priority': 'P1', 'sheet': 'S', 'rows': [3],
                           'stage': 'finished', 'work_status': 'finished', 'result': 'environment_blocked',
                           'failure_class': 'environment', 'stability': 'not_run', 'pass_streak': 0,
                           'flow_ids': [], 'fixture_ids': [], 'repair_rounds': 0,
                           'attempts': [{'executed': True, 'result': 'environment_blocked', 'errors': ['未找到目标网站'], 'evidence': ''}],
                           'classification': {'reason': '未找到目标网站'}, 'source': 'cases/C1/source.json'},
                },
            }
            flow = metrics.calculate(base, manifest)
            self.assertAlmostEqual(flow['time_to_first_result_seconds'], 60, delta=1)
            self.assertEqual(flow['pass_rate'], 0.5)
            self.assertEqual(flow['failure_class_shares']['environment']['share'], 1)
            self.assertEqual(flow['human_interventions'], 2)
            self.assertEqual(flow['human_interventions_per_case'], 1)
            self.assertEqual(flow['kb_hit_rate'], {'retrieved': 2, 'used': 1, 'rate': 0.5})
            self.assertEqual(flow['re_explored_known_pages'], 0)
            self.assertEqual(flow['knowledge_injected_tokens']['p50'], 20)
            self.assertEqual(flow['knowledge_injected_tokens']['p95'], 100)
            text = reports.opening(manifest, flow, {'items': []})[2]['text']
            for phrase in ('首个结果耗时', '通过率', '失败分类占比', '环境', '知识命中率', '已知页面重复探索', 'p50/p95'):
                self.assertIn(phrase, text)
            with patch.object(knowledge, 'ROOT', base), patch.object(common, 'ROOT', base):
                output = reports.make_report(base, manifest)
            payload = json.loads((base / 'reports/results.json').read_text(encoding='utf-8'))
            markdown = (base / 'reports/summary.md').read_text(encoding='utf-8')
            self.assertEqual(payload['schema_version'], 'uia-results.v1')
            self.assertEqual(payload['metrics']['pass_rate'], 0.5)
            self.assertEqual(payload['flow_metrics']['kb_hit_rate']['rate'], 0.5)
            self.assertEqual(payload['cases'][1]['failure_class'] if payload['cases'][1]['case_id'] == 'C2'
                             else payload['cases'][0]['failure_class'], 'environment')
            self.assertIn('失败分类占比', markdown)
            self.assertIn('知识命中率', markdown)
            self.assertTrue(output['artifacts']['json'])


if __name__ == '__main__':
    unittest.main()
