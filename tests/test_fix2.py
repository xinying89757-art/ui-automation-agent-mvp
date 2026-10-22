import argparse
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uia_core import common, preconditions, experience, exploration, workflow, profiles, cli


class GenericProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.m = {'run_id': 'R', 'cases': {}, 'questions': {}, 'history': [], 'sources': [], 'exploration': [],
                  'config': {'auth': {}, 'targets': {}, 'network': {'mode': 'direct'}}, 'interaction_mode': 'once'}
        for cid, text in [('C1', '  未知页面 已打开  '), ('C2', '未知页面已打开'), ('C3', '另一个账号')]:
            common.atomic_write(self.base / cid / 'source.json', {'preconditions': text})
            common.atomic_write(self.base / cid / 'case-spec.yaml', {'required_env': [], 'mutation_scope': [], 'questions': []}, as_yaml=True)
            self.m['cases'][cid] = {'case_id': cid, 'source': cid + '/source.json', 'case_spec': cid + '/case-spec.yaml',
                                   'work_status': 'pending', 'stage': 'spec', 'result': None, 'attempts': []}
        self.memory = patch.object(experience, 'memory_path', return_value=self.base / 'memory.json')
        self.memory.start()

    def tearDown(self):
        self.memory.stop()
        self.temp.cleanup()

    def test_unclassified_groups_survive_spec_omissions_and_block_checklist(self):
        result = experience.sync_checklist(self.base, self.m)
        self.assertTrue(result['draft'])
        self.assertEqual(result['question_count'], 0)
        self.assertEqual(len(result['unclassified']), 2)
        self.assertEqual(result['unclassified'][0]['cases'], ['C1', 'C2'])
        self.assertIn('unclassified', json.dumps(self.m['precondition_triage']))
        self.assertEqual(workflow.next_task(self.base, self.m)['action'], 'classify_preconditions')
        self.assertIn('草稿', (self.base / 'checklist.md').read_text())
        deferred = experience.answer_sentence(self.base, self.m, 'A 都有')
        self.assertTrue(deferred['deferred_until_final'])
        self.assertEqual(self.m['pending_checklist_answer']['sentence'], 'A 都有')

    def test_pending_answer_applies_once_checklist_is_final(self):
        experience.sync_checklist(self.base, self.m)
        experience.answer_sentence(self.base, self.m, 'A 都有')
        rows = preconditions.triage(self.base, self.m)
        for row in rows:
            preconditions.classify_precondition(self.base, self.m, row['key'], 'human_env', '特殊条件', [])
        self.assertFalse(experience.sync_checklist(self.base, self.m)['draft'])
        applied = experience.answer_sentence(self.base, self.m, self.m['pending_checklist_answer']['sentence'])
        self.assertGreaterEqual(applied['answered'], 1)

    def test_ai_tasks_one_human_block_and_memory(self):
        rows = preconditions.triage(self.base, self.m)
        preconditions.classify_precondition(self.base, self.m, rows[0]['key'], 'explore', '定位未知入口', [])
        preconditions.classify_precondition(self.base, self.m, rows[1]['key'], 'human_env', '特殊权限', [])
        result = experience.sync_checklist(self.base, self.m)
        self.assertFalse(result['draft'])
        self.assertEqual(result['question_count'], 1)
        self.assertEqual(result['ai_tasks'][0]['cases'], ['C1', 'C2'])
        self.assertTrue((self.base / 'preconditions.yaml').is_file())
        experience.answer_sentence(self.base, self.m, 'A 都有')
        other = copy.deepcopy(self.m)
        other['questions'] = {}; other.pop('checklist_issued')
        self.assertEqual(experience.sync_checklist(self.base, other)['question_count'], 0)
        self.assertEqual(experience.sync_checklist(self.base, other)['memory_answer_count'], 1)
        preconditions.classify_precondition(self.base, self.m, rows[0]['key'], 'ai_prepare', '准备数据', [])
        self.assertEqual(self.m['precondition_tasks'][0]['action'], 'ai_prepare')
        preconditions.classify_precondition(self.base, self.m, rows[0]['key'], 'ignore', '运行已保证', [])
        self.assertEqual(self.m['precondition_tasks'], [])

    def test_demo_requires_navigation_generator_and_same_unknown_node(self):
        for kind in ['demo', 'record_request']:
            with self.assertRaisesRegex(common.UiaError, 'snapshot.*generator'):
                workflow.question(self.m, kind, 'node.x', '演示', ['C1'])
        self.m['exploration'].append({'method': 'snapshot', 'purpose': 'node.x', 'steps_count': 1})
        with self.assertRaisesRegex(common.UiaError, 'generator'):
            exploration.demo_gate(self.m, 'node.x', ['C1'])
        exploration.log(self.m, 'generator', 'other', 'failed', 'seed unavailable')
        with self.assertRaisesRegex(common.UiaError, 'generator'):
            exploration.demo_gate(self.m, 'node.x', ['C1'])
        exploration.log(self.m, 'generator', 'node.x', 'failed', 'tool unavailable')
        with self.assertRaisesRegex(common.UiaError, 'uia.py generator'):
            exploration.demo_gate(self.m, 'node.x', ['C1'])
        fake = argparse.Namespace(stdout=self.generator_output(False), returncode=0)
        with patch.object(exploration, 'codex_binary', return_value='/bin/codex'), \
                patch('uia_core.profiles.agent_env', return_value={'cwd': '/runner', 'env': {'UIA_CONFIG': '/p/c.json'}}):
            exploration.run_generator(self.base, self.m, 'node.x', '找入口', runner=lambda cmd, timeout: fake)
        common.atomic_write(self.base / 'C1/case-spec.yaml', {'steps': [{'target': '?node.x'}]}, as_yaml=True)
        exploration.index_unknown_nodes(self.base, self.m)
        exploration.demo_gate(self.m, 'node.x', ['C1'])
        with self.assertRaisesRegex(common.UiaError, 'every case-spec'):
            exploration.demo_gate(self.m, 'node.x', ['C1', 'C2'])
        with self.assertRaises(common.UiaError):
            experience.add_review(self.m, 'record_request', ['C1'], '演示', node='other')
        self.assertEqual(workflow.question(self.m, 'demo', 'node.x', '演示', ['C1'])['status'], 'deferred')

    @staticmethod
    def generator_output(reached):
        route = '{"reached": ' + ('true' if reached else 'false') + ', "route": ["click:text=产品"], "targets": {}}'
        message = 'done\n```json\n' + route + '\n```'
        return '\n'.join([json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': message}}),
                          json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 10, 'cached_input_tokens': 5, 'output_tokens': 2}})])

    def test_generator_cli_runs_isolated_subagent_and_records_tokens(self):
        seen = {}
        def runner(cmd, timeout):
            seen['cmd'], seen['timeout'] = cmd, timeout
            return argparse.Namespace(stdout=self.generator_output(True), returncode=0)
        with patch.object(exploration, 'codex_binary', return_value='/bin/codex'), \
                patch('uia_core.profiles.agent_env', return_value={'cwd': '/runner', 'env': {'UIA_CONFIG': '/p/c.json'}}):
            result = exploration.run_generator(self.base, self.m, 'node.y', '找入口', minutes=3, runner=runner)
        joined = ' '.join(seen['cmd'])
        self.assertIn('default_tools_approval_mode="approve"', joined)
        self.assertIn('mcp_servers.playwright-test.env.UIA_CONFIG="/p/c.json"', joined)
        self.assertIn('seed.spec.ts', seen['cmd'][-1])
        self.assertEqual(seen['timeout'], 180)
        row = result['recorded']
        self.assertEqual((row['source'], row['result'], row['tokens']['input_tokens']), ('generator-cli', 'ok', 10))
        self.assertEqual(result['route']['route'], ['click:text=产品'])
        self.assertTrue((self.base / 'exploration/generator-node.y.json').is_file())
        args = cli.parser().parse_args(['generator', '--run', 'R', '--purpose', 'n', '--plan', 'p'])
        self.assertEqual(args.minutes, 20)

    def test_legacy_explore_is_clean_and_parser_compatible(self):
        args = cli.parser().parse_args(['explore', '--run', 'R'])
        with self.assertRaisesRegex(common.UiaError, 'legacy explore is retired; use snapshot --goto/--step'):
            cli.dispatch(args, self.base / 'run.json', self.m)
        args = cli.parser().parse_args(['snapshot', '--run', 'R', '--open-target', 'any.new.page', '--goto', '/path', '--step', 'click:text=Open', '--purpose', 'node.x'])
        self.assertEqual(args.step, ['click:text=Open'])
        args = cli.parser().parse_args(['preconditions', 'classify', '--run', 'R', '--key', 'k', '--as', 'explore', '--label', '入口'])
        self.assertEqual(args.classification, 'explore')

    def test_routes_are_projections_without_input_values_queries_or_refs(self):
        args = argparse.Namespace(step=['fill:text=Field=private-input=second-private', 'click:text=Open'], click=[], hover=None,
                                  save_as='route', purpose='node.x', node='editor', goto='/path?q=hidden', open_target=None, frame=None, scope=None)
        exploration.save_route(self.base, self.m, args, {})
        route = (self.base / 'exploration-routes.yaml').read_text()
        self.assertNotIn('private-input', route)
        self.assertNotIn('second-private', route)
        self.assertNotIn('?q=', route)
        self.assertIn('${INPUT}', route)
        args.step = ['click:[ref=e123]']
        with self.assertRaises(common.UiaError):
            exploration.save_route(self.base, self.m, args, {})

    def test_agent_env_returns_paths_only_private_files_and_seed_exclusion(self):
        with patch.object(profiles, 'ROOT', self.base):
            env = profiles.agent_env(self.base, self.m)
        self.assertTrue(all(Path(value).is_absolute() for value in env['env'].values()))
        self.assertEqual(Path(env['env']['UIA_CONFIG']).stat().st_mode & 0o777, 0o600)
        self.assertEqual(Path(env['env']['UIA_CASES_FILE']).read_text().strip(), '{}')
        runner = self.base / 'runner/tests'
        runner.mkdir(parents=True)
        (runner / 'seed.spec.ts').write_text("test('[C1] seed', () => {});")
        self.assertEqual(workflow.bind_specs(self.base, self.m)['bound'], [])

    def test_snapshot_flags_forwarded_and_temp_config_removed(self):
        runner = self.base / 'runner'
        (runner / 'node_modules/@playwright/test').mkdir(parents=True)
        with patch.object(profiles, 'ROOT', self.base), patch.object(profiles.subprocess, 'run') as run:
            run.return_value = argparse.Namespace(returncode=0, stdout=json.dumps({'ok': True, 'structure': {'failed_step': {'index': 1}}}))
            result = profiles.invoke_snapshot(self.m['config'], runner, goto='/path', steps=['click:text=Open'])
            command = run.call_args.args[0]
            self.assertIn('--goto', command)
            self.assertIn('--step', command)
            self.assertFalse(Path(command[command.index('--config') + 1]).exists())
            self.assertEqual(result['structure']['failed_step']['index'], 1)
