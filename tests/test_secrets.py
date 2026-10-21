import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from uia_core.secrets import drop_unsafe_artifacts, scrub_text


class SecretScrubTest(unittest.TestCase):
    def test_text_scrub_keeps_package_names(self):
        raw = "\n".join([
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.signaturevalue",
            "PIN码：ABC12",
            "person@example.com",
            "13800138000",
            "uin=100860001",
            "[QQ](https://wpa.qq.com/msgrd?v=3&uin=100860001): 100860001",
            "tel:+86-13800138000",
            "token=abc.def",
            "@playwright/test",
        ])
        cleaned = scrub_text(raw)
        self.assertNotIn("eyJ", cleaned)
        self.assertNotIn("ABC12", cleaned)
        self.assertNotIn("person@example.com", cleaned)
        self.assertNotIn("13800138000", cleaned)
        self.assertNotIn("100860001", cleaned)
        self.assertIn("[QQ](https://wpa.qq.com/msgrd?v=3&uin=[REDACTED])", cleaned)
        self.assertNotIn("tel:+86", cleaned)
        self.assertNotIn("token=abc.def", cleaned)
        self.assertIn("@playwright/test", cleaned)
        self.assertIn("[REDACTED]", cleaned)
        self.assertIn("[email]", cleaned)
        self.assertIn("[phone]", cleaned)

    def test_drop_removes_snapshots_and_leaves_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "case-results.json").write_text('{"ok": true}', encoding="utf-8")
            (root / "error-context.md").write_text("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.signaturevalue", encoding="utf-8")
            (root / "trace.zip").write_bytes(b"zip")
            (root / "shot.png").write_bytes(b"png")
            report = root / "playwright-report"
            report.mkdir()
            (report / "index.html").write_text("PIN码：ABC12", encoding="utf-8")
            removed = drop_unsafe_artifacts(root)
            self.assertGreaterEqual(removed, 4)
            self.assertTrue((root / "case-results.json").is_file())
            self.assertFalse((root / "error-context.md").exists())
            self.assertFalse((root / "trace.zip").exists())
            self.assertFalse((root / "shot.png").exists())
            self.assertFalse(report.exists())
            with zipfile.ZipFile(root / "scripts.zip", "w") as archive:
                archive.writestr("runner/package.json", '{"name": "@playwright/test"}')
            self.assertTrue((root / "scripts.zip").is_file())


if __name__ == "__main__":
    unittest.main()
