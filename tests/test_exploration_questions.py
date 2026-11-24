import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uia_core import common, exploration, workflow


class ExplorationQuestionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.run = {'run_id': 'R', 'config': {'execution': {'batch_size': 10}}, 'history': [],
                    'interaction_mode': 'once', 'questions': {}, 'sources': [], 'checklist_issued': True,
                    'preflight': {'status': 'passed'}, 'cases': {}}
        for cid in ('C1', 'C2', 'C3'):
            common.atomic_write(self.base / cid / 'case-spec.yaml', {'start_page': '?entry',
                'steps': [{'id': 'S1', 'target': '?shared' if cid != 'C3' else '?independent'}]}, as_yaml=True)
            self.run['cases'][cid] = {'case_id': cid, 'priority': 'P1', 'stage': 'discovery',
                'case_spec': cid + '/case-spec.yaml', 'work_status': 'pending', 'result': None, 'attempts': []}

    def next(self):
        with patch.object(workflow, 'refresh'), patch('uia_core.preconditions.triage', return_value=[]):
            return workflow.next_task(self.base, self.run)

    def test_shared_question_parks_only_dependents_and_answer_resumes(self):
        outcome = workflow.assess_gap(self.base, self.run, ['C1', 'C2'], '?shared', 'ask',
            '入口没有线索', '从哪里进入编辑器？', page='产品描述')
        q = outcome['question']
        self.assertEqual(q['status'], 'open')
        self.assertEqual([self.run['cases'][cid]['work_status'] for cid in ('C1', 'C2', 'C3')],
                         ['waiting_human', 'waiting_human', 'pending'])
        self.assertEqual(self.next()['case_ids'], ['C3'])
        self.run['cases']['C3'].update(work_status='finished', stage='finished', result='passed', stability='stable', feedback=True)
        self.assertEqual(self.next()['action'], 'ask_human')
        workflow.answer(self.run, q['id'], '内容管理 → 产品 → 添加产品', self.base)
        self.assertEqual(self.run['cases']['C1']['work_status'], 'pending')
        self.assertEqual(self.run['knowledge_candidates'][q['id']]['verification'], 'unverified')
        again = workflow.assess_gap(self.base, self.run, ['C1', 'C2'], '?shared', 'ask',
            '相同入口', '从哪里进入编辑器？', page='产品描述')
        self.assertEqual(again['question']['status'], 'answered')
        self.assertEqual(len(self.run['questions']), 1)

    def test_stalled_can_ask_early_and_progress_can_continue(self):
        evidence = self.base / 'evidence.json'
        evidence.write_text('{}')
        exploration.log(self.run, 'snapshot', 'shared', 'failed', '没有入口线索', self.base,
                        'C1', '?shared', 'evidence.json', 1000, 'stalled')
        self.assertEqual(self.next()['action'], 'assess_exploration')
        workflow.assess_gap(self.base, self.run, ['C1'], '?shared', 'continue', '发现产品菜单，继续查看')
        self.assertEqual(self.next()['action'], 'explore')
        self.assertIsNone(self.run['cases']['C1']['result'])

    def test_review_decisions_are_reused_only_for_associated_cases(self):
        self.run['prototype_review'] = {'decisions': [{'id': 'entry', 'cases': ['C1', 'C2'],
            'status': 'confirmed', 'value': '内容管理 → 产品 → 添加产品'}]}
        outcome = workflow.assess_gap(self.base, self.run, ['C1'], '?shared', 'ask', '入口未知', review_id='entry')
        self.assertEqual(outcome['decision'], 'use_review_answer')
        self.assertEqual(self.run['questions'], {})
        with self.assertRaises(common.UiaError):
            workflow.assess_gap(self.base, self.run, ['C3'], '?shared', 'ask', '入口未知', review_id='entry')

    def test_critical_question_is_not_deferred_by_single_review_mode(self):
        q = workflow.assess_gap(self.base, self.run, ['C1'], '?shared', 'ask',
                                '关键入口没有线索', '入口在哪里？', urgency='critical', page='产品')['question']
        self.assertEqual(q['status'], 'open')
        self.assertEqual(self.next()['action'], 'ask_human')

    def test_cli_persists_answer_and_candidate_with_scoped_evidence(self):
        self.run.update(schema_version='uia-run.v1', active_batch=None, contaminated_fixtures={})
        manifest = self.base / 'run.json'
        common.atomic_write(manifest, self.run)
        cli = Path(__file__).resolve().parents[1] / 'scripts/uia.py'
        def invoke(*args):
            result = subprocess.run([sys.executable, str(cli), *args], capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        queued = invoke('gap-assess', '--run', str(manifest), '--cases', 'C1', 'C2', '--target', '?shared',
                        '--decision', 'ask', '--reason', '无入口线索', '--prompt', '入口在哪里？', '--page', '产品')
        qid = queued['question']['id']
        self.assertEqual(common.read_json(manifest)['cases']['C3']['work_status'], 'pending')
        answer_file = self.base / 'answer.json'
        common.atomic_write(answer_file, '内容管理 → 产品')
        invoke('answer', '--run', str(manifest), '--question', qid, '--file', str(answer_file))
        saved = common.read_json(manifest)
        self.assertEqual(saved['cases']['C1']['work_status'], 'pending')
        self.assertEqual(saved['knowledge_candidates'][qid]['verification'], 'unverified')
        (self.base / 'evidence.json').write_text('{"reached":true}')
        invoke('candidate-verify', '--run', str(manifest), '--question', qid, '--evidence', 'evidence.json')
        candidate = common.read_json(manifest)['knowledge_candidates'][qid]
        self.assertEqual((candidate['verification'], candidate['evidence']), ('verified', 'evidence.json'))

    def test_same_target_on_different_pages_does_not_reuse_answer(self):
        q = workflow.assess_gap(self.base, self.run, ['C1'], '?shared', 'ask',
                                '入口未知', '入口在哪里？', page='产品')['question']
        workflow.answer(self.run, q['id'], '产品路径', self.base)
        second = workflow.assess_gap(self.base, self.run, ['C2'], '?shared', 'ask',
                                    '入口未知', '入口在哪里？', page='文章')['question']
        self.assertNotEqual(q['id'], second['id'])
        self.assertEqual(second['status'], 'open')

    def test_unanswered_review_blocks_only_its_cases_until_confirmed(self):
        self.run['human_review'] = {'pending': [{'id': 'business-expected', 'cases': ['C1', 'C2']}]}
        workflow.park_cases_with_pending_review(self.run)
        self.assertEqual([self.run['cases'][cid]['work_status'] for cid in ('C1', 'C2', 'C3')],
                         ['waiting_human', 'waiting_human', 'pending'])
        self.run['human_review']['pending'] = []
        workflow.park_cases_with_pending_review(self.run)
        self.assertEqual(self.run['cases']['C1']['work_status'], 'pending')

    def test_unbound_review_does_not_block_independent_ready_case(self):
        self.run.update(initial_review_required=True, human_review={'decisions': [
            {'id': 'A1', 'status': 'confirmed', 'cases': ['C1'], 'value': '显示成功'}], 'pending': []})
        self.run['cases']['C1']['work_status'] = 'runnable'
        self.run['cases']['C3']['work_status'] = 'runnable'
        self.run['cases']['C2']['work_status'] = 'waiting_human'
        with patch.object(workflow, 'unresolved_targets', return_value=[]), \
             patch.object(workflow, 'missing_catalog_targets', return_value=[]), \
             patch.object(workflow, 'script_todos', return_value=[]):
            result = self.next()
            self.assertEqual(result['action'], 'run-batch')
            self.assertEqual(result['case_ids'], ['C3'])
            self.run['cases']['C3']['work_status'] = 'finished'
            result = self.next()
            self.assertEqual(result['action'], 'spec')
            self.assertEqual(result['case_ids'], ['C1'])
            self.assertEqual(result['review_ids'], ['A1'])

    def test_feedback_is_required_only_for_verified_candidates_in_new_runs(self):
        case = self.run['cases']['C1']
        case.update(result='passed', stability='stable', work_status='finished')
        self.run['initial_review_required'] = True
        self.assertEqual(workflow.pending_feedback_cases(self.run), [])
        self.run['knowledge_candidates'] = {'Q': {'case_ids': ['C1'], 'verification': 'unverified'}}
        self.assertEqual(workflow.pending_feedback_cases(self.run), [])
        self.run['knowledge_candidates']['Q']['verification'] = 'verified'
        self.assertEqual([c['case_id'] for c in workflow.pending_feedback_cases(self.run)], ['C1'])


if __name__ == '__main__':
    unittest.main()
