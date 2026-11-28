import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from uia_core import cli, common, review_page, specs, text_requests, workflow


class TextRequestTest(unittest.TestCase):
    def test_partial_answers_and_changed_cases_stay_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config = root / 'profile.json'
            common.atomic_write(config, {'schema_version': 'uia-config.v1'})
            path = root / 'request.json'
            request = {'schema_version': 'uia-text-request.v1', 'kind': 'bug', 'title': '保存结果',
                       'original': '保存成功时显示成功提示。再次打开的要求待确认。', 'historical_actual': '没有显示提示。',
                       'cases': [
                           {'id': 'A', 'title': '成功提示', 'steps': ['点击保存'], 'expectations': [
                               {'quote': '保存成功时显示成功提示。', 'source': 'Bug 描述', 'method': '检查成功提示'}]},
                           {'id': 'B', 'title': '再次打开', 'steps': ['再次打开'],
                            'expectation_question': '再次打开后应显示什么？'},
                       ]}
            with patch.object(workflow, 'ROOT', root):
                workflow.init('Text', config)
            manifest, run = common.load_run(root / 'runs/Text/run.json')
            base = manifest.parent

            def load_request():
                common.atomic_write(path, request)
                workflow.import_request(base, run, path, text_requests.parse(path, 'RQ-test', run['config']))
                return review_page._payload(base, run)

            def submit(payload, decisions):
                return review_page.ingest_payload(base, run, {'run_id': 'Text', 'review_version': 1,
                    'revision': payload['revision'], 'decisions': decisions})

            payload = load_request()
            check, question = payload['checks'][0], payload['questions'][0]
            first, second = check['cases'][0], question['cases'][0]
            confirmed = {'review_id': check['id'], 'case_ids': [first], 'status': 'confirmed', 'value': '检查成功提示'}
            submit(payload, [confirmed])
            workflow.park_cases_with_pending_review(run)
            self.assertNotEqual(run['cases'][first]['work_status'], 'waiting_human')
            self.assertEqual(run['cases'][second]['work_status'], 'waiting_human')
            self.assertIsNone(review_page.approved_expectation(base, run, second))
            answer = {'review_id': question['id'], 'case_ids': [second], 'status': 'edited', 'value': '显示上次内容。'}
            submit(payload, [confirmed, answer])
            workflow.park_cases_with_pending_review(run)
            self.assertEqual(review_page.approved_expectation(base, run, second), answer['value'])
            self.assertEqual(run['cases'][second]['work_status'], 'pending')
            self.assertEqual(specs.expectation_quotes(common.read_json(base / run['cases'][second]['source'])), set())
            original = common.read_json(base / run['sources'][0]['snapshot'])
            self.assertEqual(original, request)

            request['cases'][1]['steps'].append('重新加载一次')
            load_request()
            review_page.reconcile_request_review(base, run)
            self.assertEqual([item['id'] for item in run['human_review']['decisions']], [check['id']])
            self.assertEqual([item['id'] for item in run['human_review']['pending']], [question['id']])
            self.assertIsNone(review_page.approved_expectation(base, run, second))

    def test_go_input_sources_are_exclusive(self):
        args = cli.parser().parse_args(['go', '--request', 'request.json', '--profile', 'pilot'])
        self.assertEqual(args.request, 'request.json')
        self.assertIsNone(args.excel)
        with self.assertRaises(common.UiaError):
            cli.parser().parse_args(['go', 'source.xlsx', '--request', 'request.json'])
