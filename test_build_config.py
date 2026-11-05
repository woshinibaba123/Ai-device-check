import tempfile,unittest
from pathlib import Path
from build_config import entrypoint

class BuildEntrypointTests(unittest.TestCase):
    def test_eng_target_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'lib').mkdir();(root/'lib/main_eng.dart').write_text('void main() {}')
            self.assertEqual(entrypoint(root,'lib/main_eng.dart'),'lib/main_eng.dart')
    def test_missing_target_and_outside_path_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for value in ('lib/missing.dart','../main.dart','/tmp/main.dart'):
                with self.assertRaises(ValueError):entrypoint(Path(tmp),value)
