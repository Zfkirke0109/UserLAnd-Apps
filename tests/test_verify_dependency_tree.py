import tempfile
import unittest
from pathlib import Path

from tools.verify_dependency_tree import verify_dependency_tree


class DependencyTreeTests(unittest.TestCase):
    def test_missing_files_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            errors = verify_dependency_tree(Path(directory))

            self.assertTrue(
                any("UserLAndLibrary/app/build.gradle" in error for error in errors)
            )


if __name__ == "__main__":
    unittest.main()
