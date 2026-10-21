import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from uia_core.workbooks import extract
from uia_core.workflow import heal_review

ROOT = Path(__file__).resolve().parents[1]


class WorkbookAliasTest(unittest.TestCase):
    def test_case_description_and_level_map_to_title_and_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.title = "测试用例"
            sheet.append(["用例编号", "模块", "用例描述", "用例级别", "前置条件", "测试步骤", "预期结果"])
            sheet.append(["TC-0001", "入口", "打开管理txt文件", "P0", "已登录", "点击设置", "看到入口"])
            book.save(path)
            parsed = extract(path)
        self.assertEqual(parsed["gaps"], [])
        case = parsed["cases"][0]
        self.assertEqual(case["title"], "打开管理txt文件")
        self.assertEqual(case["priority"], "P0")
        self.assertEqual(case["module"], "入口")
        self.assertEqual(case["suggested_id"], "TC-0001")


class HealReviewTest(unittest.TestCase):
    def test_review_rejects_assertion_edit_without_rewriting_the_spec(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            spec = base / "runner/tests/sample.spec.ts"
            spec.parent.mkdir(parents=True)
            original = "await expect(dialog).toContainText('故意写错的标题');\n"
            spec.write_text(original, encoding="utf-8")
            proposal = base / "evidence/proposal.ts"
            proposal.parent.mkdir(parents=True)
            proposal.write_text(original.replace("故意写错的标题", "管理txt文件"), encoding="utf-8")
            evidence = base / "evidence/review.json"
            evidence.write_text(json.dumps({
                "message": "UIA_BUSINESS_FAILURE [rehearse-title]: injected expectation",
                "spec": "runner/tests/sample.spec.ts",
                "proposal": "evidence/proposal.ts",
            }, ensure_ascii=False), encoding="utf-8")
            result = heal_review(base, "evidence/review.json")
            kept = spec.read_text(encoding="utf-8")
        self.assertFalse(result["accept"])
        self.assertEqual(result["kind"], "suspected_product_bug")
        self.assertTrue(result["spec_unchanged"])
        self.assertIn("故意写错的标题", result["rejected_diff"])
        self.assertEqual(kept, original)
        self.assertEqual(subprocess.call(["node", "--check", str(ROOT / "assets/playwright-runner/support/heal.mjs")]), 0)
