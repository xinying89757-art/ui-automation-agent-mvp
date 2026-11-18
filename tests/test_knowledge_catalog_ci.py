import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uia_core.knowledge import validate


class RepoKnowledgeCatalogTests(unittest.TestCase):
    """The repo's own knowledge catalog must pass schema/duplicate/size/secret checks (CI gate)."""

    def test_repo_catalog_is_valid(self):
        self.assertGreaterEqual(validate()['patterns'], 1)
