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


class PageMapSliceTests(unittest.TestCase):
    def test_unrelated_new_targets_do_not_change_case_version_slice(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            common.atomic_write(base / 'C1/case-spec.yaml', {'start_page': 'content-admin', 'steps': [{'target': 'faq.add'}]}, as_yaml=True)
            pm = base / 'runner/knowledge/page-map.yaml'
            def write(targets):
                common.atomic_write(pm, {'schema_version': 'page-map.v1', 'pages': {'content-admin': {'entry': '内容管理'}},
                                         'targets': targets}, as_yaml=True)
            c = {'case_spec': 'C1/case-spec.yaml'}
            write({'faq.add': {'selector': '.a', 'dialog': 'faq.dialog'}, 'faq.dialog': {'selector': '.d'}})
            first = workflow.page_map_slice(base, c)
            write({'faq.add': {'selector': '.a', 'dialog': 'faq.dialog'}, 'faq.dialog': {'selector': '.d'}, 'other.x': {'selector': '.x'}})
            self.assertEqual(workflow.page_map_slice(base, c), first)
            write({'faq.add': {'selector': '.a', 'dialog': 'faq.dialog'}, 'faq.dialog': {'selector': '.changed'}})
            self.assertNotEqual(workflow.page_map_slice(base, c), first)


class EarnedOutcomeTests(unittest.TestCase):
    def test_unexecuted_verdicts_rejected_and_reopened(self):
        c = {'case_id': 'C1', 'attempts': [], 'stage': 'finished', 'work_status': 'finished', 'result': 'product_confirmation'}
        m = {'cases': {'C1': c, 'C2': {'case_id': 'C2', 'attempts': [{'result': 'automation_failure'}], 'stage': 'finished',
                                       'work_status': 'finished', 'result': 'automation_failure'},
                       'C3': {'case_id': 'C3', 'attempts': [], 'stage': 'finished', 'work_status': 'finished',
                              'result': 'environment_blocked'}}, 'history': []}
        for result in ('product_confirmation', 'automation_failure', 'environment_blocked'):
            with self.assertRaises(common.UiaError):
                workflow.classification_gate(Path('.'), m, {'attempts': []}, result)
        workflow.classification_gate(Path('.'), m, {'attempts': [{}]}, 'automation_failure')
        workflow.classification_gate(Path('.'), m, {'attempts': [], 'checklist_wait': True}, 'environment_blocked')
        workflow.classification_gate(Path('.'), m, {'attempts': []}, 'not_suitable')
        self.assertEqual(sorted(workflow.reopen_unearned(m)), ['C1', 'C3'])
        self.assertEqual((c['stage'], c['work_status'], c['result']), ('spec', 'pending', None))
        self.assertEqual(m['cases']['C2']['result'], 'automation_failure')


class PublicHandoffTests(unittest.TestCase):
    def test_public_frontend_env_items_are_refused_and_released(self):
        m = {'cases': {'C1': {'case_id': 'C1', 'work_status': 'pending', 'stage': 'spec', 'result': None}},
             'questions': {}, 'history': [], 'interaction_mode': 'once'}
        with self.assertRaisesRegex(common.UiaError, 'defer_public'):
            workflow.question(m, 'environment', 'public', '公开前台不可达，需要可访问的前台', ['C1'])
        m['questions']['old'] = {'id': 'old', 'kind': 'environment', 'subject': 's', 'status': 'deferred',
                                 'prompt': '需读取公开页面 FAQPage；当前环境公开前台不可达', 'case_ids': ['C1'], 'resume_states': {'C1': 'pending'}}
        m['cases']['C1']['work_status'] = 'waiting_human'
        self.assertEqual(workflow.release_resolved(m), ['old'])
        self.assertEqual(m['cases']['C1']['work_status'], 'pending')


class BreadthFirstTests(ReleaseAndRefineTests):
    def test_untried_cases_are_refined_before_repairs(self):
        entries.confirm(self.m, '新版内容编辑器', ['click:content-admin', 'click:text=产品'])
        workflow.release_resolved(self.m)
        self.m['cases']['C3'] = {'case_id': 'C3', 'priority': 'P0', 'work_status': 'pending', 'stage': 'repair',
                                 'result': 'automation_failure', 'attempts': [{'result': 'automation_failure'}]}
        with patch.object(workflow, 'refresh'), patch('uia_core.preconditions.triage', return_value=[]):
            self.assertEqual(workflow.next_task(self.base, self.m)['action'], 'refine_specs')
            for cid in ('C1', 'C2'):
                self.m['cases'][cid]['work_status'] = 'finished'
            self.assertEqual(workflow.next_task(self.base, self.m)['action'], 'repair')


class SuspendedTests(unittest.TestCase):
    def test_suspended_needs_category_and_is_not_reopened(self):
        with self.assertRaises(common.UiaError):
            workflow.classification_gate(Path('.'), {}, {'attempts': []}, 'suspended', '没原因')
        workflow.classification_gate(Path('.'), {}, {'attempts': []}, 'suspended', '缺公开路径：产品公开 URL 未知')
        m = {'cases': {'C1': {'attempts': [], 'stage': 'finished', 'work_status': 'finished', 'result': 'suspended'}}, 'history': []}
        self.assertEqual(workflow.reopen_unearned(m), [])
        self.assertIn('suspended', common.RESULTS)
