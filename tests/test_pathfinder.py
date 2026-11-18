"""spec-pathfinder is a code stage: v1 markdown, one checklist, optional v2 index."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uia_core import cli, common, entries, experience, pathfinder, specs
from uia_core.workbooks import extract

SOURCE = Path(__file__).resolve().parents[1]
DEMO = SOURCE / 'skills/spec-pathfinder/trial/fixtures/demo'


class PathfinderStageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patches = [patch.object(module, 'ROOT', self.root) for module in (common, specs, entries.common)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.base = self.root / 'runs/PF'
        self.base.mkdir(parents=True)
        knowledge = self.root / 'assets/playwright-runner/knowledge'
        knowledge.mkdir(parents=True)
        common.atomic_write(knowledge / 'page-map.yaml', {
            'pages': {'editor': {'entry': '编辑网站', 'label': '编辑网站'}, 'content-admin': {'entry': '内容管理'}},
            'targets': {}}, as_yaml=True)
        common.atomic_write(knowledge / 'entries.yaml', {'schema_version': 'entry-hints.v1', 'entries': {}}, as_yaml=True)
        common.atomic_write(knowledge / 'network.yaml', {'rules': {}}, as_yaml=True)
        common.atomic_write(knowledge / 'data-prep.yaml', {'data': {}}, as_yaml=True)
        shutil.copyfile(SOURCE / 'preconditions.yaml', self.root / 'preconditions.yaml')
        (self.root / 'knowledge').mkdir()
        common.atomic_write(self.root / 'knowledge/entries.yaml', {'schema_version': 'entry-hints.v1', 'entries': {}}, as_yaml=True)
        common.atomic_write(self.root / 'knowledge/page-map.yaml', {
            'pages': {'editor': {'entry': '编辑网站', 'label': '编辑网站'}, 'content-admin': {'entry': '内容管理'}},
            'targets': {}}, as_yaml=True)
        self.memory = patch.object(experience, 'memory_path', return_value=self.root / 'private/memory.json')
        self.memory.start()
        self.addCleanup(self.memory.stop)
        self.m = {'run_id': 'PF', 'cases': {}, 'questions': {}, 'history': [], 'sources': [],
                  'config': {'auth': {}, 'targets': {}, 'network': {'mode': 'direct'}, 'mutation': {'allowed': True, 'scope': ['*'],
                             'authorization_profile': {'approved_by': 'Xinying'}}}}

    def workbook(self, rows):
        path = self.root / 'fixture.xlsx'
        book = Workbook()
        sheet = book.active
        sheet.title = '测试用例'
        sheet.append(['用例编号', '模块', '用例标题', '前置条件', '测试步骤', '预期结果'])
        for row in rows:
            sheet.append(row)
        book.save(path)
        parsed = extract(path)
        self.assertEqual(parsed['gaps'], [])
        for raw in parsed['cases']:
            cid = raw['suggested_id']
            raw['case_id'] = cid
            folder = self.base / 'cases' / cid
            folder.mkdir(parents=True)
            common.atomic_write(folder / 'source.json', raw)
            self.m['cases'][cid] = {'case_id': cid, 'source': f'cases/{cid}/source.json', 'title': raw['title'],
                                    'module': raw['module'], 'sheet': raw['sheet'], 'rows': raw['rows'],
                                    'source_hash': raw['content_hash'],
                                    'work_status': 'pending', 'stage': 'spec', 'result': None, 'attempts': []}
        return path

    def test_v1_ids_checklist_and_no_tracked_output(self):
        skill_before = {path.relative_to(SOURCE) for path in (SOURCE / 'skills/spec-pathfinder').rglob('*') if path.is_file()}
        self.workbook([
            ['TC-PF-1', '演示需求', '保存概述', '', '1. 打开订单列表页面\n2. 点击「保存」', '页面提示“已保存”'],
            ['TC-PF-2', '演示需求', '结果含糊', '', '打开编辑网站页面', '正常'],
        ])
        first = pathfinder.compile_run(self.base, self.m)
        self.assertEqual(first['stage'], 'v1')
        self.assertIsNone(first['index'])
        human = next((self.base / 'spec-pathfinder').rglob('SPEC-human-v1.md'))
        doubts = next((self.base / 'spec-pathfinder').rglob('DOUBTS-v1.md'))
        text = human.read_text(encoding='utf-8')
        doubt_text = doubts.read_text(encoding='utf-8')
        self.assertIn('TC-PF-1/S1/C1', text)
        self.assertIn('TC-PF-1/S2/C1', text)
        self.assertNotIn('置信度：高', text)
        self.assertNotIn('置信度：高', doubt_text)
        self.assertNotIn('.ftl', text)
        self.assertNotIn('/home/', text)
        again = pathfinder.compile_run(self.base, self.m)
        self.assertEqual(text, human.read_text(encoding='utf-8'))
        self.assertEqual(first['requirements'][0]['slug'], again['requirements'][0]['slug'])
        pathfinder.project_specs(self.base, self.m)
        spec = common.read_yaml(self.base / 'cases/TC-PF-1/case-spec.yaml')
        self.assertEqual([step['id'] for step in spec['steps']], ['S1', 'S2'])
        self.assertEqual(spec['assertions'][0]['excel'], '页面提示“已保存”')
        self.assertEqual(self.m['cases']['TC-PF-1']['spec_origin'], 'pathfinder')
        env, data, pages = specs.catalogs()
        errors, _ = specs.schema_errors(spec, common.read_json(self.base / 'cases/TC-PF-1/source.json'), env, data, pages)
        self.assertEqual(errors, [])
        rows = experience.sync_checklist(self.base, self.m)
        checklist = (self.base / 'checklist.md').read_text(encoding='utf-8')
        self.assertIn('D 页面入口', checklist)
        self.assertIn('订单列表页面', checklist)
        self.assertIn('E 操作路径存疑', checklist)
        self.assertIn('正常', checklist)
        self.assertNotIn('编辑网站页面 大概在哪里', checklist)
        self.assertFalse(rows['draft'])
        self.assertGreaterEqual(rows['question_count'], 2)
        experience.answer_sentence(self.base, self.m, 'D 订单列表页面=内容管理 → 订单，E 按原文可观察')
        self.assertEqual(entries.resolve('订单列表页面')['path_text'], '内容管理 → 订单')
        saved = common.read_yaml(self.root / 'knowledge/pathfinder-resolutions.yaml')
        self.assertTrue(saved['resolutions'])
        self.assertNotIn('TC-PF-1/S1', json.dumps(saved, ensure_ascii=False))
        import copy
        other = copy.deepcopy(self.m)
        other['questions'] = {}
        other.pop('checklist_issued', None)
        other['run_id'] = 'PF2'
        pathfinder.compile_run(self.base, other)
        second = experience.sync_checklist(self.base, other)
        self.assertEqual(second['question_count'], 0)
        self.assertNotIn('大概在哪里', (self.base / 'checklist.md').read_text(encoding='utf-8'))
        skill_after = {path.relative_to(SOURCE) for path in (SOURCE / 'skills/spec-pathfinder').rglob('*') if path.is_file()}
        self.assertEqual(skill_before, skill_after)
        with self.assertRaises(common.UiaError):
            pathfinder.output_dir(SOURCE / 'skills/spec-pathfinder')

    def test_v2_upgrades_code_evidence_and_marks_frontend_only_controls(self):
        real_before = {path.name: path.read_bytes() for path in (SOURCE / 'skills/spec-pathfinder/trial/real').rglob('*') if path.is_file()}
        self.workbook([
            ['TC-PF-3', '演示需求', '保存按钮', '', '点击「保存」', '页面提示“已保存”'],
            ['TC-PF-4', '演示需求', '富文本', '', '在富文本编辑器中加粗标题', '标题显示为粗体'],
        ])
        summary = pathfinder.compile_run(self.base, self.m, code_root=DEMO)
        self.assertEqual(summary['stage'], 'v2')
        self.assertTrue((self.base / 'spec-pathfinder/index/template-elements.json').is_file())
        self.assertTrue(str(self.base) in str((self.base / 'spec-pathfinder/index').resolve()))
        agent = next((self.base / 'spec-pathfinder').rglob('SPEC-agent-v2.md')).read_text(encoding='utf-8')
        human = next((self.base / 'spec-pathfinder').rglob('SPEC-human-v2.md')).read_text(encoding='utf-8')
        v1 = next((self.base / 'spec-pathfinder').rglob('SPEC-human-v1.md')).read_text(encoding='utf-8')
        upgrade = next((self.base / 'spec-pathfinder').rglob('UPGRADE-v1-v2.md')).read_text(encoding='utf-8')
        self.assertIn('llms.ftl:', agent)
        self.assertIn('置信度：高', agent)
        self.assertNotIn(str(DEMO), agent)
        self.assertNotIn('llms.ftl', human)
        self.assertNotIn('.java', human)
        self.assertNotIn('置信度：高', v1)
        self.assertIn('升级', upgrade)
        self.assertIn('引导探索', next((self.base / 'spec-pathfinder').rglob('DOUBTS-v2.md')).read_text(encoding='utf-8'))
        self.assertTrue(summary['guided'])
        pathfinder.project_specs(self.base, self.m)
        brief = pathfinder.generation_brief(self.base, 'TC-PF-3')
        self.assertEqual(brief['stage'], 'v2')
        self.assertIn('保存', brief['steps'][0]['action'])
        (self.base / 'knowledge-match.json').write_text(json.dumps({'matched': {'TC-PF-3': {}}}), encoding='utf-8')
        self.m['cases']['TC-PF-3']['spec_origin'] = 'pathfinder'
        generated = specs.generate(self.base, self.m, 'TC-PF-3')
        body = (self.base / 'runner/tests/generated/TC-PF-3.spec.ts').read_text(encoding='utf-8')
        self.assertIn('spec-pathfinder v2 entry:', body)
        self.assertIn('点击「保存」', body)
        self.assertIn('页面提示“已保存”', body)
        self.assertNotIn('getByRole', body)
        self.assertIn('UIA_EXPLORATION_REQUIRED', body)
        self.assertFalse(generated['runnable'])
        checklist = experience.checklist_text({'entries': experience.rows(self.base, self.m), 'answer': {'entries': {}}})
        self.assertIn('引导探索', checklist)
        experience.sync_checklist(self.base, self.m)
        experience.answer_sentence(self.base, self.m, 'E 已记录探索结论：工具栏在编辑器内，加粗后标题变粗')
        pathfinder.compile_run(self.base, self.m, code_root=DEMO)
        self.assertEqual(experience.sync_checklist(self.base, self.m)['question_count'], 0)
        real_after = {path.name: path.read_bytes() for path in (SOURCE / 'skills/spec-pathfinder/trial/real').rglob('*') if path.is_file()}
        self.assertEqual(real_before, real_after)

    def test_go_accepts_optional_code_path(self):
        args = cli.parser().parse_args(['go', 'cases.xlsx', '--code', 'project/src'])
        self.assertEqual(args.code, 'project/src')

    def test_module_context_supplies_named_entry_when_steps_omit_page_suffix(self):
        source = {'module': '产品管理', 'sheet': '产品用例', 'steps': ['点击新增'], 'expected': '显示成功'}
        model = pathfinder.build_case('TC-SYN-ENTRY', {}, source, {'pages': {}, 'targets': {}})
        self.assertEqual(model['entry_page'], '产品管理')
        self.assertEqual(model['doubts'][0]['kind'], 'entry')

    def test_open_entry_resolves_page_id_not_colliding_control_id(self):
        pages = {
            'pages': {'page-product-admin': {'label': '产品管理', 'entry': '产品管理'}},
            'targets': {'target-product-admin': {'label': '产品管理'}},
        }
        source = {'module': '产品管理', 'sheet': '产品用例', 'steps': ['进入「产品管理」'], 'expected': '页面已打开'}
        model = pathfinder.build_case('TC-SYN-PAGE', {}, source, pages)
        self.assertEqual(model['steps'][0]['target'], 'page-product-admin')
        self.assertNotEqual(model['steps'][0]['target'], 'target-product-admin')
