import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from uia_core import common, review_page, runtime, remote_checks


class AssertionEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.directory = self.base / 'batches/B'
        self.frozen = self.directory / 'snapshot/cases.json'
        self.ids = ['Good', 'Bad']
        self.binding = {'spec': {'assertions': [
            {'id': 'A1', 'excel': '窗口显示', 'checks': [{'op': 'visible'}]},
            {'id': 'A2', 'excel': '数量是两条', 'checks': [{'op': 'count'}]},
        ]}, 'assertion_methods': {'A2': [{'review_id': 'review-count', 'method': '统计结果行'}]}}
        self.passed = [{'id': 'A1', 'passed': True}, {'id': 'A2', 'passed': True, 'observations': [2]}]
        self.m = {'run_id': 'run', 'history': [], 'batches': [], 'questions': {}, 'contaminated_fixtures': {},
                  'config': {'targets': {'public': 'https://example.test'},
                             'execution': {'stability_passes': 1, 'repair_rounds': 0}},
                  'cases': {cid: {'case_id': cid, 'pass_streak': 0, 'attempts': [], 'repair_rounds': 0,
                                  'fixture_ids': [], 'registration': {'case_spec': True, 'fixture': {'mutates': False}}}
                            for cid in self.ids}}

    def consume(self, assertions, result='passed', remote=None, remote_binding=None, hold=False):
        common.atomic_write(self.frozen, {'Good': self.binding, 'Bad': remote_binding or self.binding})
        self.m['active_batch'] = {'id': 'B', 'directory': 'batches/B', 'report': 'batches/B/case-results.json',
                                  'case_ids': self.ids, 'versions': dict.fromkeys(self.ids, 'v'),
                                  'cases_snapshot_sha256': common.file_hash(self.frozen), 'assertion_evidence_version': 1}
        if remote is not None:
            common.atomic_write(self.directory / 'remote-Bad.json', remote)
        rows = []
        for cid, outcome, evidence in [('Good', 'passed', self.passed), ('Bad', result, assertions)]:
            pending = hold and cid == 'Bad'
            if pending:
                self.m['cases'][cid]['registration']['fixture']['mutates'] = True
            rows.append({'case_id': cid, 'result': outcome, 'retry': 0, 'playwright_status': 'passed' if outcome == 'passed' else 'failed',
                         'setup_started': True, 'assertions': evidence,
                         'lifecycle': {'batch_id': 'B', 'setup_verified': True, 'cleanup_verified': not pending, 'cleanup_pending': pending}})
        common.atomic_write(self.directory / 'case-results.json', {'schema_version': 'uia-batch-results.v1', 'batch_id': 'B',
                                                                   'complete': True, 'cases': rows})
        with patch.object(runtime, 'case_version', return_value='v'), patch('uia_core.workflow.absorb_locators'):
            runtime.consume_batch(self.base, self.m)
        self.assertEqual(self.m['cases']['Good']['result'], 'passed')
        return self.m['cases']['Bad']

    def test_missing_assertion_only_fails_the_affected_case(self):
        case = self.consume(self.passed[:1])
        self.assertEqual(case['result'], 'automation_failure')
        self.assertEqual(case['attempts'][-1]['assertion_evidence'][1]['status'], 'not_run')
        self.assertIn('A2 回执缺失', case['attempts'][-1]['assertion_evidence_errors'])

    def test_duplicate_wrong_id_and_missing_observation_prevent_a_pass(self):
        case = self.consume([self.passed[0], self.passed[0], {'id': 'A2', 'passed': True}, {'id': 'A3', 'passed': True}])
        self.assertEqual(case['result'], 'automation_failure')
        self.assertEqual(case['attempts'][-1]['assertion_evidence_errors'],
                         ['本地回执编号不符 A3', 'A1 回执重复', 'A2 缺少关键观察值'])

    def test_preserve_business_failure(self):
        case = self.consume([{'id': 'A1', 'passed': False}], 'business_failure')
        self.assertEqual(case['result'], 'business_failure')
        self.assertEqual([r['status'] for r in case['attempts'][-1]['assertion_evidence']], ['failed', 'not_run'])

    def test_preserve_locator_failure(self):
        case = self.consume([], 'automation_failure')
        self.assertEqual(case['result'], 'automation_failure')
        self.assertNotIn('assertion_evidence_errors', case['attempts'][-1])

    def remote_setup(self):
        condition = {'op': 'contains', 'value': 'hello'}
        binding = {'spec': {'assertions': [self.binding['spec']['assertions'][0],
                   {'id': 'A2', 'excel': '公开文件更新', 'checks': [{'op': 'remote_file', 'value': condition}]}]},
                   'remote_resources': {'A2': {'path': '/test.txt'}}}
        row = {'assertion_id': 'A2', 'expected': '公开文件更新', 'method': 'GET', 'url': 'https://example.test/test.txt',
               'saved_at': common.now(), 'conditions': [condition]}
        self.m['cases']['Bad']['version'] = 'v'
        return binding, row

    def test_missing_remote_request_cannot_pass(self):
        binding, _ = self.remote_setup()
        case = self.consume(self.passed[:1], remote_binding=binding)
        self.assertEqual(case['result'], 'automation_failure')
        self.assertFalse(self.m.get('remote_checks'))

    def test_remote_request_must_use_frozen_condition(self):
        binding, row = self.remote_setup()
        case = self.consume(self.passed[:1], remote_binding=binding,
                            remote=[{**row, 'conditions': [{'op': 'contains', 'value': '.'}]}])
        self.assertEqual(case['result'], 'automation_failure')
        self.assertFalse(self.m.get('remote_checks'))

    def test_invalid_handoff_keeps_a_restorable_lease_and_blocks_its_fixture(self):
        binding, row = self.remote_setup()
        case = self.consume(self.passed[:1], remote_binding=binding, remote=[row, row], hold=True)
        self.assertEqual(case['result'], 'automation_failure')
        self.assertTrue(case['attempts'][-1]['cleanup_pending'])
        self.assertIn('case:Bad', self.m['contaminated_fixtures'])
        self.assertFalse(self.m.get('remote_checks'))

    def test_valid_remote_receipt_requires_restoration_to_pass(self):
        binding, row = self.remote_setup()
        case = self.consume(self.passed[:1], remote_binding=binding, remote=[row])
        self.assertEqual(case['result'], 'remote_pending')
        entry = next(iter(self.m['remote_checks'].values()))
        case['attempts'][-1]['cleanup_verified'] = False
        entry['status'] = 'pass'
        remote_checks.fold(self.m, 'Bad')
        self.assertEqual(case['result'], 'remote_pending')
        case['attempts'][-1]['cleanup_verified'] = True
        remote_checks.fold(self.m, 'Bad')
        self.assertEqual(case['result'], 'passed')


class ReviewEvidenceBindingTests(unittest.TestCase):
    def test_reviewed_method_binds_only_to_the_exact_source_expectation(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            common.atomic_write(base / 'source.json', {'expected': ['窗口显示', '数量是两条']})
            common.atomic_write(base / 'case.yaml', {'assertions': [{'id': 'A2', 'excel': '数量是两条'}]}, as_yaml=True)
            run = {'run_id': 'R', 'history': [], 'questions': {}, 'cases': {'C': {'case_id': 'C', 'source': 'source.json', 'case_spec': 'case.yaml'}}}
            inp = {'id': 'check-count', 'title': '核对行数', 'cases': ['C'], 'checks': ['统计结果行，正好两条'], 'expectations': {'C': '数量是两条'}}
            common.atomic_write(base / 'review-input.json', {'checks': [inp]})
            payload = review_page._payload(base, run)
            self.assertEqual(payload['checks'][0]['expectations']['C'], '数量是两条')
            common.atomic_write(base / 'answer.json', {'review_version': 1, 'run_id': 'R', 'revision': payload['revision'],
                                'decisions': [{'review_id': inp['id'], 'case_ids': ['C'], 'status': 'confirmed', 'value': inp['checks'][0]}]})
            review_page.ingest(base, run, base / 'answer.json')
            with patch('uia_core.specs.lint', return_value={'errors': [], 'cases': {'C': {'errors': []}}}):
                result = review_page.bind_case(base, run, 'C', [inp['id']])
                self.assertEqual(result['review_binding']['assertion_methods']['A2'][0]['method'], inp['checks'][0])
                common.atomic_write(base / 'case.yaml', {'assertions': [{'id': 'A2', 'excel': '窗口显示'}]}, as_yaml=True)
                with self.assertRaises(common.UiaError):
                    review_page.bind_case(base, run, 'C', [inp['id']])
