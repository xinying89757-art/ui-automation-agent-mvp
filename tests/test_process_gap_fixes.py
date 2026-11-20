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

    def test_placeholder_match_uses_page_to_disambiguate_same_visible_label(self):
        pages = {'schema_version': 'page-map.v1', 'pages': {'editor': {}, 'content-admin': {}}, 'targets': {
            'legacy.faq.add': {'label': '添加FAQ', 'selector': 'a:text("添加FAQ")', 'page': 'content-admin'},
            'faq-editor.entry.faq.add': {'label': '添加FAQ', 'selector': 'button:text-is("添加FAQ")', 'page': 'editor'}}}
        common.atomic_write(knowledge.ROOT / 'page-map.yaml', pages, as_yaml=True)
        knowledge.sync_layout(pages=pages)
        case_dir = self.root / 'run/cases/C1'
        case_dir.mkdir(parents=True)
        common.atomic_write(case_dir / 'case-spec.yaml', {
            'start_page': 'editor', 'steps': [{'id': 'S1', 'verb': 'click', 'target': '?添加FAQ'}],
            'assertions': []}, as_yaml=True)
        result = knowledge.bind_spec_placeholders(self.root / 'run', {
            'cases': {'C1': {'case_spec': 'cases/C1/case-spec.yaml'}}})
        spec = common.read_yaml(case_dir / 'case-spec.yaml')
        self.assertEqual(spec['steps'][0]['target'], 'faq-editor.entry.faq.add')
        self.assertEqual(result['count'], 1)

    def test_recorded_bindings_are_applied_and_page_context_resolves_through_editor_flow(self):
        pages = {'schema_version': 'page-map.v1', 'pages': {'editor': {'entry': '编辑网站'},
                 'content-admin': {'entry': '内容管理'}}, 'targets': {
            'faq.add.admin': {'label': '添加FAQ', 'page': 'content-admin'},
            'z.faq.add': {'label': '添加FAQ', 'page': 'editor'}}}
        common.atomic_write(knowledge.ROOT / 'page-map.yaml', pages, as_yaml=True)
        knowledge.sync_layout(pages=pages)
        common.atomic_write(knowledge.ROOT / 'flows/entry.yaml', {
            'id': 'entry.editor', 'kind': 'flow', 'label': '编辑面板',
            'path_text': '内容管理→产品→编辑，内嵌编辑器框架插入 FAQ 组件',
            'confirmed': True, 'steps': ['click:text=内容管理']}, as_yaml=True)
        case_dir = self.root / 'run/cases/C1'
        case_dir.mkdir(parents=True)
        common.atomic_write(case_dir / 'case-spec.yaml', {
            'start_page': '?组件选择面板',
            'steps': [{'id': 'S1', 'verb': 'click', 'target': '?组件选择面板'},
                      {'id': 'S2', 'verb': 'click', 'target': '?添加FAQ'}],
            'assertions': []}, as_yaml=True)
        manifest = {'cases': {'C1': {'case_spec': 'cases/C1/case-spec.yaml',
                                     'kb_bindings': [
                                         {'placeholder': '?添加FAQ', 'target': 'z.faq.add', 'source': 'knowledge'},
                                         {'placeholder': '?组件选择面板', 'target': 'editor.component-panel',
                                          'source': 'knowledge-alias'},
                                         {'placeholder': '?组件选择面板', 'target': 'editor',
                                          'source': 'knowledge-page'}]}}}
        result = knowledge.bind_spec_placeholders(self.root / 'run', manifest)
        spec = common.read_yaml(case_dir / 'case-spec.yaml')
        self.assertEqual(spec['start_page'], 'editor')
        self.assertEqual(spec['steps'][0]['target'], 'editor.component-panel')
        self.assertEqual(spec['steps'][1]['target'], 'z.faq.add')
        self.assertEqual({row['placeholder'] for row in manifest['kb_bindings_applied']},
                         {'?组件选择面板', '?添加FAQ'})
        self.assertEqual(result['count'], 3)

    def test_equal_label_without_page_uses_stable_best_candidate(self):
        pages = {'schema_version': 'page-map.v1', 'pages': {'editor': {}, 'content-admin': {}}, 'targets': {
            'a.faq.add': {'label': '添加FAQ', 'page': 'content-admin'},
            'z.faq.add': {'label': '添加FAQ', 'page': 'editor'}}}
        common.atomic_write(knowledge.ROOT / 'page-map.yaml', pages, as_yaml=True)
        knowledge.sync_layout(pages=pages)
        case_dir = self.root / 'run/cases/C1'
        case_dir.mkdir(parents=True)
        common.atomic_write(case_dir / 'case-spec.yaml', {
            'start_page': 'editor', 'steps': [{'id': 'S1', 'verb': 'click', 'target': '?添加FAQ'}],
            'assertions': []}, as_yaml=True)
        result = knowledge.bind_spec_placeholders(self.root / 'run', {
            'cases': {'C1': {'case_spec': 'cases/C1/case-spec.yaml'}}})
        self.assertEqual(common.read_yaml(case_dir / 'case-spec.yaml')['steps'][0]['target'], 'z.faq.add')
        self.assertEqual(result['count'], 1)

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

    def test_round1_run_has_go_identity_for_later_resume(self):
        from uia_core import rounds
        run_root = self.root / 'runs'
        profile = self.root / 'prod.local.json'
        profile.write_text('{}', encoding='utf-8')
        def init(run_id, _profile):
            base = run_root / run_id
            (base / 'state').mkdir(parents=True)
            common.atomic_write(base / 'run.json', {
                'run_id': run_id, 'config': {'environment': {'id': 'production'}}, 'cases': {}, 'history': []})
        def imported(_base, manifest, _excel):
            manifest['cases'] = {'C1': {'case_id': 'C1'}}
            manifest['sources'] = [{'path': str(self.root / 'cases.xlsx'), 'sha256': 'abc'}]
            return {'total': 1}
        with patch.object(rounds, 'ROOT', self.root), patch('uia_core.workflow.init', side_effect=init), \
             patch('uia_core.workflow.scaffold'), patch('uia_core.workflow.import_excel', side_effect=imported), \
             patch('uia_core.profiles.profile_path', return_value=profile), \
             patch('uia_core.preconditions.sync_preconditions'):
            rounds.create(None, 1, 'R1', 'prod', str(self.root / 'cases.xlsx'))
        manifest = common.read_json(run_root / 'R1/run.json')
        self.assertEqual(manifest['go_profile'], str(profile.resolve()))
        self.assertTrue(manifest['go_key'])

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

    def test_successful_preflight_clears_only_stale_unexecuted_blockers(self):
        manifest = {'history': [], 'selected_cases': ['C1', 'C2'], 'cases': {
            'C1': {'result': 'environment_blocked', 'attempts': [], 'stage': 'finished', 'work_status': 'finished'},
            'C2': {'result': 'environment_blocked', 'attempts': [{'executed': True}], 'stage': 'finished'},
            'C3': {'result': 'environment_blocked', 'attempts': [], 'stage': 'finished'}}}
        self.assertEqual(environment_gate.clear_stale_environment_blockers(manifest), ['C1'])
        self.assertIsNone(manifest['cases']['C1']['result'])
        self.assertEqual(manifest['cases']['C2']['result'], 'environment_blocked')
        self.assertEqual(manifest['cases']['C3']['result'], 'environment_blocked')

    def test_preflight_block_only_classifies_selected_cases(self):
        manifest = {'run_id': 'R', 'config': {}, 'selected_cases': ['C1'], 'cases': {
            'C1': {'attempts': [], 'stage': 'execution', 'work_status': 'runnable'},
            'C2': {'attempts': [], 'stage': 'spec', 'work_status': 'pending'}}}
        environment_gate.block_run(manifest, common.UiaError('entry failed'))
        self.assertEqual(manifest['cases']['C1']['result'], 'environment_blocked')
        self.assertIsNone(manifest['cases']['C2'].get('result'))
        self.assertEqual(manifest['cases']['C2']['work_status'], 'pending')

    def test_writeback_rolls_back_when_knowledge_validation_fails(self):
        common.atomic_write(knowledge.ROOT / 'index.yaml', {'schema_version': 'uia-knowledge-index.v2', 'entries': []}, as_yaml=True)
        before = (knowledge.ROOT / 'index.yaml').read_bytes()
        with patch.object(knowledge, 'validate', side_effect=common.UiaError('invalid')):
            with self.assertRaises(common.UiaError):
                knowledge.writeback(self.root / 'run', {'run_id': 'R', 'cases': {}})
        self.assertEqual((knowledge.ROOT / 'index.yaml').read_bytes(), before)

    def test_catalog_promotion_rolls_back_transaction_when_checker_fails(self):
        from uia_core import entries
        (self.root / 'scripts').mkdir(exist_ok=True)
        (self.root / 'scripts/check_knowledge.py').write_text('pass')
        common.atomic_write(knowledge.ROOT / 'page-map.yaml', {
            'schema_version': 'page-map.v1', 'pages': {'editor': {}}, 'targets': {}}, as_yaml=True)
        before = (knowledge.ROOT / 'page-map.yaml').read_bytes()
        failed = __import__('subprocess').CompletedProcess([], 1, '', 'invalid')
        with patch.object(knowledge, 'validate'), patch('subprocess.run', return_value=failed):
            with self.assertRaises(common.UiaError):
                entries.save_catalog('page-map.yaml', {'schema_version': 'page-map.v1',
                    'pages': {'editor': {}}, 'targets': {'new.target': {'label': '测试', 'page': 'editor'}}})
        self.assertEqual((knowledge.ROOT / 'page-map.yaml').read_bytes(), before)

    def test_layout_preserves_legacy_index_rows_and_unspecified_page_metadata(self):
        pages = {'schema_version': 'page-map.v1', 'pages': {'editor': {}, 'content-admin': {}},
                 'targets': {'button': {'label': '保存', 'selector': '.save', 'page': 'editor'}}}
        rows = knowledge.sync_layout(pages=pages)
        current = common.read_yaml(knowledge.ROOT / 'index.yaml')
        legacy = dict(current['entries'][0])
        legacy.update(id='target.legacy', page='content-admin', path='components/target-legacy.yaml')
        legacy_file = knowledge.ROOT / legacy['path']
        common.atomic_write(legacy_file, {'id': 'target.legacy', 'kind': 'component', 'selector': '.legacy'}, as_yaml=True)
        current['entries'].append(legacy)
        common.atomic_write(knowledge.ROOT / 'index.yaml', current, as_yaml=True)
        pages['targets']['button'].pop('page')
        updated = knowledge.sync_layout(pages=pages)
        self.assertEqual(next(row for row in updated if row['id'] == 'target.button')['page'], 'editor')
        self.assertIn('target.legacy', {row['id'] for row in updated})


if __name__ == '__main__':
    unittest.main()
