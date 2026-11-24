import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uia_core.runtime import repair

class ReclassifiedRepairTest(unittest.TestCase):
    def test_evidence_backed_automation_reclassification_allows_repair_preserving_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'proof.json').write_text('{}')
            attempt = {'result': 'save_not_persisted', 'cleanup_verified': True, 'batch_id': 'B'}
            case = {'attempts': [attempt], 'result': 'automation_failure', 'classification': {'evidence': 'proof.json'}, 'repair_rounds': 0}
            run = {'cases': {'C': case}, 'config': {'execution': {'repair_rounds': 2}}, 'history': [], 'batches': []}
            self.assertEqual(repair(base, run, 'C', 'proof.json')['repair_round'], 1)
            self.assertEqual(attempt['result'], 'save_not_persisted')

    def test_unclassified_save_failure_cannot_be_repaired_as_automation(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'proof.json').write_text('{}')
            case = {'attempts': [{'result': 'save_not_persisted', 'cleanup_verified': True}], 'result': 'save_not_persisted', 'repair_rounds': 0}
            run = {'cases': {'C': case}, 'config': {'execution': {'repair_rounds': 2}}, 'history': []}
            with self.assertRaises(Exception): repair(base, run, 'C', 'proof.json')

if __name__ == '__main__': unittest.main()
