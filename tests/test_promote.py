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

    def test_unreached_report_is_refused(self):
        bad = dict(REPORT, route={'reached': False, 'reached_entry': False})
        (self.base / 'exploration/generator-x.json').write_text(json.dumps(bad), encoding='utf-8')
        with self.assertRaises(common.UiaError):
            entries.promote(self.base, self.m, 'exploration/generator-x.json')


if __name__ == '__main__':
    unittest.main()
