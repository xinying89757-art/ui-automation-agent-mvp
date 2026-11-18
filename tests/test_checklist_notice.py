import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uia_core.experience import checklist_notice


class ChecklistNoticeTest(unittest.TestCase):
    def test_notice(self):
        self.assertEqual(checklist_notice({'entry_count': 3, 'memory_answer_count': 3, 'question_count': 0}), '清单全部来自环境记忆（3 项），本次 0 问')
        self.assertEqual(checklist_notice({'entry_count': 0, 'memory_answer_count': 0, 'question_count': 0}), '本次无清单项，0 问')
        self.assertIsNone(checklist_notice({'entry_count': 2, 'memory_answer_count': 1, 'question_count': 1}))
        self.assertIsNone(checklist_notice({'entry_count': 2, 'memory_answer_count': 1, 'question_count': 0}))


if __name__ == '__main__':
    unittest.main()
