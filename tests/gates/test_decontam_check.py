import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "phase0"))
import decontam_check


def row(identifier, family, raw, norm):
    return {"id": identifier, "family_id": family, "raw_sha256": raw * 64,
            "normalized_sha256": norm * 64, "license_approved": True}


class DecontaminationTests(unittest.TestCase):
    def setUp(self):
        self.data = {"train": [row("t1", "doc-1", "a", "b")],
                     "eval": [row("e1", "doc-2", "c", "d")]}

    def test_clean_pair_is_only_exact_family_pass(self):
        result = decontam_check.check(self.data)
        self.assertEqual(result["status"], "PASS_EXACT_AND_FAMILY_CHECK_ONLY")
        self.assertFalse(result["collisions"])
        self.assertIn("pretraining", result["limitations"])

    def test_identical_normalized_hash_fails(self):
        data = copy.deepcopy(self.data)
        data["eval"][0]["normalized_sha256"] = "b" * 64
        result = decontam_check.check(data)
        self.assertEqual(result["status"], "FAIL_CONTAMINATION_DETECTED")
        self.assertIn("normalized_sha256", result["collisions"][0]["collision_fields"])

    def test_same_family_even_if_hash_diff_fails(self):
        data = copy.deepcopy(self.data)
        data["eval"][0]["family_id"] = "doc-1"
        self.assertEqual(decontam_check.check(data)["status"], "FAIL_CONTAMINATION_DETECTED")

    def test_unknown_license_fails_closed(self):
        self.data["train"][0]["license_approved"] = False
        with self.assertRaisesRegex(ValueError, "derechos"):
            decontam_check.check(self.data)

    def test_missing_manifest_data_is_not_clean(self):
        self.data["eval"][0].pop("family_id")
        with self.assertRaisesRegex(ValueError, "family_id"):
            decontam_check.check(self.data)


if __name__ == "__main__":
    unittest.main()
