import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "phase0"))
import hash_artifacts


class HashArtifactTests(unittest.TestCase):
    def test_local_content_has_correct_sha_and_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.gguf"
            path.write_bytes(b"TEST BYTES, NOT MODEL")
            result = hash_artifacts.hash_file(path)
            self.assertEqual(result["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(result["size_bytes"], path.stat().st_size)

    def test_nonexistent_or_empty_artifact_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "not-model.gguf"
            with self.assertRaises(ValueError):
                hash_artifacts.hash_file(path)
            path.write_bytes(b"")
            with self.assertRaises(ValueError):
                hash_artifacts.hash_file(path)


if __name__ == "__main__":
    unittest.main()
