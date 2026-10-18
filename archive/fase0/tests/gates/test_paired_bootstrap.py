from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "phase0"))
import paired_bootstrap


def manifest(cases):
    return {
        "dataset": {"sha256": "a" * 64, "held_out": True, "license_review": "approved"},
        "models": {"base_sha256": "b" * 64, "specialist_sha256": "c" * 64,
                   "base_quantized": True, "specialist_quantized": True},
        "cases": cases,
    }


class BootstrapTests(unittest.TestCase):
    def test_gain_detected_in_unit_fixture_only(self):
        # Synthetic internal fixture tests math, not a real Spike performance claim.
        data = manifest([{"id": str(i), "group_id": str(i), "base_correct": False, "specialist_correct": True} for i in range(12)])
        stats = paired_bootstrap.bootstrap(paired_bootstrap.validate(data), 1000, seed=42)
        self.assertTrue(stats["significant_improvement"])
        self.assertEqual(stats["ci95_lower_points"], 100)

    def test_no_improvement_fails_gate(self):
        data = manifest([{"id": str(i), "group_id": str(i), "base_correct": True, "specialist_correct": True} for i in range(12)])
        self.assertFalse(paired_bootstrap.bootstrap(paired_bootstrap.validate(data), 1000)["significant_improvement"])

    def test_rejects_duplicate_ids(self):
        data = manifest([{"id": "same", "group_id": "family", "base_correct": False, "specialist_correct": True}] * 2)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            paired_bootstrap.validate(data)

    def test_rejects_non_quantized_results(self):
        data = manifest([{"id": "0", "group_id": "family", "base_correct": False, "specialist_correct": True}])
        data["models"]["specialist_quantized"] = False
        with self.assertRaisesRegex(ValueError, "quantized"):
            paired_bootstrap.validate(data)

    def test_rejects_unlicensed_eval_data(self):
        data = manifest([{"id": "0", "group_id": "family", "base_correct": False, "specialist_correct": True}])
        data["dataset"]["license_review"] = "pending"
        with self.assertRaisesRegex(ValueError, "approved"):
            paired_bootstrap.validate(data)

    def test_same_document_prompts_are_one_cluster(self):
        data = manifest([{"id": str(i), "group_id": "one_document",
                          "base_correct": False, "specialist_correct": True} for i in range(20)])
        stats = paired_bootstrap.bootstrap(paired_bootstrap.validate(data), 1000)
        self.assertEqual(stats["n"], 20)
        self.assertEqual(stats["grouped_n"], 1)

    def test_group_id_is_required(self):
        data = manifest([{"id": "0", "base_correct": False, "specialist_correct": True}])
        with self.assertRaisesRegex(ValueError, "group_id"):
            paired_bootstrap.validate(data)


if __name__ == "__main__":
    unittest.main()
