import argparse
import json
import os
import unittest
from unittest.mock import patch

import tests.test_entries as entry_tests
from uia_core import cli, common, entries, experience, exploration, profiles


class Fix3Tests(unittest.TestCase):
    setUp = entry_tests.EntryHintsTests.setUp
    case = entry_tests.EntryHintsTests.case
    locked = entry_tests.EntryHintsTests.locked
    snapshot = entry_tests.EntryHintsTests.snapshot
    generator = entry_tests.EntryHintsTests.generator
    def test_only_start_pages_with_page_names_join_checklist(self):
        self.case('C1', '?内容编辑器')
        spec = common.read_yaml(self.base / 'C1/case-spec.yaml')
        spec.update(steps=[{'target': '?别的页面'}], assertions=[{'checks': [{'target': '?faq.schema'}]}])
        common.atomic_write(self.base / 'C1/case-spec.yaml', spec, as_yaml=True)
        self.case('C2', '?faq.schema')
        self.case('C3', '?data')
        self.assertEqual([r['page'] for r in entries.page_rows(self.base, self.m)], ['内容编辑器'])
        catalog = common.read_yaml(entries.knowledge_path('page-map.yaml'))
        catalog['pages']['faq.schema'] = {'label': 'Structured view'}
        common.atomic_write(entries.knowledge_path('page-map.yaml'), catalog, as_yaml=True)
        self.assertIsNotNone(entries.resolve('faq.schema'))

    def test_non_page_answer_is_saved_and_never_navigated(self):
        for text in ['不是页面，是数据', '不是后台页面，是结构化数据', '非页面']:
            entries.add(self.m, '数据页面=' + text)
            self.assertTrue(entries.resolve('数据页面')['not_a_page'])
            args = cli.parser().parse_args(['snapshot', '--run', 'R', '--entry', '数据页面'])
            with patch.object(cli, 'locked_run', self.locked), patch.object(profiles, 'invoke_snapshot') as run:
                result = cli.execute(args)
            run.assert_not_called()
            self.assertFalse(result['entry_reached'])
            self.assertTrue(result['not_a_page'])
        entries.add(self.m, '数据页面=内容管理 → 产品')
        self.assertFalse(entries.resolve('数据页面')['not_a_page'])

    def test_checklist_d_answer_marks_non_page(self):
        self.case('C1', '?数据页面')
        experience.sync_checklist(self.base, self.m)
        experience.answer_sentence(self.base, self.m, 'D 数据页面=不是后台页面，是结构化数据')
        self.assertTrue(entries.resolve('数据页面')['not_a_page'])

    def test_path_text_routes_area_before_frame_and_suggests_confirmation(self):
        entries.add(self.m, '内容编辑器=内容管理 → 产品（或文章）→ 编辑，在内嵌编辑器框架 #tiptap-iframe 里')
        result, run = self.snapshot(extra=['--step', 'click:text=工具栏'])
        self.assertEqual(run.call_args.args[2], '内容管理')
        self.assertEqual(run.call_args.args[-1], ['click:text=产品', 'click:text=编辑', 'click:text=工具栏'])
        self.assertEqual(run.call_args.kwargs['entry_steps'], 2)
        self.assertEqual(result['frame_hint'], '#tiptap-iframe')
        self.assertTrue(result['entry_reached'])
        self.assertIn('hints confirm --run R', result['confirm_command'])
        self.assertIn('--frame', result['confirm_command'])
        for arrow in ['->', '>', '＞']:
            route = entries.navigation_hint({'path_text': '网站编辑' + arrow + '设置(任选),说明'})
            self.assertEqual(route['node'], 'editor')
            self.assertEqual(route['steps'], ['click:text=设置'])
        route = entries.navigation_hint({'path_text': '工作台 → 编辑'})
        self.assertEqual(route['open_target'], 'dashboard')

    def test_expected_entry_frame_must_be_reached(self):
        entries.add(self.m, '内容编辑器=内容管理 → 产品 → 编辑，在 #compose-frame 里')
        args = cli.parser().parse_args(['snapshot', '--run', 'R', '--entry', '内容编辑器'])
        with patch.object(cli, 'locked_run', self.locked), patch.object(cli, 'save'), \
                patch.object(profiles, 'invoke_snapshot', return_value={'structure': {'failed_step': None, 'frame_reached': False}}):
            result = cli.execute(args)
        self.assertFalse(result['entry_reached'])
        self.assertNotIn('confirm_command', result)

    def test_frame_class_and_generator_route_and_seed_area(self):
        entries.add(self.m, '内容编辑器=内容管理 → 产品 → 编辑，在 .compose-frame 里')
        result, seen = self.generator({'reached': True, 'reached_entry': True})
        self.assertIn('UIA_SEED_ENTRY="content-admin"', ' '.join(seen['command']))
        self.assertIn('click:text=产品', seen['command'][-1])
        self.assertIn('.compose-frame', seen['command'][-1])

    def test_sandbox_marker_and_start_failure_cannot_satisfy_demo(self):
        with patch.dict(os.environ, {}, clear=True):
            command = exploration.generator_command('codex', '/runner', {}, 'prompt', 'model')
            self.assertIn('workspace-write', command)
        for marker in ['CODEX_SANDBOX', '__CURSOR_SANDBOX_ENV_RESTORE']:
            with patch.dict(os.environ, {marker: '1'}, clear=True):
                command = exploration.generator_command('codex', '/runner', {}, 'prompt', 'model')
                self.assertIn('--dangerously-bypass-approvals-and-sandbox', command)
                self.assertNotIn('-s', command)
        entries.add(self.m, '内容编辑器=内容管理 → 产品 → 编辑')
        fake = argparse.Namespace(stdout='', stderr='Permission denied writing codex session', returncode=1)
        with patch.object(exploration, 'codex_binary', return_value='/bin/codex'), \
                patch.object(profiles, 'agent_env', return_value={'cwd': '/runner', 'env': {}}):
            result = exploration.run_generator(self.base, self.m, 'insert.widget', 'observe',
                                               runner=lambda *a: fake, entry='内容编辑器')
        self.assertEqual(result['recorded']['failure_class'], 'subagent_start')
        self.assertEqual(common.read_json(self.base / result['report'])['failure_class'], 'subagent_start')
        result['recorded'].update(reached_entry=True, entry_reached=True, failed_interaction='drag')
        self.m['cases']['C1']['unknown_nodes'] = ['insert.widget']
        with self.assertRaisesRegex(common.UiaError, 'generator'):
            exploration.demo_gate(self.m, 'insert.widget', ['C1'], 'drag', page='内容编辑器')
