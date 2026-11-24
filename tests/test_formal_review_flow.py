import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uia_core import checks, cli, common, review_page, runtime, specs, workflow


class FormalReviewFlowTest(unittest.TestCase):
    def test_overlay_is_run_local_and_cannot_replace_shared_target(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            _, _, shared = specs.catalogs()
            name = 'pilot.unpublished.close'
            common.atomic_write(base / 'state/page-map-overlay.yaml',
                                {'targets': {name: {'selector': 'button.close'}}}, as_yaml=True)
            _, _, merged = specs.catalogs(base)
            self.assertNotIn(name, shared['targets'])
            self.assertIn(name, merged['targets'])
            existing = next(iter(shared['targets']))
            common.atomic_write(base / 'state/page-map-overlay.yaml',
                                {'targets': {existing: {'selector': 'fake'}}}, as_yaml=True)
            with self.assertRaises(common.UiaError):
                specs.catalogs(base)

    def test_rerun_requires_real_pass_and_no_unanswered_blocker(self):
        case = {'case_id': 'C1', 'result': 'passed', 'work_status': 'finished',
                'attempts': [{'result': 'passed', 'executed': True}]}
        run = {'questions': {}}
        runtime.require_rerunnable(run, case)
        run['questions']['Q'] = {'status': 'open', 'kind': 'exploration', 'case_ids': ['C1']}
        with self.assertRaises(common.UiaError):
            runtime.require_rerunnable(run, case)
        run['questions']['Q']['case_ids'] = ['C2']
        runtime.require_rerunnable(run, case)
        case['attempts'][0]['executed'] = False
        with self.assertRaises(common.UiaError):
            runtime.require_rerunnable(run, case)

    def test_bind_review_to_spec_rejects_wrong_owner_and_changed_source(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            common.atomic_write(base / 'source.json', {'expected': ['原文']})
            common.atomic_write(base / 'case.yaml', {'case_id': 'C1'}, as_yaml=True)
            run = {'run_id': 'R', 'history': [], 'cases': {'C1': {'case_id': 'C1',
                   'source': 'source.json', 'case_spec': 'case.yaml'}},
                   'review_applications': {'entry': {'source': 'prototype', 'case_ids': ['C1'],
                       'source_files': {'C1': common.file_hash(base / 'source.json')}}},
                   'prototype_review': {'reviewed_revision': None, 'decisions': [
                       {'id': 'A1', 'status': 'confirmed', 'cases': ['C1']},
                       {'id': 'A2', 'status': 'confirmed', 'cases': ['C2']}]}}
            clean = {'errors': [], 'cases': {'C1': {'errors': []}}}
            with patch.object(specs, 'lint', return_value=clean):
                with self.assertRaises(common.UiaError):
                    review_page.bind_case(base, run, 'C1', ['A2'], 'prototype')
                result = review_page.bind_case(base, run, 'C1', ['A1'], 'prototype')
                self.assertIsNone(result['review_binding']['reviewed_revision'])
                self.assertEqual(checks.review_binding_errors(base, run['cases']['C1'], base / 'case.yaml'), [])
                common.atomic_write(base / 'source.json', {'expected': ['不同预期']})
                self.assertTrue(checks.review_binding_errors(base, run['cases']['C1'], base / 'case.yaml'))
                with self.assertRaises(common.UiaError):
                    review_page.bind_case(base, run, 'C1', ['A1'], 'prototype')

    def test_headed_rerun_is_explicit_in_cli(self):
        args = cli.parser().parse_args(['run-batch', '--run', 'R', '--cases', 'C1', '--headed', '--rerun'])
        self.assertTrue(args.headed)
        self.assertTrue(args.rerun)

    def test_binding_a_reviewed_assertion_needs_no_entry_question(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            common.atomic_write(base / 'source.json', {'expected': ['原文']})
            common.atomic_write(base / 'case.yaml', {'case_id': 'C1'}, as_yaml=True)
            run = {'run_id': 'R', 'history': [], 'cases': {'C1': {'case_id': 'C1',
                   'source': 'source.json', 'case_spec': 'case.yaml'}},
                   'human_review': {'revision': 'reviewed', 'source_files': {'C1': common.file_hash(base / 'source.json')},
                                    'decisions': [{'id': 'A1', 'status': 'confirmed', 'cases': ['C1']}]}}
            with patch.object(specs, 'lint', return_value={'errors': [], 'cases': {'C1': {'errors': []}}}):
                result = review_page.bind_case(base, run, 'C1', ['A1'])
            self.assertEqual(result['review_binding']['reviewed_revision'], 'reviewed')

    def test_binding_requires_all_confirmed_decisions_for_case(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            common.atomic_write(base / 'source.json', {'expected': ['原文']})
            common.atomic_write(base / 'case.yaml', {'case_id': 'C1'}, as_yaml=True)
            run = {'run_id': 'R', 'history': [], 'cases': {'C1': {'case_id': 'C1',
                   'source': 'source.json', 'case_spec': 'case.yaml'}},
                   'human_review': {'revision': 'reviewed', 'source_files': {'C1': common.file_hash(base / 'source.json')},
                                    'decisions': [{'id': 'A1', 'status': 'confirmed', 'cases': ['C1']},
                                                  {'id': 'A2', 'status': 'edited', 'cases': ['C1']}]}}
            with patch.object(specs, 'lint', return_value={'errors': [], 'cases': {'C1': {'errors': []}}}):
                with self.assertRaises(common.UiaError):
                    review_page.bind_case(base, run, 'C1', ['A1'])
                review_page.bind_case(base, run, 'C1', ['A1', 'A2'])
                run['initial_review_required'] = True
                self.assertEqual(workflow.unbound_review_ids(run, run['cases']['C1']), [])
                common.atomic_write(base / 'case.yaml', {'case_id': 'C1', 'changed': True}, as_yaml=True)
                self.assertEqual(workflow.unbound_review_ids(run, run['cases']['C1'], base), ['A1', 'A2'])
                run['human_review']['decisions'][1]['value'] = '调整后的预期'
                self.assertEqual(workflow.unbound_review_ids(run, run['cases']['C1']), ['A1', 'A2'])


if __name__ == '__main__':
    unittest.main()
