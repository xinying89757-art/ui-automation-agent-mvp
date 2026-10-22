import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uia_core import common, entries, workflow


class ReleaseAndRefineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / 'runs/R'
        self.base.mkdir(parents=True)
        p = patch.object(common, 'ROOT', self.root)
        p.start(); self.addCleanup(p.stop)
        common.atomic_write(entries.knowledge_path('page-map.yaml'), {
            'pages': {'content-admin': {'entry': '内容管理'}}, 'targets': {'faq.cancel': {'selector': 'a'}}}, as_yaml=True)
        self.m = {'run_id': 'R', 'cases': {}, 'questions': {}, 'history': [], 'sources': [], 'interaction_mode': 'once',
                  'checklist_issued': True, 'config': {'execution': {'batch_size': 10}}}
        for cid in ('C1', 'C2'):
            common.atomic_write(self.base / cid / 'case-spec.yaml', {
                'start_page': 'content-admin', 'steps': [{'id': 'S1', 'verb': 'assert', 'target': '?faq_state_' + cid}],
                'assertions': [{'checks': [{'target': 'faq.cancel'}]}]}, as_yaml=True)
            self.m['cases'][cid] = {'case_id': cid, 'case_spec': cid + '/case-spec.yaml', 'priority': 'P1',
                                    'work_status': 'pending', 'stage': 'discovery', 'result': None, 'attempts': []}
        entries.add(self.m, '新版内容编辑器=内容管理 → 产品 → 编辑')
        workflow.question(self.m, 'environment', 'faq-editor-entry', '入口没到', ['C1', 'C2'], page='新版内容编辑器')

    def test_deferred_item_parks_until_entry_confirmed_then_releases(self):
        q = self.m['questions']['environment:faq-editor-entry'] if 'environment:faq-editor-entry' in self.m['questions'] \
            else next(iter(self.m['questions'].values()))
        self.assertEqual((q['status'], q['page']), ('deferred', '新版内容编辑器'))
        self.assertEqual(workflow.release_resolved(self.m), [])
        self.assertEqual(self.m['cases']['C1']['work_status'], 'waiting_human')
        entries.confirm(self.m, '新版内容编辑器', ['click:content-admin', 'click:text=产品'])
        self.assertEqual(workflow.release_resolved(self.m), [q['id']])
        self.assertEqual(q['status'], 'closed')
        self.assertEqual(self.m['cases']['C1']['work_status'], 'pending')

    def test_next_returns_refine_specs_not_review_when_placeholders_remain(self):
        entries.confirm(self.m, '新版内容编辑器', ['click:content-admin', 'click:text=产品'])
        workflow.release_resolved(self.m)
        with patch.object(workflow, 'refresh'), patch('uia_core.preconditions.triage', return_value=[]):
            task = workflow.next_task(self.base, self.m)
        self.assertEqual(task['action'], 'refine_specs')
        self.assertEqual(task['unresolved']['C1'], ['?faq_state_C1'])
        self.assertIn('faq.cancel', task['known_targets'])


if __name__ == '__main__':
    unittest.main()


class ChecklistResumeTests(unittest.TestCase):
    def test_cases_parked_by_queued_checklist_resume_when_answered(self):
        from uia_core import experience
        m = {'cases': {cid: {'case_id': cid, 'work_status': 'pending', 'stage': 'spec', 'result': None} for cid in ('C1', 'C2')},
             'questions': {}, 'history': [], 'config': {'mutation': {}}}
        q = workflow.question(m, 'preconditions', 'run-preconditions', '清单', ['C1', 'C2'], key='pre')
        self.assertEqual(m['cases']['C1']['work_status'], 'waiting_human')
        q.update(status='answered', entries=[{'key': 'env:x', 'block': 'A', 'label': 'x', 'cases': ['C2']}],
                 answer={'entries': {'env:x': False}})
        experience.apply_checklist(m, q)
        self.assertEqual(m['cases']['C1']['work_status'], 'pending')
        self.assertEqual(m['cases']['C2']['work_status'], 'waiting_human')
