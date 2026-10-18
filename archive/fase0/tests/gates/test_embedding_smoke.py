from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "phase0"))
import embedding_smoke


class SmokeEmbeddingTests(unittest.TestCase):
    def test_normalize_valid(self):
        self.assertEqual(embedding_smoke.norm([3, 4]), [0.6, 0.8])

    def test_non_finite_rejected(self):
        for vector in ([], [float("nan")], [float("inf")], [0, 0], ["bad"]):
            with self.subTest(vector=vector):
                with self.assertRaises(ValueError):
                    embedding_smoke.norm(vector)


if __name__ == "__main__":
    unittest.main()
