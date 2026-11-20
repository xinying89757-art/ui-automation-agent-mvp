import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uia_core import review_page
from uia_core.common import UiaError, atomic_write, read_json


class ReviewHandoffTest(unittest.TestCase):
    def test_plan_requires_every_decision_case_and_matching_source_hash(self):
        from uia_core.common import file_hash
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            run = {'run_id': 'R', 'cases': {'C1': {}, 'C2': {}}, 'questions': {}, 'history': []}
            atomic_write(base / review_page.RESULT, {'run_id': 'R', 'decisions': [
                {'id': 'Q', 'cases': ['C1', 'C2']}]})
            row = {'review_id': 'Q', 'case_id': 'C1', 'disposition': 'implement',
                   'scope': '产品', 'instruction': '进入产品描述'}
            plan = {'run_id': 'R', 'review_source': review_page.RESULT,
                    'review_source_sha256': file_hash(base / review_page.RESULT), 'items': [row]}
            atomic_write(base / 'plan.json', plan)
            with self.assertRaises(UiaError):
                review_page.validate_plan(base, run, base / 'plan.json')
            plan['items'].append({**row, 'case_id': 'C2', 'disposition': 'partial_exclusion'})
            atomic_write(base / 'plan.json', plan)
            result = review_page.validate_plan(base, run, base / 'plan.json')
            self.assertEqual(result['state'], 'planned_not_applied')
            self.assertEqual(result['items'], 2)
            atomic_write(base / review_page.RESULT, {'run_id': 'R', 'decisions': []})
            with self.assertRaises(UiaError):
                review_page.validate_plan(base, run, base / 'plan.json')

    def test_prototype_migration_checks_mapping_and_keeps_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            run = {'run_id': 'R', 'cases': {'C1': {'title': 'first'}, 'C2': {'title': 'second'}},
                   'questions': {}, 'history': []}
            atomic_write(base / review_page.INPUT, {'questions': [
                {'id': 'entry', 'title': '入口', 'cases': ['C1'], 'answer': '产品'}],
                'checks': [{'id': 'A1', 'title': '结果', 'cases': ['C2'], 'checks': ['显示成功']}]})
            report = {'run_id': 'R', 'review_version': 1, 'decisions': [
                {'review_id': 'old', 'case_ids': ['C1'], 'status': 'confirmed', 'value': '产品'},
                {'review_id': 'A1', 'case_ids': ['C2'], 'status': 'confirmed', 'value': '显示成功'}]}
            atomic_write(base / 'old.json', report)
            atomic_write(base / 'map.json', {'old': 'entry', 'A1': 'A1'})
            out = review_page.ingest_prototype(base, run, base / 'old.json', base / 'map.json')
            decisions = read_json(out['review_decisions'])
            self.assertIsNone(decisions['reviewed_revision'])
            self.assertEqual(decisions['source_kind'], 'unversioned_prototype')
            self.assertNotIn('human_review', run)
            self.assertEqual(read_json(out['review_handoff'])['cases'][0]['decisions'][0]['prototype_id'], 'old')
            report['decisions'][1]['value'] = '内容已改变'
            atomic_write(base / 'old.json', report)
            with self.assertRaises(UiaError):
                review_page.ingest_prototype(base, run, base / 'old.json', base / 'map.json')
            self.assertEqual(read_json(out['review_decisions']), decisions)

    def test_ingest_groups_shared_answers_and_pending_without_applying(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            run = {'run_id': 'R', 'cases': {'C1': {'title': 'first'}, 'C2': {'title': 'second'}},
                   'questions': {}, 'history': []}
            atomic_write(base / review_page.INPUT, {'questions': [
                {'id': 'Q1', 'title': '入口', 'cases': ['C1', 'C2']},
                {'id': 'Q2', 'title': '其他', 'cases': ['C2']}],
                'checks': [{'id': 'A1', 'title': '结果', 'cases': ['C1'], 'checks': ['显示成功']}]})
            payload = review_page._payload(base, run)
            report = {'run_id': 'R', 'review_version': 1, 'revision': payload['revision'],
                      'decisions': [{'review_id': 'Q1', 'case_ids': ['C1', 'C2'],
                                     'status': 'edited', 'value': '从产品进入'}]}
            atomic_write(base / 'export.json', report)
            result = review_page.ingest(base, run, base / 'export.json')
            handoff = read_json(result['review_handoff'])
            first, second = handoff['cases']
            self.assertEqual(first['decisions'][0]['value'], '从产品进入')
            self.assertEqual(second['decisions'][0]['id'], 'Q1')
            self.assertEqual(first['pending'][0]['id'], 'A1')
            self.assertEqual(second['pending'][0]['id'], 'Q2')
            self.assertEqual(first['processing'], 'not_applied')
            self.assertEqual(result['next'], 'apply_review_decisions')
            report['revision'] = 'stale'
            atomic_write(base / 'export.json', report)
            with self.assertRaises(UiaError):
                review_page.ingest(base, run, base / 'export.json')
            self.assertEqual(read_json(result['review_handoff']), handoff)


if __name__ == '__main__':
    unittest.main()
