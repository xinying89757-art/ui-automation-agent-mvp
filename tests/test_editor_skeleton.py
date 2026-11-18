import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uia_core import specs
from uia_core.editor_explore import validate_candidates, write_candidates
from uia_core.metrics import calculate


class EditorSkeletonTests(unittest.TestCase):
    def test_assembled_lint_rejects_raw_locator_actions_only(self):
        body = "// @uia-assembled\nawait page.getByText('保存').click();\n"
        self.assertTrue(specs.assembled_raw_action_errors(body))
        self.assertEqual(specs.assembled_raw_action_errors("await page.getByText('保存').click();\n"), [])
        self.assertEqual(specs.assembled_raw_action_errors("// @uia-assembled\nawait editor.actVerified('click', 'save');\n"), [])

    def test_unknown_control_is_marked_instead_of_invented(self):
        self.assertIn('待补控件', specs.note_missing_control.__doc__)
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / 'checklist.md').write_text('# 执行前清单\n', encoding='utf-8')
            manifest = {'cases': {'T1': {}}, 'questions': {'run-preconditions': {'entries': []}}}
            specs.note_missing_control(base, manifest, 'T1', 'S1 ?slash.card')
            text = (base / 'missing-controls.md').read_text(encoding='utf-8')
            self.assertIn('待补控件 T1 S1 ?slash.card', text)
            self.assertIn('## 待补控件', (base / 'checklist.md').read_text(encoding='utf-8'))
            self.assertEqual(manifest['cases']['T1']['missing_controls'], ['S1 ?slash.card'])

    def test_exploration_candidates_stay_needs_review(self):
        with tempfile.TemporaryDirectory() as temp:
            written = write_candidates(temp, [
                {'name': '保存', 'selector': '#save', 'strategy': 'id', 'match_count': 1,
                 'frame': 'iframe[name="prod"]', 'nested_frames': ['#tiptap-iframe'], 'role': 'button'},
                {'name': 'person' + '@' + 'example.com', 'selector': '#secret', 'match_count': 1, 'strategy': 'id'},
                {'name': '模糊', 'selector': '.many', 'match_count': 2, 'strategy': 'class'},
            ], run_id='editor-explore')
            self.assertEqual(written['status'], 'needs_review')
            self.assertEqual(written['count'], 1)
            report = validate_candidates(temp)
            self.assertTrue(report['valid'])
            record = list(Path(temp, 'components').glob('*.yaml'))[0].read_text(encoding='utf-8')
            self.assertIn('needs_review', record)
            self.assertNotIn('@', record)

    def test_metrics_count_midscene_rescues(self):
        with tempfile.TemporaryDirectory() as temp:
            metrics = calculate(Path(temp), {'cases': {'T1': {'attempts': [{'rescued_by_midscene': 2}]}}, 'missing_controls': []})
        self.assertEqual(metrics['rescued_by_midscene'], 2)
        self.assertEqual(metrics['missing_controls'], 0)


if __name__ == '__main__':
    unittest.main()
