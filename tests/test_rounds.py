import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from uia_core import rounds


class RoundOneTest(unittest.TestCase):
    def test_round_one_has_no_prior_baseline_and_imports_workbook(self):
        with tempfile.TemporaryDirectory(prefix="uia-round-one-") as temp:
            root = Path(temp)

            def init(run_id, _profile):
                base = root / "runs" / run_id
                (base / "state").mkdir(parents=True)
                (base / "run.json").write_text(json.dumps({
                    "run_id": run_id, "config": {"environment": {"id": "production"}}, "cases": {}, "history": []
                }), encoding="utf-8")
                return {"run": str(base / "run.json")}

            def import_excel(_base, manifest, _excel):
                manifest["cases"] = {"TC-1": {"case_id": "TC-1"}}
                return {"total": 1}

            with patch.object(rounds, "ROOT", root), \
                    patch("uia_core.workflow.init", side_effect=init), \
                    patch("uia_core.workflow.scaffold"), \
                    patch("uia_core.workflow.import_excel", side_effect=import_excel), \
                    patch("uia_core.profiles.profile_path", return_value=Path("profile.json")), \
                    patch("uia_core.preconditions.sync_preconditions"):
                result = rounds.create(None, 1, "R1", "offline", "cases.xlsx")

            manifest = json.loads((root / "runs" / "R1" / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["round"], {
                "number": 1, "requirement_id": "R1", "environment": "production",
                "previous_run": None, "created_from": None,
            })
            self.assertEqual(result["re_explore"], ["TC-1"])
            self.assertEqual(result["import"], {"total": 1})

    def test_round_one_rejects_previous_run(self):
        with self.assertRaisesRegex(Exception, "Round 1 cannot have a previous-round baseline"):
            rounds.create("prior", 1, "R1", "offline", "cases.xlsx")


if __name__ == "__main__":
    unittest.main()
