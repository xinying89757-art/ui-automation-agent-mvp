import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from openpyxl import Workbook
from uia_core import cli, common, entries, experience, failures, metrics, profiles, reports, specs, workflow

SOURCE = Path(__file__).resolve().parents[1]


class FailureClassTests(unittest.TestCase):
    def test_site_not_found_is_environment_not_automation(self):
        result, kind = failures.judge_result("automation_failure", ["Error: SITE_NOT_ACCESSIBLE 未找到目标网站"])
        self.assertEqual((result, kind), ("environment_blocked", "environment"))
        self.assertEqual(failures.failure_class_for_case({
            "result": "automation_failure",
            "attempts": [{"errors": ["page.goto: Timeout 30000ms exceeded while opening the login site"]}],
        }), "environment")
        self.assertEqual(failures.judge_result("business_failure", ["UIA_BUSINESS_FAILURE: missing copy"])[1], "product")
        self.assertEqual(failures.judge_result("suspended", [])[1], "suspended")
        self.assertEqual(failures.judge_result("automation_failure", ["locator resolved to 0 elements"])[1], "automation")

    def test_shares_cover_the_four_classes(self):
        cases = [
            {"result": "environment_blocked", "failure_class": "environment"},
            {"result": "automation_failure", "failure_class": "automation"},
            {"result": "business_failure"},
            {"result": "suspended"},
            {"result": "passed", "attempts": [{"executed": True, "result": "passed"}]},
        ]
        shares = failures.class_shares(cases)
        self.assertEqual(shares["counts"], {"environment": 1, "automation": 1, "product": 1, "suspended": 1})
        self.assertAlmostEqual(sum(shares["shares"].values()), 1.0)


class MetricsReportTests(unittest.TestCase):
    def test_report_metrics_include_the_required_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "cases").mkdir()
            (base / "cases/C1.spec.ts").write_text("// uses page.editor\n", encoding="utf-8")
            spec = "cases/C1/case-spec.yaml"
            (base / "cases/C1").mkdir()
            (base / spec).write_text("start_page: editor\n", encoding="utf-8")
            common.atomic_write(base / "knowledge-match.json", {
                "matched": {"C1": {"page.editor": {"id": "page.editor", "page": "editor"},
                                   "page.other": {"id": "page.other", "page": "unused-page"}}},
                "budgets": {"C1": {"used_tokens": 10}, "C2": {"used_tokens": 90}},
            })
            manifest = {
                "created_at": "2026-01-01T00:00:00+00:00",
                "first_result_at": "2026-01-01T00:10:00+00:00",
                "sources": [{"imported_at": "2026-01-01T00:00:00+00:00"}],
                "rescued_by_midscene": 2,
                "interaction_events": [{"kind": "checklist_answer"}, {"kind": "session_turn", "category": "计划外"}],
                "exploration": [],
                "cases": {
                    "C1": {"case_id": "C1", "case_spec": spec, "registration": {"script": "cases/C1.spec.ts"},
                           "attempts": [{"executed": True, "result": "passed"}], "result": "passed", "work_status": "finished"},
                    "C2": {"case_id": "C2", "result": "environment_blocked", "failure_class": "environment",
                           "attempts": [{"executed": True, "errors": ["SITE_NOT_ACCESSIBLE"]}], "work_status": "finished"},
                },
                "config": {"auth": {}},
            }
            measured = metrics.calculate(base, manifest)
            for key in ("time_to_first_result_seconds", "pass_rate", "failure_class_shares",
                        "human_interventions_per_case", "kb_hit_rate", "re_explored_known_pages",
                        "knowledge_injected_tokens", "rescued_by_midscene"):
                self.assertIn(key, measured)
            self.assertEqual(measured["rescued_by_midscene"], 2)
            self.assertEqual(measured["time_to_first_result_seconds"], 600)
            self.assertEqual(measured["pass_rate"], 0.5)
            self.assertEqual(measured["failure_class_shares"]["environment"], 1.0)
            self.assertEqual(measured["human_interventions"], 2)
            self.assertEqual(measured["human_interventions_per_case"], 1.0)
            self.assertEqual(measured["kb_hit_rate"], {"retrieved": 2, "used": 1, "rate": 0.5})
            self.assertEqual(measured["knowledge_injected_tokens"]["p50"], 90)
            self.assertEqual(measured["knowledge_injected_tokens"]["p95"], 90)
            text = reports.opening(manifest, measured, {"items": []})[2]["text"]
            self.assertIn("失败分类占比", text)
            self.assertIn("知识命中率", text)
            self.assertIn("Midscene 挽救 2", text)


class SmokeGateTests(unittest.TestCase):
    def test_representative_cases_spread_across_modules(self):
        cases = [
            {"case_id": "A", "priority": "P1", "module": "faq"},
            {"case_id": "B", "priority": "P0", "module": "faq"},
            {"case_id": "C", "priority": "P2", "module": "article"},
            {"case_id": "D", "priority": "P0", "module": "product"},
            {"case_id": "E", "priority": "P1", "module": "article"},
        ]
        picked = experience.representative_cases(cases, 3)
        self.assertEqual(picked, ["B", "D", "E"])

    def test_full_batch_splits_smoke_and_subset_does_not(self):
        cases = [{"case_id": str(i), "module": str(i)} for i in range(5)]
        ready = [case["case_id"] for case in cases]
        first, rest = experience.split_smoke(ready, cases, 3, True, None)
        self.assertEqual(len(first), 3)
        self.assertEqual(len(rest), 2)
        self.assertEqual(experience.split_smoke(ready, cases, 3, False, None), (ready, []))
        self.assertEqual(experience.split_smoke(ready[:2], cases[:2], 3, True, None)[1], [])
        self.assertEqual(experience.split_smoke(ready, cases, 3, True, {"status": "rejected"}), ([], []))

    def test_first_result_budget_is_26_minutes(self):
        start = "2026-01-01T00:00:00+00:00"
        slow = {"first_result_at": "2026-01-01T00:27:00+00:00", "sources": [{"imported_at": start}]}
        fast = {"first_result_at": "2026-01-01T00:25:00+00:00", "sources": [{"imported_at": start}]}
        self.assertTrue(experience.first_result_exceeded(slow, 26, start))
        self.assertFalse(experience.first_result_exceeded(fast, 26, start))
        self.assertFalse(experience.first_result_exceeded({}, 26, start))


class PreflightGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(module, "ROOT", self.root) for module in (common, experience, profiles, workflow)]
        for item in self.patches:
            item.start()
        shutil.copytree(SOURCE / "assets", self.root / "assets", ignore=shutil.ignore_patterns("node_modules", "results"))
        shutil.copytree(SOURCE / "examples/phase2", self.root / "examples/phase2")

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.temp.cleanup()

    def test_go_blocks_the_batch_before_cases_when_the_site_is_missing(self):
        auth = self.root / "private.json"
        common.atomic_write(auth, {"account": "fake-private-user", "password": "fake-private-password"})
        profiles.setup("offline", "production", "en.example.test", credentials_file=auth)
        workbook = self.root / "sample.xlsx"
        book = Workbook()
        sheet = book.active
        sheet.append(["用例ID", "用例标题", "前置条件", "操作步骤", "预期结果"])
        sheet.append(["TC-0004", "窗口", "", "打开", "显示"])
        sheet.append(["NEW-2", "新页面", "", "打开", "显示"])
        book.save(workbook)

        def explode(*_args, **_kwargs):
            raise common.UiaError("未找到目标网站", {"code": "SITE_NOT_ACCESSIBLE"})

        with patch.object(profiles, "invoke_login", side_effect=explode), \
                patch.object(experience, "_run_ready") as run, \
                patch.object(reports, "make_report", return_value={"summary": {}}):
            result = experience.go(workbook, "offline")
        self.assertEqual(run.call_count, 0)
        self.assertTrue(result["environment_blocked"])
        self.assertIn("SITE_NOT_ACCESSIBLE", result["reason"])
        saved = common.read_json(self.root / "runs" / result["run_id"] / "run.json")
        self.assertTrue(all(case["result"] == "environment_blocked" and case["failure_class"] == "environment"
                            for case in saved["cases"].values()))
        self.assertNotIn("fake-private-password", json.dumps(result))

    def test_live_summary_hides_session_material(self):
        from uia_core.environment_gate import public_preflight_result
        summary = public_preflight_result({
            "status": "authenticated",
            "environment": {"environment": "production", "verified": True},
            "targets": {"admin": {"reachable": True, "authenticated": True, "selected_site": "en.example.test"}},
            "editor": {"opened": True, "area": "编辑网站"},
            "storage_state": "/tmp/secret-session.json",
            "timings": {"authenticated_ms": 10, "editor_ms": 20, "total_ms": 30},
        }, 1.25)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["checks"]["editor_opened"], True)
        self.assertNotIn("storage_state", json.dumps(summary))

    def test_preflight_command_parses_without_evidence(self):
        args = cli.parser().parse_args(["preflight", "--profile", "prod-test"])
        self.assertEqual(args.profile, "prod-test")
        self.assertIsNone(args.evidence)
        self.assertEqual(cli.parser().parse_args(["go", "a.xlsx"]).smoke_size, 3)
        self.assertEqual(cli.parser().parse_args(["go", "a.xlsx"]).first_result_budget_minutes, 26)


class PressEnterTests(unittest.TestCase):
    def test_path_and_promote_keep_press_enter(self):
        route = entries.navigation_hint({"path_text": "编辑网站 → 按回车"})
        self.assertEqual(route["steps"], ["press:Enter"])
        self.assertEqual(entries.navigation_hint({"path_text": "编辑网站 → press Enter"})["steps"], ["press:Enter"])
        self.assertEqual(entries.navigation_hint({"path_text": "编辑网站 → 设置"})["steps"], ["click:text=设置"])

    def test_generated_press_enter_is_not_a_click(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            folder = base / "cases/T1"
            folder.mkdir(parents=True)
            (base / "runner/tests/generated").mkdir(parents=True)
            source = {"case_id": "T1", "expected": ["1. 弹窗显示管理txt文件。"], "steps": ["press Enter"]}
            spec = {
                "schema_version": "case-spec.v1", "case_id": "T1", "intent": "检查窗口",
                "automatable": {"status": "yes", "reason": "known"}, "required_env": [],
                "data_prep": {}, "mutation_scope": [], "start_page": "editor",
                "steps": [{"id": "S1", "verb": "click", "target": "txt.dialog"}],
                "assertions": [{"id": "A1", "after": "S1", "excel": "1. 弹窗显示管理txt文件。",
                                "checks": [{"target": "txt.dialog", "op": "visible"}]}],
                "questions": [],
            }
            common.atomic_write(folder / "source.json", source)
            common.atomic_write(folder / "case-spec.yaml", spec, as_yaml=True)
            manifest = {"cases": {"T1": {"case_id": "T1", "source": "cases/T1/source.json",
                        "case_spec": "cases/T1/case-spec.yaml", "source_hash": "hash", "attempts": []}},
                        "config": {"mutation": {"allowed": False, "scope": []}}, "questions": {}, "history": []}
            with patch.object(specs, "register_script", return_value={"script": "runner/tests/generated/T1.spec.ts"}):
                generated = specs.generate(base, manifest, "T1")
            body = (base / generated["script"]).read_text(encoding="utf-8")
            self.assertIn('page.keyboard.press("Enter")', body)
            self.assertNotIn(".click()", body)


class PromoteUnderscoreTests(unittest.TestCase):
    def test_promote_accepts_underscore_catalog_names(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            know = root / "assets/playwright-runner/knowledge"
            know.mkdir(parents=True)
            (know / "entries.yaml").write_text("schema_version: entry-hints.v1\nentries: {}\n", encoding="utf-8")
            (know / "page-map.yaml").write_text("schema_version: page-map.v1\npages: {}\ntargets: {}\n", encoding="utf-8")
            base = root / "run"
            (base / "exploration").mkdir(parents=True)
            (base / "cases/C1").mkdir(parents=True)
            common.atomic_write(base / "cases/C1/case-spec.yaml", {
                "start_page": "content-admin",
                "steps": [{"id": "S1", "verb": "click", "target": "?faq_editor.save"}],
            }, as_yaml=True)
            report = {
                "purpose": "faq_editor", "entry": "新版内容编辑器", "reached": True, "reached_entry": True,
                "route": {"reached": True, "reached_entry": True, "route": ["press Enter", "click:text=press Enter"],
                          "targets": {}, "step_targets": [{
                              "case_id": "C1", "step_id": "S1", "placeholder": "?faq_editor.save",
                              "target": "faq_editor.save_button", "locator": {"text": "保存"},
                              "verified": True, "match_count": 1}]},
                "case_targets": [{"case_id": "C1", "targets": ["?faq_editor.save"]}],
            }
            (base / "exploration/generator-faq.json").write_text(json.dumps(report), encoding="utf-8")
            manifest = {"config": {}, "cases": {"C1": {"case_id": "C1", "case_spec": "cases/C1/case-spec.yaml"}}}
            with patch.object(common, "ROOT", root):
                entries.add(manifest, "新版内容编辑器=内容管理 → 产品")
                result = entries.promote(base, manifest, "exploration/generator-faq.json")
            self.assertEqual(result["route_steps"][:2], ["press:Enter", "press:Enter"])
            self.assertEqual(result["placeholder_bindings"]["?faq_editor.save"], "faq_editor.save_button")


if __name__ == "__main__":
    unittest.main()
