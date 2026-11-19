import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uia_core import assertions, common, process_issues, remote_checks, rounds, workflow, profiles
from uia_core.experience import checklist_text
from uia_core.preconditions import set_prep_method


class GenericPilotGapsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def test_api_list_keyword_matching_is_offline_and_generic(self):
        catalog = self.root / 'open-api.md'
        catalog.write_text('# Open API\n\n## Create FAQ\nPOST /faq/create\n\n## Site overview\nGET /site/overview\n\n## Create order\nPOST /orders/create\n', encoding='utf-8')
        found = remote_checks  # Make the input/output boundary explicit: no network client is involved.
        del found
        from uia_core.preconditions import api_candidates
        matches = api_candidates('首页网站概述', ['overview'], catalog)
        self.assertTrue(any('site/overview' in line for line in matches))
        self.assertFalse(api_candidates('未知业务', [], None))
        manifest = {'config': {}, 'cases': {}, 'precondition_catalog': {'raw:order': {'label': '创建订单', 'match': ['order']}}}
        selected = set_prep_method(self.root, manifest, 'raw:order', 'api', catalog)
        self.assertTrue(selected['api_candidates'])
        projected = common.read_yaml(self.root / 'preconditions.yaml')
        self.assertEqual(projected['preconditions']['raw:order']['prep_method'], 'api')

    def test_user_preset_items_appear_once_in_a_single_batch_section(self):
        label = '站点首页语言'
        rendered = checklist_text({'entries': [{'key': 'env:language', 'block': 'A', 'label': label,
            'cases': ['C1', 'C2'], 'options': ['可用', '缺少'], 'prep_method': 'user_preset'}], 'answer': {'entries': {}}})
        self.assertEqual(rendered.count(label), 1)
        self.assertIn('每个需求一次性预置的数据（集中确认）', rendered)

    def test_process_issue_summary_classifies_unrun_and_repeated_steps(self):
        base = self.root
        for cid in ('A', 'B'):
            folder = base / 'cases' / cid
            folder.mkdir(parents=True)
            (folder / 'case-spec.yaml').write_text(
                f"schema_version: case-spec.v1\ncase_id: {cid}\nsteps:\n  - {{id: S1, verb: click, target: menu.settings}}\n",
                encoding='utf-8')
        m = {'run_id': 'R', 'interaction_events': [{'kind': 'checklist_answer', 'at': 'now'}],
             'questions': {}, 'cases': {
                 'A': {'case_spec': 'cases/A/case-spec.yaml', 'work_status': 'pending', 'attempts': [], 'classification': {'reason': '缺少数据'}},
                 'B': {'case_spec': 'cases/B/case-spec.yaml', 'work_status': 'pending', 'attempts': [{'prep_time_ms': 12, 'precondition_check': 'not_satisfied', 'preparation': 'prepared'}]},
             }}
        report = process_issues.build(base, m, {'unplanned_interventions': 0, 'human_interventions': 1})
        self.assertEqual(report['human_intervention_count'], 1)
        self.assertEqual(report['data_prep_time_ms_total'], 12)
        self.assertEqual(report['not_run_cases'][0]['reason'], '缺少数据')
        self.assertEqual(report['common_step_candidates'][0]['target'], 'menu.settings')
        self.assertIn('公共步骤候选', process_issues.markdown(report))

    def test_confirmed_expectations_require_an_executed_assertion_and_evidence(self):
        spec = {'assertions': [{'id': 'A1', 'checks': [{'op': 'text'}]}]}
        self.assertFalse(assertions.assess(spec, {'assertions': []})['complete'])
        no_evidence = {'assertions': [{'id': 'A1', 'passed': True, 'evidence': {}}]}
        self.assertFalse(assertions.assess(spec, no_evidence)['complete'])
        proven = {'assertions': [{'id': 'A1', 'passed': True, 'evidence': {
            'source': 'playwright-reporter', 'started_at': '2026-01-01T00:00:00Z'}}]}
        self.assertTrue(assertions.assess(spec, proven)['complete'])
        remote_spec = {'assertions': [{'id': 'A2', 'checks': [{'op': 'remote_file'}]}]}
        self.assertFalse(assertions.assess(remote_spec, {'assertions': []})['complete'])
        deferred = {'deferred_assertions': [{'id': 'A2', 'recorded': True,
            'evidence': {'source': 'remote-check-request'}}]}
        self.assertTrue(assertions.assess(remote_spec, deferred)['complete'])

    def test_frontend_bundle_is_a_playwright_bundle_and_keeps_request_hash(self):
        base = self.root / 'runs' / 'R'
        remote_dir = base / 'remote-checks'
        remote_dir.mkdir(parents=True)
        request = {'schema_version': 'uia-remote-request.v1', 'run_id': 'R', 'checks': [
            {'id': 'c1', 'case_id': 'C1', 'assertion_id': 'A1', 'category': 'frontend',
             'url': 'https://example.invalid/public.txt', 'method': 'GET', 'conditions': [{'op': 'contains', 'value': 'hello'}],
             'saved_at': '2026-01-01T00:00:00+00:00', 'earliest_check_at': '2026-01-01T01:00:00+00:00',
             'deadline': '2026-01-01T02:00:00+00:00', 'timeout_ms': 10000}]}
        common.atomic_write(remote_dir / 'request.json', request)
        result = remote_checks.export_frontend_bundle(base, {'run_id': 'R', 'config': {}})
        self.assertEqual(result['request_sha256'], common.file_hash(remote_dir / 'request.json'))
        self.assertTrue((Path(result['directory']) / 'tests/frontend.spec.mjs').is_file())
        self.assertIn("process.env.UIA_SITE_BASE_URL", (Path(result['directory']) / 'tests/frontend.spec.mjs').read_text())
        self.assertTrue((Path(result['directory']) / 'playwright.config.mjs').read_text().startswith('import { defineConfig'))
        for source in [Path(result['directory']) / 'tests/frontend.spec.mjs', Path(result['directory']) / 'playwright.config.mjs']:
            checked = subprocess.run(['node', '--check', str(source)], capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertTrue(Path(result['zip']).is_file())
        self.assertNotIn('.auth', json.dumps([p.name for p in Path(result['directory']).rglob('*')]))

    def test_round_create_carries_confirmed_spec_and_marks_only_prior_pass_as_reused(self):
        root = self.root
        prior = root / 'runs' / 'REQ-r1'
        (prior / 'cases' / 'PASS').mkdir(parents=True)
        (prior / 'cases' / 'RETRY').mkdir(parents=True)
        (prior / 'runner' / 'knowledge').mkdir(parents=True)
        (prior / 'runner' / 'knowledge' / 'network.yaml').write_text('rules: {}\n', encoding='utf-8')
        (root / 'assets' / 'playwright-runner' / 'tests').mkdir(parents=True)
        (root / 'assets' / 'playwright-runner' / 'tests' / 'pass.spec.ts').write_text('test', encoding='utf-8')
        source = {'case_id': 'PASS', 'title': 'confirmed source'}
        spec = 'schema_version: case-spec.v1\ncase_id: PASS\n'
        for cid, result, script in [('PASS', 'passed', 'runner/tests/pass.spec.ts'), ('RETRY', 'business_failure', None)]:
            folder = prior / 'cases' / cid
            common.atomic_write(folder / 'source.json', source)
            common.atomic_write(folder / 'case-spec.yaml', spec.replace('PASS', cid), as_yaml=False)
        manifest = {'schema_version': 'uia-run.v1', 'run_id': 'REQ-r1', 'config': {'environment': {'id': 'p'}},
                    'cases': {
                        'PASS': {'case_id': 'PASS', 'source': 'cases/PASS/source.json', 'case_spec': 'cases/PASS/case-spec.yaml',
                                 'source_hash': 'x', 'result': 'passed', 'registration': {'script': 'runner/tests/pass.spec.ts',
                                 'fixture': {'hooks': 'fixtures/case-spec.mjs', 'mutates': False}}, 'isolated': False,
                                 'fixture_ids': [], 'flow_ids': [], 'attempts': []},
                        'RETRY': {'case_id': 'RETRY', 'source': 'cases/RETRY/source.json', 'case_spec': 'cases/RETRY/case-spec.yaml',
                                  'source_hash': 'y', 'result': 'business_failure', 'registration': None, 'attempts': []},
                    }, 'sources': [], 'identity_map': {}, 'questions': {'pre': {'subject': 'run-preconditions',
                        'entries': [{'key': 'env:setup', 'prep_method': 'user_preset'}],
                        'answer': {'entries': {'env:setup': True}}}}, 'precondition_catalog': {'raw:setup': {'label': 'setup', 'prep_method': 'user_preset'}}}
        common.atomic_write(prior / 'run.json', manifest)

        def fake_init(run_id, _config):
            new = root / 'runs' / run_id
            (new / 'state').mkdir(parents=True)
            common.atomic_write(new / 'run.json', {'schema_version': 'uia-run.v1', 'run_id': run_id,
                'config': {'environment': {'id': 'gray'}}, 'cases': {}, 'sources': [], 'identity_map': {}, 'history': []})

        with patch.object(common, 'ROOT', root), patch.object(rounds, 'ROOT', root), \
             patch.object(workflow, 'ROOT', root), patch.object(workflow, 'init', side_effect=fake_init), \
             patch.object(profiles, 'profile_path', return_value='fake-profile'):
            output = rounds.create('REQ-r1', 2, 'REQ-r2-gray', 'gray-profile')
        self.assertEqual(output['reused_scripts'], ['PASS'])
        self.assertEqual(output['re_explore'], ['RETRY'])
        created = common.read_json(root / 'runs' / 'REQ-r2-gray' / 'run.json')
        self.assertEqual(created['round']['environment'], 'gray')
        self.assertEqual(created['round_memory']['user_preset_answers'], {'env:setup': True})
        self.assertIn('raw:setup', created['precondition_catalog'])
        self.assertEqual(created['cases']['PASS']['attempts'], [])
        self.assertTrue((root / 'runs' / 'REQ-r2-gray' / 'cases' / 'PASS' / 'case-spec.yaml').is_file())
        created['cases']['PASS']['result'] = 'passed'
        created['cases']['RETRY']['result'] = 'passed'
        common.atomic_write(root / 'runs' / 'REQ-r2-gray' / 'run.json', created)
        with patch.object(common, 'ROOT', root), patch.object(rounds, 'ROOT', root):
            comparison = rounds.compare('REQ-r2-gray')
        self.assertEqual(comparison['pass_delta'], 1)
        self.assertEqual(comparison['scripts_reused'], ['PASS'])
        self.assertEqual(comparison['scripts_re_explored'], ['RETRY'])


if __name__ == '__main__':
    unittest.main()
