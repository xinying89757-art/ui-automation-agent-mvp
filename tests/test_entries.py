import argparse
import contextlib
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uia_core import cli, common, entries, experience, exploration, metrics, preconditions, profiles, reports, workflow


class EntryHintsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / 'runs/R'
        self.base.mkdir(parents=True)
        for module in (common, experience):
            p = patch.object(module, 'ROOT', self.root)
            p.start(); self.addCleanup(p.stop)
        p = patch.object(experience, 'memory_path', return_value=self.root / 'private/memory.json')
        p.start(); self.addCleanup(p.stop)
        self.m = {'run_id': 'R', 'cases': {}, 'questions': {}, 'history': [], 'sources': [], 'exploration': [],
                  'interaction_mode': 'once', 'config': {'auth': {}, 'targets': {}, 'network': {'mode': 'direct'}}}
        common.atomic_write(entries.knowledge_path('page-map.yaml'), {
            'pages': {'dashboard': {'entry': '工作台'}},
            'targets': {'detail.open': {'label': '商品详情页', 'selector': '#detail', 'aliases': ['商品详情']}}}, as_yaml=True)
        self.case('C1')

    def case(self, cid, page=None, raw=''):
        common.atomic_write(self.base / cid / 'source.json', {'preconditions': raw})
        common.atomic_write(self.base / cid / 'case-spec.yaml', {
            'start_page': page or 'dashboard', 'steps': [], 'assertions': [], 'required_env': []}, as_yaml=True)
        self.m['cases'][cid] = {'case_id': cid, 'source': cid + '/source.json', 'case_spec': cid + '/case-spec.yaml',
                               'work_status': 'pending', 'stage': 'spec', 'result': None, 'attempts': []}

    @contextlib.contextmanager
    def locked(self, run):
        yield self.base / 'run.json', self.m

    def run_go(self, hints=None):
        # No workbook or site: the importer and all runtime boundaries are mocked.
        source = self.root / 'source.txt'
        source.write_text('mock import source')
        self.m['sources'] = [{'sha256': common.file_hash(source), 'path': str(source)}]
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(profiles, 'profile_path', return_value=self.root / 'profile.json'))
            stack.enter_context(patch.object(experience, 'locked_run', self.locked))
            stack.enter_context(patch.object(experience, 'save'))
            for name in ('init', 'scaffold', 'refresh', 'bind_specs', 'import_excel'):
                stack.enter_context(patch.object(workflow, name))
            stack.enter_context(patch('uia_core.remote_checks.expire'))
            stack.enter_context(patch.object(profiles, 'invoke_login'))
            stack.enter_context(patch('uia_core.runtime.preflight'))
            stack.enter_context(patch.object(reports, 'make_report', return_value={}))
            stack.enter_context(patch.object(experience, '_run_ready'))
            stack.enter_context(patch('uia_core.specs.generate'))
            args = ['go', str(source), '--profile', 'test']
            if hints:
                args += ['--hints', hints]
            return cli.execute(cli.parser().parse_args(args))

    def test_parse_normalization_aliases_and_frame_notes(self):
        hints = entries.parse('入口提示： 新版编辑器 = 管理 → 编辑（#compose-frame）；商品列表=管理 → 商品')
        self.assertEqual(hints[0]['frame'], '#compose-frame')
        self.assertEqual(entries.key('？Ｎｅｗ Page'), 'newpage')
        entries.store(self.m, [dict(hints[0], aliases=['内容编辑面板'])])
        self.assertEqual(entries.resolve(' 内容编辑面板 ')['label'], '新版编辑器')
        self.assertIsNotNone(entries.resolve('?新版编辑器面板'))
        self.assertIsNone(entries.resolve('页'))
        entries.add(self.m, '新版编辑器面板=管理 → 编辑')
        self.assertIn('新版编辑器面板', entries.load()['entries']['新版编辑器']['aliases'])
        self.assertEqual(len(entries.load()['entries']), 1)
        self.assertEqual(entries.resolve('商品详情')['key'], 'detail.open')
        self.assertEqual(entries.resolve('工作台')['key'], 'dashboard')

    def test_security_rejects_refs_and_sensitive_hints_without_writing(self):
        fake_jwt = '.'.join(['eyJ' + 'a' * 12, 'b' * 12, 'c' * 12])
        for text in ('页面=click:[ref=e123]', '页面=token=private-value', '页面=' + fake_jwt):
            with self.assertRaises(common.UiaError):
                entries.add(self.m, text)
        self.assertFalse(entries.knowledge_path('entries.yaml').exists())
        with self.assertRaises(common.UiaError):
            entries.parse('not a mapping')

    def test_go_hints_text_and_file_are_knowledge_and_counted_in_output(self):
        self.case('C1', '?内容编辑器')
        output = self.run_go('内容编辑器=管理 → 编辑')
        self.assertEqual(entries.resolve('内容编辑器')['source'], 'handoff')
        self.assertEqual(output['entry_question_count'], 0)
        path = self.root / 'hints.txt'
        path.write_text('订单列表=管理 → 订单', encoding='utf-8')
        self.run_go(str(path))
        self.assertIsNotNone(entries.resolve('订单列表'))
        self.assertIn('内容编辑器', self.m['entry_hint_changes'])
        self.assertEqual(entries.load()['schema_version'], 'entry-hints.v1')

    def test_unknown_pages_deduplicated_known_pages_not_asked(self):
        self.case('C1', '?内容编辑器', '打开内容编辑器；打开商品详情页')
        self.case('C2', '?内容编辑器')
        draft = experience.sync_checklist(self.base, self.m)
        self.assertTrue(draft['draft'])
        for row in preconditions.triage(self.base, self.m):
            preconditions.classify_precondition(self.base, self.m, row['key'], 'explore', '定位入口', [])
        result = experience.sync_checklist(self.base, self.m)
        self.assertEqual((result['question_count'], result['entry_question_count']), (1, 1))
        q = self.m['questions'][preconditions.QUESTION_KEY]
        d = [r for r in q['entries'] if r['block'] == 'D']
        self.assertEqual(d[0]['cases'], ['C1', 'C2'])
        self.assertIn('D 页面入口（大概在哪）', experience.checklist_text(q))
        self.assertIn('内容编辑器 大概在哪里进入？', experience.checklist_text(q))
        # Known handoff aliases also suppress questions.
        entries.store(self.m, [{'label': '主编辑器', 'path_text': '管理 → 编辑', 'aliases': ['内容编辑器']}])
        self.assertEqual(experience.sync_checklist(self.base, self.m)['question_count'], 0)

    def test_explicit_precondition_page_overrides_heuristic(self):
        self.case('C1', raw='使用新控制台并打开旧页面')
        row = preconditions.triage(self.base, self.m)[0]
        args = cli.parser().parse_args(['preconditions', 'classify', '--run', 'R', '--key', row['key'],
                                       '--as', 'ai_prepare', '--label', '准备数据', '--page', '新控制台'])
        result = cli.dispatch(args, self.base / 'run.json', self.m)
        self.assertEqual(result['entry_question_count'], 1)
        q = self.m['questions'][preconditions.QUESTION_KEY]
        self.assertEqual([r['page'] for r in q['entries'] if r['block'] == 'D'], ['新控制台'])
        self.assertEqual(self.m['precondition_tasks'][0]['page'], '新控制台')

    def test_raw_phrases_are_conservative(self):
        self.assertEqual(entries.phrases('打开商品详情页面；进入内容编辑器；准备三条记录'), ['商品详情页面', '内容编辑器'])
        self.assertEqual(entries.phrases('至少三条记录；已登录；网络可用'), [])

    def test_d_answers_persist_to_memory_and_across_requirements(self):
        self.case('C1', '?内容编辑器')
        self.case('C2', '?订单面板')
        experience.sync_checklist(self.base, self.m)
        result = experience.answer_sentence(self.base, self.m,
            'D 内容编辑器=内容管理 → 编辑，在 #compose-frame 里；订单面板=工作台 → 订单')
        self.assertEqual(result['answered'], 2)
        self.assertEqual(entries.resolve('内容编辑器')['source'], 'checklist')
        self.assertEqual(entries.resolve('内容编辑器')['frame'], '#compose-frame')
        self.assertEqual(experience.load_memory(self.m)['answers']['entry:订单面板'], '工作台 → 订单')
        other = copy.deepcopy(self.m)
        other['questions'] = {}; other.pop('checklist_issued'); other['run_id'] = 'OTHER'
        other['config']['site'] = 'https://other.example.test'
        with patch.object(experience, 'memory_path', return_value=self.root / 'different-memory.json'):
            self.assertEqual(experience.sync_checklist(self.base, other)['entry_question_count'], 0)
            self.assertEqual(experience.sync_checklist(self.base, other)['question_count'], 0)

    def test_numbered_d_and_existing_blocks(self):
        self.case('C1', '?甲编辑器')
        self.case('C2', '?乙编辑器')
        common.atomic_write(self.base / 'C1/case-spec.yaml', {'start_page': '?甲编辑器', 'required_env': ['editor_4_0'],
                            'questions': ['结果？选项：允许/阻止']}, as_yaml=True)
        experience.sync_checklist(self.base, self.m)
        experience.answer_sentence(self.base, self.m, 'A 都有，C 选允许，D1 管理 → 甲；D2 乙编辑器=管理 → 乙')
        self.assertEqual(entries.resolve('甲编辑器')['path_text'], '管理 → 甲')
        self.assertEqual(entries.resolve('乙编辑器')['path_text'], '管理 → 乙')

    def test_draft_d_answer_applied_by_go_at_finalization(self):
        self.case('C1', '?内容编辑器', '具备特殊条件')
        experience.sync_checklist(self.base, self.m)
        experience.answer_sentence(self.base, self.m, 'D 内容编辑器=管理 → 编辑')
        self.assertFalse(entries.knowledge_path('entries.yaml').exists())
        row = preconditions.triage(self.base, self.m)[0]
        preconditions.classify_precondition(self.base, self.m, row['key'], 'ignore', '无需准备', [])
        self.run_go()
        self.assertNotIn('pending_checklist_answer', self.m)
        self.assertEqual(entries.resolve('内容编辑器')['source'], 'checklist')
        self.assertEqual(experience.load_memory(self.m)['answers']['entry:内容编辑器'], '管理 → 编辑')
        self.assertIn('entry:内容编辑器', experience.load_memory(self.m)['answers'])
        self.assertEqual(self.m['entry_question_count'], 1)
        with patch.object(metrics, 'leak_scan', return_value=[]):
            measured = metrics.calculate(self.base, self.m)
        self.assertEqual(measured['entry_question_count'], 1)
        self.assertIn('入口问题 1', reports.opening(self.m, measured, {'items': []})[-1]['text'])

    def test_pending_d_answer_applies_even_if_final_checklist_is_already_known(self):
        self.case('C1', '?内容编辑器', '具备特殊条件')
        experience.sync_checklist(self.base, self.m)
        experience.answer_sentence(self.base, self.m, 'D 内容编辑器=管理 → 编辑')
        row = preconditions.triage(self.base, self.m)[0]
        preconditions.classify_precondition(self.base, self.m, row['key'], 'ignore', '无需准备', [])
        entries.add(self.m, '内容编辑器=管理 → 编辑')
        self.run_go()
        self.assertNotIn('pending_checklist_answer', self.m)
        self.assertEqual(entries.resolve('内容编辑器')['source'], 'checklist')

    def test_issued_d_answer_history_survives_knowledge_reuse(self):
        self.case('C1', '?内容编辑器')
        experience.sync_checklist(self.base, self.m)
        experience.answer_sentence(self.base, self.m, 'D 内容编辑器=管理 → 编辑')
        result = experience.sync_checklist(self.base, self.m)
        self.assertEqual(result['question_count'], 0)
        q = self.m['questions'][preconditions.QUESTION_KEY]
        self.assertEqual(q['answer']['entries']['entry:内容编辑器'], '管理 → 编辑')
        self.assertEqual(len(q['entries']), 1)
        self.assertFalse(self.m.get('review_items'))

    def test_changed_handoff_invalidates_stale_concrete_route(self):
        entries.add(self.m, '内容编辑器=管理 → 编辑')
        entries.confirm(self.m, '内容编辑器', ['goto:/old'], '#old-frame')
        entries.add(self.m, '内容编辑器=管理 → 编辑')
        self.assertTrue(entries.resolve('内容编辑器')['confirmed'])
        entries.add(self.m, '内容编辑器=新版管理 → 编辑')
        self.assertFalse(entries.resolve('内容编辑器')['confirmed'])
        self.assertNotIn('steps', entries.resolve('内容编辑器'))
        self.assertNotIn('frame', entries.resolve('内容编辑器'))

    def test_midrun_unknown_is_async_review_only(self):
        experience.sync_checklist(self.base, self.m)
        self.m['checklist_issued'] = True
        self.case('C2', '?新面板')
        result = experience.sync_checklist(self.base, self.m)
        self.assertEqual((result['question_count'], result['entry_question_count']), (0, 0))
        self.assertFalse(any(r['block'] == 'D' for r in self.m['questions'][preconditions.QUESTION_KEY]['entries']))
        self.assertEqual(self.m['cases']['C2']['work_status'], 'waiting_human')
        self.assertEqual(self.m['cases']['C1']['work_status'], 'pending')
        self.assertIn('新面板 大概在哪里进入', (self.base / 'review.md').read_text())
        self.assertFalse(any(r['kind'] == 'record_request' for r in self.m['review_items'].values()))

    def snapshot(self, failed=None, extra=None):
        args = cli.parser().parse_args(['snapshot', '--run', 'R', '--entry', '内容编辑器', '--purpose', 'insert.widget',
                                       *(extra or [])])
        with patch.object(cli, 'locked_run', self.locked), patch.object(cli, 'save'), \
                patch.object(profiles, 'invoke_snapshot', return_value={'structure': {'failed_step': failed}}) as run:
            result = cli.execute(args)
        return result, run

    def test_snapshot_free_text_confirm_and_entry_boundary(self):
        entries.add(self.m, '内容编辑器=管理 → 编辑（#compose-frame）')
        result, run = self.snapshot()
        run.assert_not_called()
        self.assertFalse(result['entry_reached'])
        self.assertIn('--goto/--step', result['instruction'])
        args = cli.parser().parse_args(['hints', 'confirm', '--run', 'R', '--page', '内容编辑器',
                                       '--step', 'goto:/manage', '--step', 'click:text=编辑'])
        cli.dispatch(args, self.base / 'run.json', self.m)
        hint = entries.resolve('内容编辑器')
        self.assertTrue(hint['confirmed']); self.assertEqual(hint['source'], 'explored')
        for failed, reached in [(None, True), ({'index': 1}, False), ({'index': 2}, False), ({'index': 3}, True)]:
            with self.subTest(failed=failed):
                result, run = self.snapshot(failed, ['--step', 'click:text=插入'])
                self.assertEqual(result['entry_reached'], reached)
                self.assertEqual(run.call_args.args[-2:], ('/manage', ['click:text=编辑', 'click:text=插入']))
                self.assertEqual(run.call_args.args[4], '#compose-frame')
                self.assertEqual(self.m['exploration'][-1]['entry_reached'], reached)
                self.assertEqual(self.m['exploration'][-1]['entry'], '内容编辑器')

    def test_snapshot_known_map_and_runner_error(self):
        args = cli.parser().parse_args(['snapshot', '--run', 'R', '--entry', '工作台', '--purpose', 'node'])
        with patch.object(cli, 'locked_run', self.locked), patch.object(cli, 'save'), \
                patch.object(profiles, 'invoke_snapshot', side_effect=common.UiaError('navigation failed')):
            with self.assertRaises(common.UiaError):
                cli.execute(args)
        self.assertFalse(self.m['exploration'][-1]['entry_reached'])
        self.assertEqual(args.open_target, 'dashboard')

    def generator(self, final, entry='内容编辑器'):
        output = json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message',
                             'text': '```json\n' + json.dumps(final) + '\n```'}})
        seen = {}
        def runner(command, timeout):
            seen['command'] = command
            return argparse.Namespace(stdout=output, returncode=0)
        with patch.object(profiles, 'agent_env', return_value={'cwd': '/runner', 'env': {}}), \
                patch.object(exploration, 'codex_binary', return_value='/bin/codex'):
            result = exploration.run_generator(self.base, self.m, 'insert.widget', '插入组件', runner=runner, entry=entry)
        return result, seen

    def test_generator_hint_prompt_and_reached_entry_json(self):
        entries.add(self.m, '内容编辑器=管理 → 编辑')
        entries.confirm(self.m, '内容编辑器', ['goto:/manage', 'click:text=编辑'], '#compose-frame')
        result, seen = self.generator({'reached': False, 'reached_entry': True, 'failed_interaction': 'drag'})
        prompt = seen['command'][-1]
        for text in ('管理 → 编辑', 'goto:/manage', 'click:text=编辑', '#compose-frame', 'reached_entry'):
            self.assertIn(text, prompt)
        self.assertEqual(seen['command'][:3], ['timeout', '2h', '/bin/codex'])
        self.assertTrue(result['recorded']['entry_reached'])
        self.assertEqual(result['recorded']['failed_interaction'], 'drag')
        self.assertTrue(common.read_json(self.base / result['report'])['reached_entry'])
        result, _ = self.generator({'reached': False, 'reached_entry': False, 'failed_interaction': 'drag'})
        self.assertFalse(result['recorded']['entry_reached'])
        self.assertIsNone(result['recorded']['failed_interaction'])
        result, _ = self.generator({'reached': False, 'reached_entry': True, 'failed_interaction': 'drag'}, entry=None)
        self.assertFalse(result['recorded']['entry_reached'])

    def test_generator_cli_entry_forwarded(self):
        args = cli.parser().parse_args(['generator', '--run', 'R', '--purpose', 'insert.widget', '--plan', 'insert', '--entry', '内容编辑器'])
        with patch.object(exploration, 'run_generator', return_value={}) as run:
            cli.dispatch(args, self.base / 'run.json', self.m)
        self.assertEqual(run.call_args.kwargs['entry'], '内容编辑器')

    def test_hints_add_cli_accepts_multiple_lines(self):
        args = cli.parser().parse_args(['hints', 'add', '--run', 'R', '内容编辑器=管理 → 编辑；订单列表=管理 → 订单'])
        result = cli.dispatch(args, self.base / 'run.json', self.m)
        self.assertEqual(result['saved_entries'], 2)
        self.assertIsNotNone(entries.resolve('订单列表'))

    def test_unknown_entry_demo_refused_into_d_or_async_review(self):
        for issued in (False, True):
            with self.subTest(issued=issued):
                self.m['checklist_issued'] = issued
                with self.assertRaisesRegex(common.UiaError, '页面入口未知：请走入口提示问题（清单 D 块），不要请求演示'):
                    workflow.question(self.m, 'demo', 'insert.widget', '演示交互', ['C1'],
                                      interaction='drag', page='内容编辑器', base=self.base)
                if issued:
                    self.assertIn('内容编辑器 大概在哪里进入', (self.base / 'review.md').read_text())
                else:
                    self.assertIn('D 页面入口', (self.base / 'checklist.md').read_text())
        self.assertFalse(any(q['kind'] == 'demo' for q in self.m['questions'].values()))

    def test_refused_demo_cli_saves_entry_request(self):
        self.m.update(preflight=None, contaminated_fixtures={})
        args = cli.parser().parse_args(['question', '--run', 'R', '--kind', 'demo', '--subject', 'insert.widget',
                                      '--page', '内容编辑器', '--prompt', '拖入失败', '--cases', 'C1', '--interaction', 'drag'])
        with patch.object(cli, 'locked_run', self.locked), patch.object(cli, 'save') as save:
            with self.assertRaisesRegex(common.UiaError, '页面入口未知'):
                cli.execute(args)
        save.assert_called_once()
        self.assertIn('entry:内容编辑器', self.m['questions'][preconditions.QUESTION_KEY]['checklist'])

    def test_demo_all_rungs_interaction_and_affected_case_required(self):
        self.m['cases']['C1']['unknown_nodes'] = ['insert.widget']
        entries.add(self.m, '内容编辑器=管理 → 编辑')
        def gate(interaction='drag'):
            exploration.demo_gate(self.m, 'insert.widget', ['C1'], interaction, page='内容编辑器')
        with self.assertRaisesRegex(common.UiaError, '到达页面入口'):
            gate()
        self.m['exploration'].append({'method': 'snapshot', 'purpose': 'insert.widget', 'entry': '内容编辑器', 'entry_reached': True})
        with self.assertRaisesRegex(common.UiaError, 'uia.py generator --entry'):
            gate()
        self.generator({'reached': False, 'reached_entry': True})
        with self.assertRaisesRegex(common.UiaError, '具体交互失败'):
            gate()
        self.generator({'reached': False, 'reached_entry': True, 'failed_interaction': 'drag'})
        with self.assertRaisesRegex(common.UiaError, '--interaction'):
            gate(None)
        with self.assertRaisesRegex(common.UiaError, '对应'):
            gate('clipboard')
        gate()
        self.case('C2')
        with self.assertRaisesRegex(common.UiaError, 'every case-spec'):
            exploration.demo_gate(self.m, 'insert.widget', ['C1', 'C2'], 'drag', page='内容编辑器')
        row = experience.add_review(self.m, 'record_request', ['C1'], '拖入组件失败',
                                    node='insert.widget', page='内容编辑器', interaction='drag')
        self.assertEqual(row['interaction'], 'drag')
        q = workflow.question(self.m, 'demo', 'insert.widget', '拖入组件失败', ['C1'], page='内容编辑器', interaction='drag')
        self.assertEqual(q['interaction'], 'drag')
        with self.assertRaisesRegex(common.UiaError, '--interaction'):
            experience.add_review(self.m, 'record_request', ['C1'], '缺少具体交互', node='insert.widget', page='内容编辑器')


if __name__ == '__main__':
    unittest.main()


class PhraseHeuristicTests(unittest.TestCase):
    def test_conservative_page_phrases(self):
        from uia_core import entries as E
        got = E.phrases('已登录新版内容编辑器并打开一个可编辑的产品或文章详情页。')
        self.assertEqual(got, ['新版内容编辑器', '产品或文章详情页'])
        self.assertEqual(E.phrases('偏好设置已启用新版内容编辑器'), ['新版内容编辑器'])
        self.assertEqual(E.phrases('视频和内容撰写系统等目标页面'), [])
        self.assertEqual(E.phrases('已登录内容管理后台'), ['内容管理后台'])
