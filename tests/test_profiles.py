import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uia_core import common, workflow, profiles, reports, runtime, cli

SOURCE = Path(__file__).resolve().parents[1]

class ProfilesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='uia-offline-')
        self.root = Path(self.temp.name)
        shutil.copytree(SOURCE / 'assets', self.root / 'assets', ignore=shutil.ignore_patterns('node_modules', 'results'))
        self.patches = [patch.object(module, 'ROOT', self.root) for module in (common, workflow, profiles)]
        for p in self.patches: p.start()
        self.creds = self.root / 'provided.json'
        common.atomic_write(self.creds, {'account': 'offline-user', 'password': 'offline-password'})

    def tearDown(self):
        for p in self.patches: p.stop()
        self.temp.cleanup()

    def setup_profile(self, name='operator', environment='p'):
        return profiles.setup(name, environment, 'en.example.test', credentials_file=self.creds)

    def test_private_setup_and_session_isolation(self):
        output = self.setup_profile()
        self.assertNotIn('offline-password', json.dumps(output))
        self.assertNotIn('offline-user', json.dumps(output))
        cfg = common.config(output['config'])
        self.assertEqual(cfg['targets']['admin'], profiles.presets()['p']['cloud_url'])
        self.assertEqual(cfg['targets']['public'], 'http://en.example.test')
        self.assertEqual(Path(cfg['auth']['credentials_file']).stat().st_mode & 0o777, 0o600)
        gray = common.config(self.setup_profile('gray', 'gray')['config'])
        self.assertNotEqual(cfg['auth']['storage_state'], gray['auth']['storage_state'])
        self.assertEqual(common.redact('offline-user offline-password', cfg), '[REDACTED] [REDACTED]')
        self.assertNotIn('offline-password', json.dumps(cfg))

    def test_identity_not_password_changes_result_version(self):
        cfg_path = self.setup_profile()['config']
        original = common.config(cfg_path)
        credential = original['auth']['credentials_file']
        common.atomic_write(credential, {'account': 'offline-user', 'password': 'changed-password'})
        self.assertEqual(common.execution_config_fingerprint(original), common.execution_config_fingerprint(common.config(cfg_path)))
        common.atomic_write(credential, {'account': 'different-user', 'password': 'changed-password'})
        self.assertNotEqual(common.execution_config_fingerprint(original), common.execution_config_fingerprint(common.config(cfg_path)))

    def test_explicit_environment_ignores_process_proxy(self):
        cfg_path = self.setup_profile('formal', 'production')['config']
        with patch.dict(os.environ, {'UI_PROXY': 'http://unexpected:9999'}):
            cfg = common.config(cfg_path)
            self.assertEqual(cfg['network']['mode'], 'direct')
            self.assertEqual(profiles.effective_network(cfg)['mode'], 'direct')
        legacy = self.root / 'legacy.yaml'
        common.atomic_write(legacy, {'schema_version': 'uia-config.v1', 'auth': {}, 'targets': {}, 'data_rules': {}, 'mutation': {}, 'execution': {}})
        with patch.dict(os.environ, {'UI_PROXY': 'none'}):
            self.assertEqual(profiles.effective_network(common.config(legacy))['mode'], 'direct')

    def test_pac_and_identity_changes_invalidate_stability_but_state_refresh_does_not(self):
        cfg_path = self.setup_profile('gray', 'gray')['config']
        initialized = workflow.init('OFFLINE', cfg_path)
        base = Path(initialized['run']).parent
        workflow.scaffold(base)
        m = common.read_json(initialized['run'])
        workflow.refresh(base, m)
        m['cases']['C1'] = {'case_id': 'C1', 'fixture_ids': [], 'registration': None,
            'result': 'passed', 'pass_streak': 2, 'stability': 'stable', 'work_status': 'finished', 'stage': 'finished'}
        common.atomic_write(m['config']['auth']['storage_state'], {'cookies': [], 'origins': []})
        workflow.refresh(base, m)
        self.assertEqual(m['cases']['C1']['pass_streak'], 2)
        pac = base / 'runner/network/gray.pac'
        pac.write_text(pac.read_text() + '\n// offline changed rules\n')
        workflow.refresh(base, m)
        self.assertEqual(m['cases']['C1']['pass_streak'], 0)
        self.assertIsNone(m['cases']['C1']['result'])
        self.assertIsNone(m['preflight'])
        m['cases']['C1'].update(result='passed', pass_streak=2, stability='stable', work_status='finished')
        common.atomic_write(m['config']['auth']['credentials_file'], {'account': 'different-user', 'password': 'offline-password'})
        workflow.refresh(base, m)
        self.assertEqual(m['cases']['C1']['pass_streak'], 0)

    def test_environment_evidence_required_and_network_matches_js(self):
        cfg = common.config(self.setup_profile('gray', 'gray')['config'])
        expected = profiles.network_fingerprint(cfg)
        node = subprocess.run(['node', '--input-type=module', '-e',
            "import {resolveConfig,networkFingerprint} from './support/environment.mjs'; console.log(networkFingerprint(resolveConfig(JSON.parse(process.argv[1]))));", json.dumps(cfg)],
            cwd=profiles.runtime_root(), capture_output=True, text=True, check=True)
        self.assertEqual(expected, node.stdout.strip())
        base = self.root / 'evidence-run'; base.mkdir()
        evidence = base / 'proof.json'
        proof = {'targets': {'admin': {'url': cfg['targets']['admin'], 'reachable': True, 'target_visible': True, 'authenticated': True},
            'public': {'url': cfg['targets']['public'], 'reachable': True, 'target_visible': True}}}
        common.atomic_write(evidence, proof)
        m = {'config': cfg, 'config_hash': 'hash', 'cases': {}, 'questions': {}, 'history': [], 'active_batch': None}
        self.assertEqual(runtime.preflight(base, m, 'proof.json')['status'], 'blocked')
        proof['environment'] = {'environment': 'gray', 'entry_url': cfg['environment']['entry_url'],
            'network_fingerprint': expected, 'verified': True, 'x_via': 'Ld-Gray'}
        common.atomic_write(cfg['auth']['storage_state'], {'cookies': [], 'origins': []})
        common.atomic_write(evidence, proof)
        self.assertEqual(runtime.preflight(base, m, 'proof.json')['status'], 'passed')
        proof['targets']['public'].update(reachable=False, target_visible=False, error='net::ERR_CONNECTION_REFUSED offline-password')
        common.atomic_write(evidence, proof)
        optional = runtime.preflight(base, m, 'proof.json')
        self.assertEqual(optional['status'], 'passed')
        self.assertFalse(optional['capabilities']['public_frontend'])
        self.assertNotIn('offline-password', json.dumps(optional))

    def test_explicit_http_wins_and_profile_set_updates_scope(self):
        explicit = profiles.setup('http-site', 'production', 'http://en.example.test', credentials_file=self.creds)
        self.assertEqual(explicit['site'], 'http://en.example.test')
        self.assertNotIn('offline-password', json.dumps(explicit))
        bare = profiles.setup('bare-prod', 'production', 'en.example.test', credentials_file=self.creds)
        self.assertEqual(bare['site'], 'https://en.example.test')
        updated = profiles.update_profile('http-site', mutation_allowed=True, scope=['llms.txt'], stability_passes=1)
        self.assertEqual(updated['mutation'], {'allowed': True, 'scope': ['llms.txt']})
        self.assertEqual(updated['stability_passes'], 1)
        self.assertNotIn('offline-password', json.dumps(updated))
        cfg = common.config(updated['config'])
        self.assertEqual(cfg['targets']['public'], 'http://en.example.test')
        self.assertEqual(cfg['execution']['stability_passes'], 1)

    def test_human_preconditions_wait_instead_of_not_suitable(self):
        from uia_core.preconditions import sync_preconditions
        base = self.root / 'pre'
        folder = base / 'cases/TC-0002'
        folder.mkdir(parents=True)
        common.atomic_write(folder / 'source.json', {
            'title': '无网站设置权限的账号不显示入口',
            'preconditions': '账号不具备当前站点的网站设置操作权限，已进入3.0编辑器。'})
        passed = base / 'cases/TC-0001'
        passed.mkdir()
        common.atomic_write(passed / 'source.json', {'title': '设置面板', 'preconditions': '已登录'})
        m = {'history': [], 'questions': {}, 'cases': {
            'TC-0002': {'case_id': 'TC-0002', 'source': 'cases/TC-0002/source.json', 'title': '无权限',
                        'result': 'not_suitable', 'work_status': 'finished', 'stage': 'finished',
                        'attempts': [], 'stability': 'not_run'},
            'TC-0001': {'case_id': 'TC-0001', 'source': 'cases/TC-0001/source.json', 'title': '设置面板',
                        'result': 'passed', 'work_status': 'finished', 'stage': 'finished',
                        'attempts': [{'result': 'passed'}], 'stability': 'stable'}}}
        queued = sync_preconditions(base, m)
        self.assertEqual(m['cases']['TC-0002']['result'], None)
        self.assertEqual(m['cases']['TC-0002']['work_status'], 'waiting_human')
        self.assertNotEqual(m['cases']['TC-0002'].get('result'), 'not_suitable')
        self.assertEqual(m['cases']['TC-0001']['result'], 'passed')
        self.assertIn('TC-0002', queued['cases'])
        workflow.answer(m, queued['question_id'], {'available': [], 'unavailable': ['no_settings_permission']}, base)
        self.assertEqual(m['cases']['TC-0002']['work_status'], 'waiting_human')
        self.assertIsNone(m['cases']['TC-0002']['result'])

    def test_login_blocker_is_scoped_and_successful_answer_restores_work(self):
        cfg_path = self.setup_profile()['config']
        initialized = workflow.init('AUTH-RESTORE', cfg_path)
        manifest = Path(initialized['run']); base = manifest.parent
        m = common.read_json(manifest)
        for cid, stage in [('READY', 'discovery'), ('INDEPENDENT', 'intent')]:
            m['cases'][cid] = {'case_id': cid, 'stage': stage, 'work_status': 'pending',
                'fixture_ids': [], 'registration': None, 'result': None, 'stability': 'not_run', 'pass_streak': 0}
        common.save(manifest, m)
        args = cli.parser().parse_args(['login', '--run', str(manifest)])
        blocker = common.UiaError('验证码需要人工处理', {'code': 'CAPTCHA_REQUIRED', 'choices': ['使用 --manual', '暂停']})
        with patch.object(profiles, 'invoke_login', side_effect=blocker):
            with self.assertRaises(common.UiaError): cli.execute(args)
        m = common.read_json(manifest)
        self.assertEqual(m['cases']['READY']['work_status'], 'waiting_human')
        self.assertEqual(m['cases']['INDEPENDENT']['work_status'], 'pending')
        self.assertEqual(next(iter(m['questions'].values()))['choices'], ['使用 --manual', '暂停'])
        def successful(cfg, runner, check_only, force, evidence, manual):
            proof = {'environment': {'environment': cfg['environment']['id'], 'entry_url': cfg['environment']['entry_url'],
                'network_fingerprint': profiles.network_fingerprint(cfg), 'verified': True},
                'targets': {key: {'url': url, 'reachable': True, 'target_visible': True, 'authenticated': True}
                    for key, url in cfg['targets'].items()}}
            common.atomic_write(cfg['auth']['storage_state'], {'cookies': [], 'origins': []})
            common.atomic_write(evidence, proof)
            return {'status': 'authenticated'}
        with patch.object(profiles, 'invoke_login', side_effect=successful):
            self.assertEqual(cli.execute(args)['preflight']['status'], 'passed')
        m = common.read_json(manifest)
        self.assertTrue(all(q['status'] == 'answered' for q in m['questions'].values()))
        self.assertEqual(m['cases']['READY']['work_status'], 'pending')
        self.assertEqual(m['cases']['INDEPENDENT']['work_status'], 'pending')

    def test_cli_setup_init_status_after_moving_project(self):
        shutil.copytree(SOURCE / 'scripts', self.root / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
        def cli(*args):
            result = subprocess.run([sys.executable, str(self.root / 'scripts/uia.py'), *args],
                cwd=self.root.parent, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertNotIn('offline-password', result.stdout)
            return json.loads(result.stdout)
        self.assertEqual(set(cli('env', 'list')['environments']), {'p', 'gray', 'production'})
        cli('setup', '--profile', 'moved', '--environment', 'production', '--site', 'en.example.test',
            '--credentials-file', str(self.creds))
        initialized = cli('init', '--run-id', 'MOVED', '--profile', 'moved')
        status = cli('status', '--run', initialized['run'])
        self.assertEqual(status['connection']['environment'], 'production')
        self.assertEqual(status['connection']['entry_url'], 'https://www.leadong.com/website.html')
        self.assertEqual(status['connection']['network_mode'], 'direct')
        self.assertEqual((self.root / '.auth').stat().st_mode & 0o777, 0o700)

    def test_package_is_portable_and_excludes_credentials_state_and_local_files(self):
        cfg_path = self.setup_profile()['config']
        initialized = workflow.init('EXPORT', cfg_path)
        m = common.read_json(initialized['run']); base = Path(initialized['run']).parent
        workflow.scaffold(base)
        # Deliberately put secrets under neutral filenames in runner: configured paths must exclude them.
        credential = base / 'runner/fixtures/operator.json'
        state = base / 'runner/fixtures/browser.json'
        common.atomic_write(credential, {'account': 'offline-user', 'password': 'offline-password'})
        common.atomic_write(state, {'cookies': ['offline-cookie']})
        common.atomic_write(str(state) + '.meta.json', {'binding': 'private-binding'})
        m['config']['auth'].update(credentials_file=str(credential), storage_state=str(state))
        (base / 'runner/ignored.local.json').write_text('offline-password')
        reports.make_report(base, m)
        extracted = self.root / 'relocated'
        with zipfile.ZipFile(base / 'reports/scripts.zip') as archive:
            names = archive.namelist()
            self.assertIn('runner/network/gray.pac', names)
            self.assertIn('runner/scripts/check-environment.mjs', names)
            self.assertIn('runner/environments.json', names)
            self.assertNotIn('runner/fixtures/operator.json', names)
            self.assertNotIn('runner/fixtures/browser.json', names)
            self.assertNotIn('runner/fixtures/browser.json.meta.json', names)
            for name in names:
                self.assertNotIn(b'offline-password', archive.read(name))
                self.assertNotIn(b'offline-cookie', archive.read(name))
                self.assertNotIn(str(SOURCE).encode(), archive.read(name))
            archive.extractall(extracted)
        env_module = (extracted / 'runner/support/environment.mjs').as_uri()
        node = subprocess.run(['node', '--input-type=module', '-e',
            f"import {{resolveConfig,launchOptions}} from {json.dumps(env_module)}; console.log(JSON.stringify(launchOptions(resolveConfig({{environment:'gray'}}))));"],
            cwd=self.root, capture_output=True, text=True, check=True)
        pac_url = json.loads(node.stdout)['args'][0]
        self.assertIn('relocated/runner/network/gray.pac', pac_url)

if __name__ == '__main__': unittest.main()
