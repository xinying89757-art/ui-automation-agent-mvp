import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from uia_core import common, workflow, profiles, cli, metrics

SOURCE = Path(__file__).resolve().parents[1]


class PhaseOneTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="uia-phase1-")
        self.root = Path(self.temp.name)
        shutil.copytree(SOURCE / "assets", self.root / "assets", ignore=shutil.ignore_patterns("node_modules", "results"))
        self.patches = [patch.object(module, "ROOT", self.root) for module in (common, workflow, profiles)]
        for item in self.patches:
            item.start()
        credentials = self.root / "private-source.json"
        common.atomic_write(credentials, {"account": "offline-private-account", "password": "offline-private-password"})
        self.profile = profiles.setup("offline", "production", "en.example.test", credentials_file=credentials)["config"]

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.temp.cleanup()

    def test_run_uses_shared_runner_and_private_case_bindings(self):
        initialized = workflow.init("SHARED", self.profile)
        base = Path(initialized["run"]).parent
        result = workflow.scaffold(base)
        self.assertTrue((base / "runner").is_symlink())
        self.assertEqual((base / "runner").resolve(), self.root / "assets/playwright-runner")
        self.assertTrue((base / "state/cases.json").is_file())
        self.assertEqual(result["next"], "bind_existing_specs_then_generate_final_scripts")
        self.assertEqual(common.read_json(initialized["run"])["config"]["execution"]["stability_passes"], 1)

    def test_mid_run_scope_change_is_rejected_and_recorded(self):
        initialized = workflow.init("LOCKED", self.profile)
        args = cli.parser().parse_args(["profile", "set", "--profile", "offline", "--run", initialized["run"],
                                        "--mutation-allowed", "--scope", "everything"])
        with self.assertRaises(common.UiaError):
            cli.execute(args)
        manifest = common.read_json(initialized["run"])
        self.assertEqual(manifest["scope_violations"], 1)
        self.assertFalse(common.config(self.profile)["mutation"]["allowed"])

    def test_explicit_editor_restore_approval_is_recorded(self):
        result = profiles.update_profile("offline", mutation_allowed=True, scope=["content-admin"],
                                         editor_data_restorable=True)
        self.assertEqual(result["authorization_profile"], {"mode": "editor_any_data_restore", "approved_by": "Xinying"})
        serialized = json.dumps(result)
        self.assertNotIn("offline-private-account", serialized)
        self.assertNotIn("offline-private-password", serialized)

    def test_leak_scan_reports_only_redacted_hit_metadata(self):
        base = self.root / "leak-run"
        base.mkdir()
        (base / "evidence.txt").write_text("Authorization=abc123secretvalue", encoding="utf-8")
        (base / "safe.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
        found = metrics.leak_scan(base, {"auth": {}})
        self.assertEqual(found, [{"file": "evidence.txt", "category": "credential_parameter"}])
        self.assertNotIn("abc123secretvalue", json.dumps(found))

    def test_locator_wait_repair_preserves_only_unchanged_assertions(self):
        before = self.root / "before.spec.ts"
        after = self.root / "after.spec.ts"
        before.write_text("await expect(page.locator('#old')).toHaveText('saved');\n", encoding="utf-8")
        after.write_text("await expect(page.locator('#new')).toHaveText('saved');\n", encoding="utf-8")
        self.assertTrue(metrics.locator_wait_only(before, after))
        after.write_text("await expect(page.locator('#new')).toHaveText('changed');\n", encoding="utf-8")
        self.assertFalse(metrics.locator_wait_only(before, after))


if __name__ == "__main__":
    unittest.main()
