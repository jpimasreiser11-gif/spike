import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "phase0"))
import create_s3_pilot


class S3PilotDataTests(unittest.TestCase):
    def test_200_synthetic_arithmetic_samples(self):
        rows = create_s3_pilot.create(42)
        self.assertEqual(len(rows), 200)
        self.assertEqual(sum(x["split"] == "train" for x in rows), 180)
        self.assertEqual(sum(x["split"] == "valid" for x in rows), 20)
        self.assertTrue(all("Factura" in row["messages"][0]["content"] or
                            "Calculate" in row["messages"][0]["content"] for row in rows))
        self.assertTrue(all(row["arithmetic"]["result_eur"] in row["messages"][1]["content"] for row in rows))

    def test_reproducibility_same_seed_and_difference_across_seeds(self):
        first = create_s3_pilot.serialize(create_s3_pilot.create(42), "train")
        second = create_s3_pilot.serialize(create_s3_pilot.create(42), "train")
        other = create_s3_pilot.serialize(create_s3_pilot.create(43), "train")
        self.assertEqual(hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest())
        self.assertNotEqual(first, other)

    def test_mlx_messages_structure(self):
        content = create_s3_pilot.serialize(create_s3_pilot.create(42), "valid")
        items = [json.loads(line) for line in content.splitlines()]
        self.assertEqual(len(items), 20)
        self.assertTrue(all(list(item) == ["messages"] for item in items))
        self.assertTrue(all([msg["role"] for msg in item["messages"]] == ["user", "assistant"]
                            for item in items))


if __name__ == "__main__":
    unittest.main()
