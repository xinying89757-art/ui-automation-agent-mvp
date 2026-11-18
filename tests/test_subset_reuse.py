import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from uia_core import common, workflow, profiles

SOURCE = Path(__file__).resolve().parents[1]


def row(cid, content='v1'):
    return {"suggested_id": cid, "identity_key": "id-" + cid, "content_hash": cid + content, "original_id": cid,
            "title": cid, "module": "m", "priority": "P1", "sheet": "S", "rows": [2]}


class SubsetReuseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="uia-subset-")
        self.root = Path(self.temp.name)
        shutil.copytree(SOURCE / "assets", self.root / "assets", ignore=shutil.ignore_patterns("node_modules", "results"))
        self.patches = [patch.object(module, "ROOT", self.root) for module in (common, workflow, profiles)]
        for item in self.patches:
            item.start()
        credentials = self.root / "private-source.json"
        common.atomic_write(credentials, {"account": "a", "password": "p"})
        profile = profiles.setup("offline", "production", "en.example.test", credentials_file=credentials)["config"]
        self.base = Path(workflow.init("SUBSET", profile)["run"]).parent
        workflow.scaffold(self.base)
        self.m = common.read_json(self.base / "run.json")
        self.xlsx = self.root / "cases.xlsx"; self.xlsx.write_bytes(b"x")

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.temp.cleanup()

    def load(self, selected, rows):
        self.m["selected_cases"] = selected
        with patch.object(workflow, "extract", return_value={"cases": rows, "gaps": [], "sheets": ["S"]}):
            workflow.import_excel(self.base, self.m, self.xlsx)

    def test_switching_subsets_keeps_results_of_deselected_cases(self):
        self.load(["TC-1"], [row("TC-1"), row("TC-2")])
        self.m["cases"]["TC-1"].update(result="passed", work_status="finished", stability="stable", pass_streak=1)
        self.load(["TC-2"], [row("TC-1"), row("TC-2")])
        self.assertEqual(sorted(self.m["cases"]), ["TC-2"])
        self.assertEqual([a["reason"] for a in self.m["archived_cases"]], ["deselected"])
        self.load(["TC-1"], [row("TC-1"), row("TC-2")])
        self.assertEqual(self.m["cases"]["TC-1"]["result"], "passed")
        self.assertEqual(self.m["cases"]["TC-1"]["work_status"], "finished")
        # A case whose source changed while deselected starts over.
        self.load(["TC-2"], [row("TC-1"), row("TC-2")])
        self.load(["TC-1"], [row("TC-1", "v2"), row("TC-2")])
        self.assertIsNone(self.m["cases"]["TC-1"]["result"])

    def test_case_removed_from_source_is_still_archived_as_removed(self):
        self.load(None, [row("TC-1"), row("TC-2")])
        self.load(None, [row("TC-2")])
        self.assertEqual([a["reason"] for a in self.m["archived_cases"]], ["removed_from_source"])


if __name__ == "__main__":
    unittest.main()
