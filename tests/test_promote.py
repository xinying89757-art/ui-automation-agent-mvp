import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from uia_core import common, entries

REPORT = {'purpose': 'faq-editor.entry', 'entry': '新版内容编辑器', 'reached': True, 'reached_entry': True,
          'route': {'reached': True, 'reached_entry': True,
                    'route': ['click:text=产品',
                              'click:iframe#prod a[href*="prod_new_update"] (first product row, 编辑)',
                              'click:iframe#prod >> #tiptap-iframe >> iframe.tiptap-iframe button.placeholder-plus',
                              'click:iframe#prod >> #tiptap-iframe >> iframe.tiptap-iframe .slash-card (FAQ)'],
                    'frames': ['iframe#prod', '#tiptap-iframe', 'iframe.tiptap-iframe'],
                    'targets': {'faq_cancel': 'iframe#prod >> #tiptap-iframe >> iframe.tiptap-iframe button.faq-editor-action filtered by exact text 取消',
                                'faq_question_title': 'iframe#prod >> #tiptap-iframe >> iframe.tiptap-iframe input.faq-editor-input[placeholder="请输入FAQ标题"]',
                                'product_form_cancel': 'iframe#prod a.new_cancel_btn'}}}


class PromoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        know = self.tmp / 'assets/playwright-runner/knowledge'
        know.mkdir(parents=True)
        (know / 'entries.yaml').write_text('schema_version: entry-hints.v1\nentries: {}\n', encoding='utf-8')
        (know / 'page-map.yaml').write_text('schema_version: page-map.v1\npages: {content-admin: {entry: 内容管理}}\ntargets: {faq-editor.entry.faq.cancel: {selector: keep}}\n', encoding='utf-8')
        self.base = self.tmp / 'run'
        (self.base / 'exploration').mkdir(parents=True)
        (self.base / 'exploration/generator-faq-editor.entry.json').write_text(json.dumps(REPORT, ensure_ascii=False), encoding='utf-8')
        self.patch = patch.object(common, 'ROOT', self.tmp)
        self.patch.start()
        self.m = {'config': {}}
        entries.add(self.m, '新版内容编辑器=内容管理 → 产品（或文章）→ 编辑，在内嵌编辑器框架 #tiptap-iframe 里')

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.tmp)

    def test_locator_parsing(self):
        row = entries.locator_target(REPORT['route']['targets']['faq_cancel'])
        self.assertEqual(row, {'frame': 'iframe#prod', 'nested_frames': ['#tiptap-iframe', 'iframe.tiptap-iframe'],
                               'selector': 'button.faq-editor-action:text-is("取消")'})
        self.assertEqual(entries.locator_target('iframe#prod a.new_cancel_btn'), {'frame': 'iframe#prod', 'selector': 'a.new_cancel_btn'})
        self.assertEqual(entries.locator_target('#x [data-a="b c"]'), {'selector': '#x [data-a="b c"]'})

    def test_promote_writes_targets_and_confirms_entry_without_overwrite(self):
        result = entries.promote(self.base, self.m, 'exploration/generator-faq-editor.entry.json')
        catalog = common.read_yaml(self.tmp / 'assets/playwright-runner/knowledge/page-map.yaml')
        t = catalog['targets']
        self.assertEqual(t['faq-editor.entry.faq.cancel'], {'selector': 'keep'})
        self.assertIn('faq-editor.entry.faq.cancel', result['targets_skipped'])
        self.assertEqual(t['faq-editor.entry.faq.question.title']['nested_frames'], ['#tiptap-iframe', 'iframe.tiptap-iframe'])
        self.assertEqual(t['faq-editor.entry.route.2'], {'frame': 'iframe#prod', 'selector': 'a[href*="prod_new_update"]',
                                                       'source': 'generator:faq-editor.entry', 'confirmed': False})
        self.assertEqual(result['route_steps'][0], 'click:text=产品')
        hint = entries.resolve('新版内容编辑器')
        self.assertTrue(hint['confirmed'])
        self.assertEqual(hint['steps'][:3], ['click:content-admin', 'click:text=产品', 'click:faq-editor.entry.route.2'])
        self.assertEqual(hint['frame'], entries.FRAME_JOIN.join(REPORT['route']['frames']))
        self.assertEqual(result['entry_confirmed'], '新版内容编辑器')

    def test_type_route_step_is_promoted(self):
        rep = dict(REPORT, route=dict(REPORT['route'], route=['click:text=产品',
            {'verb': 'type', 'target': 'iframe#prod >> #tiptap-iframe >> iframe.tiptap-iframe .ProseMirror', 'value': '/'}]))
        (self.base / 'exploration/generator-t.json').write_text(json.dumps(rep, ensure_ascii=False), encoding='utf-8')
        result = entries.promote(self.base, self.m, 'exploration/generator-t.json')
        self.assertEqual(result['route_steps'][-1], 'type:faq-editor.entry.route.2=/')

    def test_unreached_report_is_refused(self):
        bad = dict(REPORT, route={'reached': False, 'reached_entry': False})
        (self.base / 'exploration/generator-x.json').write_text(json.dumps(bad), encoding='utf-8')
        with self.assertRaises(common.UiaError):
            entries.promote(self.base, self.m, 'exploration/generator-x.json')


if __name__ == '__main__':
    unittest.main()


class StructuredTargetTests(unittest.TestCase):
    def test_playwright_call_text_and_objects(self):
        f = 'iframe[name="prod"] >> #tiptap-iframe >> iframe'
        self.assertEqual(entries.locator_target("getByRole('button', { name: '添加FAQ' }) scoped to " + f),
                         {'role': 'button', 'name': '添加FAQ', 'frame': 'iframe[name="prod"]', 'nested_frames': ['#tiptap-iframe', 'iframe']})
        self.assertEqual(entries.locator_target("getByText('FAQ', { exact: true }) scoped to " + f)['selector'], 'text="FAQ"')
        self.assertEqual(entries.locator_target({'frames': ['iframe#prod'], 'role': 'textbox', 'name': '请输入FAQ标题'}),
                         {'role': 'textbox', 'name': '请输入FAQ标题', 'frame': 'iframe#prod'})
        self.assertEqual(entries.locator_target({'frames': [], 'css': '.x'}), {'selector': '.x'})
        with self.assertRaises(common.UiaError):
            entries.locator_target('locator(".x").filter(something)')


class StructuredRouteTests(PromoteTests):
    def test_object_route_steps_and_literal_fill(self):
        report = dict(REPORT, route=dict(REPORT['route'], route=[
            'click:text=产品',
            {'verb': 'fill', 'target': {'frames': ['iframe#prod', '#tiptap-iframe', 'iframe'], 'role': 'textbox'}, 'value': '/'},
            'fill:iframe#prod >> #x=/',
            {'verb': 'click', 'target': {'frames': ['iframe#prod', '#tiptap-iframe', 'iframe'], 'text': 'FAQ'}}], targets={}))
        (self.base / 'exploration/generator-o.json').write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
        result = entries.promote(self.base, self.m, 'exploration/generator-o.json', prefix='p')
        self.assertEqual(result['route_steps'], ['click:text=产品', 'fill:p.route.2=/', 'fill:p.route.3=/', 'click:p.route.4'])


class AddTargetTests(PromoteTests):
    def test_add_target_requires_evidence_and_no_silent_overwrite(self):
        r = entries.add_target(self.base, self.m, 'faq-editor.add', '{"frames": ["iframe#prod", "#tiptap-iframe"], "role": "button", "name": "添加FAQ"}',
                               'exploration/generator-faq-editor.entry.json')
        self.assertEqual(r['row']['nested_frames'], ['#tiptap-iframe'])
        with self.assertRaises(common.UiaError):
            entries.add_target(self.base, self.m, 'faq-editor.add', '{"css": ".x"}', 'exploration/generator-faq-editor.entry.json')
        with self.assertRaises(common.UiaError):
            entries.add_target(self.base, self.m, 'faq-editor.other', '{"css": ".x"}', 'exploration/missing.json')


class SingleCatalogTests(PromoteTests):
    def test_new_target_is_visible_to_spec_gen_catalog_and_index(self):
        from uia_core import knowledge
        (self.tmp / 'knowledge').mkdir()
        old = knowledge.ROOT; knowledge.ROOT = None
        self.addCleanup(lambda: setattr(knowledge, 'ROOT', old))
        entries.add_target(self.base, self.m, 'md.dialog', '{"css": ".md"}', 'exploration/generator-faq-editor.entry.json')
        # specs.catalogs() reads ROOT/knowledge/page-map.yaml first: the shared copy must carry the new target.
        self.assertIn('md.dialog', common.read_yaml(self.tmp / 'knowledge/page-map.yaml')['targets'])
        ids = [r['id'] for r in common.read_yaml(self.tmp / 'knowledge/index.yaml')['entries']]
        self.assertIn('target.md.dialog', ids)


class LiteralRouteTests(unittest.TestCase):
    def test_input_placeholder_truncates_entry_route(self):
        h = entries.literal_route({'steps': ['goto:/a', 'click:x', 'fill:y=${INPUT}', 'click:text=FAQ']})
        self.assertEqual(h['steps'], ['goto:/a', 'click:x'])
        self.assertEqual(h['route_truncated_at'], 'fill:y')


class DraftAndResourceTests(PromoteTests):
    def test_resource_target(self):
        r = entries.add_target(self.base, self.m, 'product.public', None, 'exploration/generator-faq-editor.entry.json',
                               resource='/products/demo.html')
        self.assertEqual(r['row']['resource'], {'path': '/products/demo.html'})
        with self.assertRaises(common.UiaError):
            entries.add_target(self.base, self.m, 'product.public2', None, 'exploration/generator-faq-editor.entry.json',
                               resource='https://x.test/p')

    def test_draft_generator_prompt_and_gate(self):
        import argparse
        from uia_core import exploration, profiles
        seen = {}
        def runner(cmd, timeout):
            seen['prompt'] = cmd[-1]
            return argparse.Namespace(stdout='', stderr='', returncode=0)
        with patch.object(exploration, 'codex_binary', return_value='/bin/codex'), \
                patch.object(profiles, 'agent_env', return_value={'cwd': '/runner', 'env': {}}):
            with self.assertRaises(common.UiaError):
                exploration.run_generator(self.base, self.m, 'p', 'plan', runner=runner, draft=True)
            self.m['config']['mutation'] = {'allowed': True}
            exploration.run_generator(self.base, self.m, 'p', 'plan', runner=runner, draft=True)
        self.assertIn('Draft mode', seen['prompt'])
        self.assertNotIn('Read-only', seen['prompt'])


class AliasLintTests(unittest.TestCase):
    def test_written_back_aliases_are_one_element(self):
        from uia_core import specs
        row = {'role': 'button', 'name': '保存', 'frame': 'iframe#prod'}
        body = "await frame.getByRole('button', { name: '保存' }).click();"
        aliases = {'a.save': dict(row, source='generator:a'), 'b.save': dict(row, source='observed:x', alias_of='a.save')}
        self.assertEqual([e for e in specs.locator_errors(body, {'targets': aliases}) if 'non-unique' in e], [])
        real = {'x.save': dict(row), 'y.save': dict(row)}
        self.assertTrue([e for e in specs.locator_errors(body, {'targets': real}) if 'non-unique' in e])
        self.assertEqual(entries.same_locator({'a.save': dict(row, source='g')}, dict(row), 'b.save'), 'a.save')
