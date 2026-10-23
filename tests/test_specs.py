import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uia_core import specs, common, workflow, cli


class CaseSpecTests(unittest.TestCase):
    def setUp(self):
        self.env, self.data, self.pages = specs.catalogs()
        self.source = {'case_id': 'T1', 'expected': ['1. 弹窗显示管理txt文件。\n2. 弹窗关闭。']}
        self.spec = {
            'schema_version': 'case-spec.v1', 'case_id': 'T1', 'intent': '检查窗口',
            'automatable': {'status': 'yes', 'reason': 'known'}, 'required_env': [],
            'data_prep': {}, 'mutation_scope': [], 'start_page': 'editor',
            'steps': [{'id': 'S1', 'verb': 'open', 'target': 'txt.dialog'}],
            'assertions': [{'id': 'A1', 'after': 'S1', 'excel': '1. 弹窗显示管理txt文件。',
                            'checks': [{'target': 'txt.dialog', 'op': 'visible'}]}], 'questions': []}

    def errors(self):
        return specs.schema_errors(self.spec, self.source, self.env, self.data, self.pages)[0]

    def test_verbatim_line_and_whole_cell_only(self):
        self.assertEqual(self.errors(), [])
        self.spec['assertions'][0]['excel'] = '弹窗显示管理txt文件'
        self.assertTrue(self.errors())
        self.spec['assertions'][0]['excel'] = self.source['expected'][0]
        self.assertEqual(self.errors(), [])

    def test_schema_rejects_implicit_targets_selectors_and_unknown_verbs(self):
        for change in ({'target': '#dialog'}, {'target': None}, {'verb': 'do_it'}, {'extra': 1}):
            before = copy.deepcopy(self.spec)
            self.spec['steps'][0].update(change)
            self.assertTrue(self.errors(), change)
            self.spec = before

    def test_unknown_targets_collected_without_fabricating_locators(self):
        self.spec['steps'][0]['target'] = '?new_entry'
        errors, unknown = specs.schema_errors(self.spec, self.source, self.env, self.data, self.pages)
        self.assertEqual(errors, [])
        self.assertEqual(unknown, ['?new_entry'])
        self.assertIsNone(specs.locator_expression('?new_entry', self.pages))

    def test_menu_option_clicks_get_keyboard_pattern_automatically(self):
        self.assertIn('MENU_KEYBOARD', specs.interaction_patterns_for_target({'role':'option'}, 'click'))
        self.assertIn('MENU_KEYBOARD', specs.interaction_patterns_for_target({'selector':'[role="menuitem"]'}, 'click'))
        self.assertIn('MENU_KEYBOARD', specs.interaction_patterns_for_target({'patterns':['MENU_KEYBOARD']}, 'click'))
        self.assertIn('MENU_KEYBOARD', specs.interaction_patterns_for_target({}, 'click', 'article.slash-command-menu'))
        self.assertIn('MENU_KEYBOARD', specs.interaction_patterns_for_target({'selector':'[role="listbox"]'}, 'click'))
        self.assertNotIn('MENU_KEYBOARD', specs.interaction_patterns_for_target({'role':'option'}, 'fill'))

    def test_extensible_env_and_data_vocabulary(self):
        self.spec['required_env'] = ['new_permission']
        self.assertTrue(self.errors())
        self.env['new_permission'] = {'label': 'new permission'}
        self.assertEqual(self.errors(), [])
        self.spec['mutation_scope'] = ['faq']
        self.spec['data_prep'] = {'faq.count': True}
        self.assertTrue(self.errors())
        self.spec['data_prep'] = {'faq.count': 5}
        self.assertEqual(self.errors(), [])

    def test_close_needs_hidden_assertion_at_its_step(self):
        self.spec['steps'].append({'id': 'S2', 'verb': 'close', 'target': 'txt.cancel'})
        self.assertTrue(self.errors())
        self.spec['assertions'].append({'id': 'A2', 'after': 'S2', 'excel': '2. 弹窗关闭。',
                                        'checks': [{'target': 'txt.dialog', 'op': 'hidden'}]})
        self.assertEqual(self.errors(), [])

    def test_marker_coverage_recomputes_after_lines_move(self):
        body = "// @step S1\nawait page.click();\nawait businessAssertion('A1', async () => {});"
        self.assertEqual(specs.coverage(body, 'a.ts')['assertions']['A1']['line'], 3)
        self.assertEqual(specs.coverage('\n\n' + body, 'a.ts')['assertions']['A1']['line'], 5)
        with self.assertRaises(common.UiaError):
            specs.coverage(body + '\n// @step S1', 'a.ts')

    def test_fixture_dialog_duplicate_icon_and_close_gate(self):
        good = "import { test, expect } from '../support/fixtures.js';\n"
        self.assertEqual(specs.locator_errors(good, self.pages), [])
        self.assertTrue(specs.locator_errors("import { test } from '@playwright/test';", self.pages))
        pages = copy.deepcopy(self.pages)
        pages['targets']['tab'] = {'role': 'link', 'name': 'llms.txt', 'dialog': 'txt.dialog', 'scope': '#backstage-dialog-customizeFile'}
        pages['targets']['contact'] = {'role': 'link', 'name': 'Contact Us', 'matches': 2}
        self.assertTrue(specs.locator_errors(good + "page.getByRole('link', { name: 'llms.txt' });", pages))
        self.assertTrue(specs.locator_errors(good + "page.locator('strong').filter({ hasText: '管理txt文件' });", pages))
        self.assertTrue(specs.locator_errors(good + "page.getByText('取消');", pages))
        self.assertTrue(specs.locator_errors(good + "page.getByRole('link', { name: 'Contact Us' });", pages))
        self.assertTrue(specs.locator_errors(good + "page.getByRole('link', { name: '\ue001设置' });", pages))
        self.assertTrue(specs.locator_errors(good + "// @step S2\nawait cancel.click();", pages))
        self.assertEqual(specs.locator_errors(good + "// @step S2\nawait cancel.click();\nawait expect(dialog).toBeHidden();", pages), [])

    def test_snapshot_refs_are_forbidden(self):
        for value in ['aria-ref=f2e55', '[ref=f1e10]', {'snapshot_ref': 'e12'}, "'f2e12'"]:
            self.assertTrue(specs.has_snapshot_ref(value))
        self.assertFalse(specs.has_snapshot_ref({'selector': '#backstage-innerpage'}))
        pages = copy.deepcopy(self.pages)
        pages['targets']['icon'] = {'role': 'link', 'name': chr(0xE001) + '管理txt文件'}
        expression = specs.locator_expression('icon', pages)
        self.assertIn('new RegExp', expression)
        self.assertNotIn(chr(0xE001), expression)

    def test_save_read_back_lints_as_warning_and_generator_renders_block(self):
        import yaml
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); folder = base / 'cases/T1'; folder.mkdir(parents=True)
            (base / 'runner/tests/generated').mkdir(parents=True)
            common.atomic_write(folder / 'source.json', self.source)
            self.spec['mutation_scope'] = ['llms.txt']
            self.spec['steps'] = [{'id':'S1','verb':'fill','target':'txt.overview','value':'wanted'},
                                  {'id':'S2','verb':'click','target':'txt.save'}]
            self.spec['assertions'] = [{'id':'A1','after':'S2','excel':self.source['expected'][0],
                                        'checks':[{'target':'txt.saved','op':'visible'}]}]
            common.atomic_write(folder / 'case-spec.yaml', self.spec, as_yaml=True)
            case = {'case_id':'T1','source':'cases/T1/source.json','case_spec':'cases/T1/case-spec.yaml','source_hash':'hash','attempts':[]}
            manifest = {'cases':{'T1':case},'config':{'mutation':{'allowed':True,'scope':['llms.txt']}},'questions':{},'history':[]}
            linted = specs.lint(base, manifest, ['T1'], record=False)
            self.assertTrue(linted['valid'])
            self.assertIn('保存步骤缺少读回检查', linted['cases']['T1']['warnings'])
            self.spec['read_back'] = [{'id':'R1','after':'S2','target':'txt.overview','value':'wanted',
                                      'reopen':['settings','txt.entry'],'save_target':'network.llms.save'}]
            common.atomic_write(folder / 'case-spec.yaml', self.spec, as_yaml=True)
            generated_pages = copy.deepcopy(self.pages)
            generated_pages['targets']['txt.save']['patterns'] = ['RERENDER_RELOCATE']
            with patch.object(specs, 'catalogs', return_value=(self.env, self.data, generated_pages)), \
                    patch.object(specs, 'register_script', return_value={'script':'runner/tests/generated/T1.spec.ts'}):
                specs.generate(base, manifest, 'T1')
            generated = (base / 'runner/tests/generated/T1.spec.ts').read_text()
            self.assertIn('verifyPersisted(page, caseContext', generated)
            self.assertIn('readFieldValue(', generated)
            self.assertIn('await page.reload()', generated)
            self.assertIn('performWithPatterns(page, () =>', generated)
            self.assertIn("target => target.click()", generated)

    def test_lint_records_true_first_pass_and_cross_case_duplicates(self):
        import yaml
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            cases = {}
            for cid in ('T1', 'T2'):
                folder = base / 'cases' / cid
                folder.mkdir(parents=True)
                source = dict(self.source, case_id=cid)
                spec = copy.deepcopy(self.spec); spec['case_id'] = cid
                common.atomic_write(folder / 'source.json', source)
                (folder / 'case-spec.yaml').write_text(yaml.safe_dump(spec, allow_unicode=True))
                cases[cid] = {'case_id': cid, 'source': f'cases/{cid}/source.json', 'source_hash': cid,
                              'stage': 'spec', 'work_status': 'pending', 'result': None, 'attempts': []}
            m = {'cases': cases, 'questions': {}, 'history': []}
            result = specs.lint(base, m)
            self.assertFalse(result['valid'])
            self.assertEqual(result['first_pass']['passed'], 0)
            spec['assertions'][0]['checks'][0] = {'target': 'txt.title', 'op': 'text', 'value': '管理txt文件'}
            (base / 'cases/T2/case-spec.yaml').write_text(yaml.safe_dump(spec, allow_unicode=True))
            self.assertTrue(specs.lint(base, m)['valid'])
            self.assertEqual(specs.lint(base, m)['first_pass']['passed'], 0)

    def test_generator_todo_is_explicit_and_deterministic(self):
        import yaml
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); (base / 'cases/T1').mkdir(parents=True)
            common.atomic_write(base / 'cases/T1/source.json', self.source)
            self.spec['steps'][0]['target'] = '?unknown'
            (base / 'cases/T1/case-spec.yaml').write_text(yaml.safe_dump(self.spec, allow_unicode=True))
            case = {'case_id': 'T1', 'source': 'cases/T1/source.json', 'source_hash': 'x', 'stage': 'spec', 'work_status': 'pending', 'result': None}
            m = {'cases': {'T1': case}, 'questions': {}, 'history': []}
            first = specs.generate(base, m, 'T1')
            body = (base / first['script']).read_bytes()
            self.assertFalse(first['runnable'])
            self.assertIn(b'TODO explore: S1 ?unknown', body)
            self.assertIn(b'UIA_EXPLORATION_REQUIRED', body)
            self.assertIn(b'test.step("uia-step:S1"', body)
            specs.generate(base, m, 'T1')
            self.assertEqual(body, (base / first['script']).read_bytes())
            self.assertNotIn('registration', case)

    def test_unrelated_invalid_contract_does_not_block_independent_generation(self):
        import yaml
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); cases = {}
            for cid in ('T1', 'T2'):
                folder = base / 'cases' / cid; folder.mkdir(parents=True)
                common.atomic_write(folder / 'source.json', dict(self.source, case_id=cid))
                spec = copy.deepcopy(self.spec); spec['case_id'] = cid
                spec['steps'][0]['target'] = '?unknown'
                if cid == 'T2': spec['steps'][0]['verb'] = 'invalid'
                (folder / 'case-spec.yaml').write_text(yaml.safe_dump(spec, allow_unicode=True))
                cases[cid] = {'case_id': cid, 'source': f'cases/{cid}/source.json', 'source_hash': cid,
                              'stage': 'spec', 'work_status': 'pending', 'result': None}
            result = specs.generate(base, {'cases': cases, 'questions': {}, 'history': []}, 'T1')
            self.assertIn('S1 ?unknown', result['todos'])

    def test_known_template_registers_fixture_and_ai_registration_derives_coverage(self):
        import yaml
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            shutil.copytree(Path(__file__).resolve().parents[1] / 'assets/playwright-runner', base / 'runner',
                            ignore=shutil.ignore_patterns('node_modules', 'results'))
            (base / 'cases/T1').mkdir(parents=True)
            common.atomic_write(base / 'cases/T1/source.json', self.source)
            (base / 'cases/T1/case-spec.yaml').write_text(yaml.safe_dump(self.spec, allow_unicode=True))
            case = {'case_id': 'T1', 'source': 'cases/T1/source.json', 'source_hash': 'x',
                    'intent': 'cases/T1/automation-intent.yaml', 'reuse_plan': 'cases/T1/reuse-plan.slim.yaml',
                    'stage': 'spec', 'work_status': 'pending', 'result': None, 'attempts': [], 'isolated': False}
            m = {'cases': {'T1': case}, 'questions': {}, 'history': [],
                 'config': {'execution': {'workers': 1, 'timeout_ms': 60000}, 'mutation': {'allowed': False, 'scope': []}}}
            first = specs.generate(base, m, 'T1')
            self.assertTrue(first['runnable'])
            script = base / first['script']
            self.assertIn('support/fixtures.js', script.read_text())
            initial_line = first['coverage']['assertions']['A1']['line']
            script.write_text('\n\n' + script.read_text())
            registered = workflow.register(base, m, 'T1', {'case_id': 'T1', 'script': first['script']})
            self.assertEqual(registered['coverage']['assertions']['A1']['line'], initial_line + 2)
            script.write_text(script.read_text().replace('support/fixtures.js', 'support/test.js'))
            with self.assertRaises(common.UiaError):
                workflow.register(base, m, 'T1', {'case_id': 'T1', 'script': first['script']})

    def test_business_questions_share_precondition_checklist_and_wait_for_answer(self):
        from uia_core.preconditions import apply_precondition_answer
        case = {'case_id': 'T1', 'stage': 'spec', 'work_status': 'pending', 'result': None, 'precondition_items': [], 'attempts': []}
        q = {'case_ids': ['T1'], 'answer': {'available': []},
             'business_questions': [{'question': 'Confirm format?', 'case_ids': ['T1']}]}
        manifest = {'cases': {'T1': case}}
        apply_precondition_answer(manifest, q)
        self.assertEqual(case['work_status'], 'waiting_human')
        q['answer']['business'] = {'Confirm format?': 'Use documented format'}
        apply_precondition_answer(manifest, q)
        self.assertEqual(case['work_status'], 'pending')

    def test_cli_scope_and_spec_commands(self):
        args = cli.parser().parse_args(['snapshot', '--run', 'x', '--node', 'editor', '--frame', '#backstage-innerpage', '--scope', '#box'])
        self.assertEqual(args.scope, '#box')
        self.assertEqual(cli.parser().parse_args(['spec', 'lint', '--run', 'x']).action, 'lint')


if __name__ == '__main__':
    unittest.main()
