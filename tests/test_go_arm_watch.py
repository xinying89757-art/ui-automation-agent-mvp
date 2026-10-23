import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from uia_core import common, experience, remote_checks


class GoArmWatchTest(unittest.TestCase):
    def test_arms_runnable_cases_and_announces_handoff(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            m = {'cases': {'TC-0036': {'work_status': 'runnable'}, 'TC-0033': {'work_status': 'finished'}}, 'remote_watches': {}}
            def fake(base_, m_, cid, lead, watch):
                m_['remote_watches']['w1'] = {'save_not_before': 'S', 'watch_until': 'U'}
                return {'watch_id': 'w1', 'request': 'remote-checks/watch/w1/request.json'}
            with patch.object(remote_checks, 'arm_watch', side_effect=fake):
                armed = experience._arm_requested_watches(base, m, 'TC-0036', 20, 10)
                self.assertEqual(armed[0]['case_id'], 'TC-0036')
                self.assertEqual(common.read_json(base / 'remote-checks/watch/ARMED.json'), armed)
                with self.assertRaises(common.UiaError):
                    experience._arm_requested_watches(base, m, 'TC-0033', 20, 10)
            self.assertEqual(experience._arm_requested_watches(base, m, None, 20, 10), [])


if __name__ == '__main__':
    unittest.main()
