import json
from pathlib import Path
import tempfile
import unittest

from sys import path as sys_path
sys_path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "phase0"))
import gate_report


class GateReportTests(unittest.TestCase):
    def test_missing_plan_is_explicitly_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "reports" / "phase0").mkdir(parents=True)
            gates = gate_report.inspect(root)["gates"]
            self.assertEqual(gates["plan_full"]["status"], "BLOCKED_MISSING_SOURCE")
            self.assertTrue(all(v["status"] != "PASS" for v in gates.values()))

    def test_http_success_alone_cannot_certify_a_model(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report_dir = root / "reports" / "phase0"
            report_dir.mkdir(parents=True)
            (report_dir / "sample.json").write_text(json.dumps({
                "schema": "spike.phase0.http-smoke.v1",
                "status": "PASS_HTTP_SMOKE_ONLY",
                "server": {"model_id": "fake-server-test"},
            }))
            inspected = gate_report.inspect(root)
            self.assertEqual(len(inspected["phase0_reports"]), 1)
            self.assertEqual(inspected["gates"]["http_smoke"]["status"], "NOT_VERIFIED")

    def test_plan_presence_never_auto_approves_phase(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "PLAN.md").write_text("fragmento")
            inspected = gate_report.inspect(root)
            self.assertEqual(inspected["gates"]["plan_full"]["status"], "MANUAL_REVIEW_REQUIRED")


if __name__ == "__main__":
    unittest.main()
