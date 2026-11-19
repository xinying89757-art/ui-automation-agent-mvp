import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uia_core import common, experience, knowledge, cli, environment_gate


class ProcessGapFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.old_common, self.old_knowledge = common.ROOT, knowledge.ROOT
        common.ROOT = self.root
        knowledge.ROOT = self.root / 'knowledge'
        knowledge.ROOT.mkdir()
        self.addCleanup(self.restore)

    def restore(self):
        common.ROOT, knowledge.ROOT = self.old_common, self.old_knowledge

    def test_placeholder_binds_unique_existing_kb_target_and_records_source(self):
        pages = {'schema_version': 'page-map.v1', 'pages': {'editor': {}}, 'targets': {
            'faq.add': {'label': '添加FAQ', 'role': 'button', 'name': '添加FAQ', 'page': 'editor'}}}
        common.atomic_write(knowledge.ROOT / 'page-map.yaml', pages, as_yaml=True)
        knowledge.sync_layout(pages=pages)
        case_dir = self.root / 'run/cases/C1'
        case_dir.mkdir(parents=True)
        common.atomic_write(case_dir / 'case-spec.yaml', {
            'steps': [{'id': 'S1', 'verb': 'click', 'target': '?添加FAQ'}], 'assertions': []}, as_yaml=True)
        manifest = {'cases': {'C1': {'case_spec': 'cases/C1/case-spec.yaml'}}}
        result = knowledge.bind_spec_placeholders(self.root / 'run', manifest)
        spec = common.read_yaml(case_dir / 'case-spec.yaml')
        self.assertEqual(spec['steps'][0]['target'], 'faq.add')
        self.assertEqual(result['count'], 1)
        self.assertEqual(manifest['cases']['C1']['kb_bindings'][0]['source'], 'knowledge')

    def test_all_placeholder_controls_are_present_in_initial_checklist(self):
        case_dir = self.root / 'run/cases/C1'
        case_dir.mkdir(parents=True)
        common.atomic_write(case_dir / 'case-spec.yaml', {
            'steps': [{'id': 'S1', 'target': '?一个未知控件'}],
            'assertions': [{'checks': [{'target': '?另一个未知控件'}]}]}, as_yaml=True)
        manifest = {'cases': {'C1': {'case_spec': 'cases/C1/case-spec.yaml', 'source': ''}},
                    'questions': {}, 'config': {'auth': {}, 'targets': {}, 'network': {'mode': 'direct'}}}
        rows = experience.rows(self.root / 'run', manifest)
        controls = {r['subject'] for r in rows if r.get('kind') == 'missing_control'}
        self.assertEqual(controls, {'?一个未知控件', '?另一个未知控件'})

    def test_observable_missing_control_becomes_exploration_work(self):
        manifest = {'cases': {'C1': {'result': None, 'work_status': 'waiting_human', 'stage': 'execution'}},
                    'config': {}, 'questions': {}}
        row = {'key': 'missing-control:C1', 'block': 'E', 'kind': 'missing_control',
               'cases': ['C1'], 'missing_controls': [{'case_id': 'C1', 'target': '?按钮'}]}
        experience.apply_checklist(manifest, {'entries': [row], 'answer': {'entries': {row['key']: '按原文可观察'}},
                                               'case_ids': ['C1'], 'status': 'answered'})
        case = manifest['cases']['C1']
        self.assertEqual(case['work_status'], 'pending')
        self.assertEqual(case['stage'], 'discovery')
        self.assertEqual(case['exploration_required'], ['?按钮'])

    def test_preconditions_rejects_options_without_classify(self):
        base = self.root / 'run'
        base.mkdir()
        args = cli.parser().parse_args(['preconditions', '--run', str(base), '--key', 'K', '--as', 'explore'])
        with self.assertRaisesRegex(common.UiaError, 'require the classify action'):
            cli.dispatch(args, base / 'run.json', {'cases': {}, 'questions': {}, 'config': {}})

    def test_preflight_reuses_recent_proof_without_login(self):
        base = self.root / 'run'
        (base / 'evidence').mkdir(parents=True)
        proof = base / 'evidence/proof.json'
        proof.write_text('{}', encoding='utf-8')
        manifest = {'config': {'auth': {}}, 'config_hash': 'cfg', 'preflight': {
            'status': 'passed', 'checked_at': common.now(), 'config_hash': 'cfg',
            'auth_sha256': None, 'evidence': 'evidence/proof.json', 'sha256': common.file_hash(proof)}}
        with patch.object(environment_gate, 'public_preflight_result', return_value={'status': 'passed'}), \
             patch.object(environment_gate, 'enforce_editor'), \
             patch('uia_core.profiles.invoke_login', side_effect=AssertionError('login should be cached')):
            result = environment_gate.preflight_run(base, manifest)
        self.assertTrue(result['cached'])

    def test_writeback_rolls_back_when_knowledge_validation_fails(self):
        common.atomic_write(knowledge.ROOT / 'index.yaml', {'schema_version': 'uia-knowledge-index.v2', 'entries': []}, as_yaml=True)
        before = (knowledge.ROOT / 'index.yaml').read_bytes()
        with patch.object(knowledge, 'validate', side_effect=common.UiaError('invalid')):
            with self.assertRaises(common.UiaError):
                knowledge.writeback(self.root / 'run', {'run_id': 'R', 'cases': {}})
        self.assertEqual((knowledge.ROOT / 'index.yaml').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
