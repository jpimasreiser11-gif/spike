"""S7 TEST FAKE ONLY: validate HTTP/parser/evaluation, never model benchmarks."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "phase0" / "s7_readiness.py"
sys.path.insert(0, str(SCRIPT.parent))
import s7_readiness  # noqa: E402


class TEST_FAKE_Server(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == "/health":
            data = {"status": "ok"}
        elif self.path == "/v1/models":
            data = {"data": [{"id": "TEST_FAKE_PRIMARY"}]}
        else:
            self.send_error(404)
            return
        payload = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        self.server.requests.append((self.path, payload))
        if self.path == "/v1/chat/completions":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            event = json.dumps({"choices": [{"delta": {
                "content": "DIFFERENT TEST RESPONSE" if self.server.different_response else "TEST RESPONSE"
            }}]}).encode()
            self.wfile.write(b"data: " + event + b"\n\ndata: [DONE]\n\n")
        elif self.path == "/v1/embeddings":
            text = payload.get("input", "")
            if self.server.bad_embeddings:
                vec = []
            else:
                vec = [1.0, 0.0, 0.2] if text.startswith("finance-") else [0.0, 1.0, 0.2]
            body = json.dumps({"data": [{"index": 0, "embedding": vec}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)


def corpus():
    examples = []
    for label in ("finance", "medicine"):
        for index, split in ((0, "train"), (1, "train"), (2, "test")):
            examples.append({"id": f"{label}{index}", "text": f"{label}-{index}",
                             "label": label, "split": split})
    return {"license_review": "approved", "held_out": True, "examples": examples}


class S7HarnessTEST(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="spike-s7-TEST-FAKE-")
        self.addCleanup(self.temp.cleanup)
        self.servers = []

    def fake(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), TEST_FAKE_Server)
        srv.requests = []
        srv.bad_embeddings = False
        srv.different_response = False
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        self.servers.append(srv)
        return f"http://127.0.0.1:{srv.server_port}"

    def dataset_file(self, value=None):
        path = Path(self.temp.name) / "labeled-dataset.json"
        path.write_text(json.dumps(corpus() if value is None else value), encoding="utf-8")
        return str(path)

    def run_cli(self, action, *args, output=None, test=True):
        output = Path(output or Path(self.temp.name) / "result.json")
        argv = [sys.executable, str(SCRIPT), "--output", str(output), "--timeout", "2"]
        if test:
            argv.append("--test-harness")
        argv.extend((action, *args))
        p = subprocess.run(argv, text=True, capture_output=True, timeout=16, cwd=self.temp.name)
        try:
            data = json.loads(output.read_text()) if output.exists() else None
        except json.JSONDecodeError:
            data = None
        return p, data

    def test_compare_two_sessions_marks_mock_and_records_both(self):
        baseline, draft = self.fake(), self.fake()
        p, data = self.run_cli("compare", "--baseline-url", baseline, "--draft-url", draft,
                               "--model-id", "TEST_FAKE_PRIMARY", "--rounds", "2")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(data["status"], "TEST_FAKE_OBSERVED_PAIR_NOT_CERTIFIED")
        self.assertEqual(data["evidence_kind"], "TEST_FAKE_NOT_BENCHMARK")
        self.assertFalse(data["summary"]["proof_of_acceleration"])
        self.assertTrue(data["summary"]["all_visible_outputs_equal"])
        self.assertEqual([r["arm"] for r in data["samples"]], ["baseline", "draft", "draft", "baseline"])
        self.assertEqual(len(self.servers[0].requests), 2)
        self.assertEqual(len(self.servers[1].requests), 2)
        self.assertTrue(all(r["measurement"]["ttft_ms"] is not None for r in data["samples"]))
        self.assertIsNone(data["process_evidence"]["baseline"])

    def test_different_visible_outputs_fail_comparison(self):
        a, b = self.fake(), self.fake()
        self.servers[1].different_response = True
        p, data = self.run_cli("compare", "--baseline-url", a, "--draft-url", b,
                               "--model-id", "TEST_FAKE_PRIMARY", "--rounds", "2")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(data["status"], "TEST_FAKE_FAIL")
        self.assertFalse(data["summary"]["all_visible_outputs_equal"])
        self.assertIn("respuestas visibles diferentes", data["error"])

    def test_compare_no_server_is_fail_no_bench_claim(self):
        baseline = self.fake()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            absent = f"http://127.0.0.1:{sock.getsockname()[1]}"
        p, data = self.run_cli("compare", "--baseline-url", baseline, "--draft-url", absent,
                               "--model-id", "TEST_FAKE_PRIMARY", "--rounds", "2", test=False)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(data["status"], "FAIL")
        self.assertIsNone(data["summary"])
        self.assertEqual(data["samples"], [])

    def test_reject_same_port_remote_and_wrong_model(self):
        a, b = self.fake(), self.fake()
        options = ("--baseline-url", a, "--draft-url", a,
                   "--model-id", "TEST_FAKE_PRIMARY", "--rounds", "2")
        p, data = self.run_cli("compare", *options)
        self.assertEqual(p.returncode, 1)
        self.assertIn("dos puertos", data["error"])
        p, data = self.run_cli("compare", "--baseline-url", "http://example.org:80",
                               "--draft-url", b, "--model-id", "TEST_FAKE_PRIMARY",
                               "--rounds", "2", output=Path(self.temp.name) / "remote.json")
        self.assertEqual(p.returncode, 1)
        self.assertIn("127.0.0.1", data["error"])
        p, data = self.run_cli("compare", "--baseline-url", a, "--draft-url", b,
                               "--model-id", "WRONG", "--rounds", "2",
                               output=Path(self.temp.name) / "wrong.json")
        self.assertEqual(p.returncode, 1)
        self.assertIn("no está", data["error"])

    def test_route_labeled_holdout(self):
        url = self.fake()
        dataset = self.dataset_file()
        p, data = self.run_cli("route", "--endpoint", url, "--model-id", "TEST_FAKE_PRIMARY",
                               "--dataset", dataset)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(data["status"], "TEST_FAKE_OBSERVED_EMBEDDING_ROUTING_NOT_CERTIFIED")
        self.assertEqual(data["result"]["n_test"], 2)
        self.assertEqual(data["result"]["n_train"], 4)
        self.assertEqual(data["result"]["accuracy"], 1)
        self.assertEqual(len(self.servers[0].requests), 6)
        self.assertTrue(all(x["split"] == "train" for x in corpus()["examples"][:2]))
        self.assertNotIn("finance-0", json.dumps(data["result"]))

    def test_route_dataset_missing_and_unapproved_fail(self):
        url = self.fake()
        p, data = self.run_cli("route", "--endpoint", url, "--model-id", "TEST_FAKE_PRIMARY",
                               "--dataset", str(Path(self.temp.name) / "missing.json"))
        self.assertEqual(p.returncode, 1)
        self.assertIsNone(data["result"])
        self.assertEqual(self.servers[0].requests, [])
        bad = corpus()
        bad["license_review"] = "pending"
        path = self.dataset_file(bad)
        p, data = self.run_cli("route", "--endpoint", url, "--model-id", "TEST_FAKE_PRIMARY",
                               "--dataset", path, output=Path(self.temp.name) / "bad.json")
        self.assertEqual(p.returncode, 1)
        self.assertIn("license_review", data["error"])
        self.assertEqual(self.servers[0].requests, [])

    def test_route_no_local_embedding_server_fails(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            missing_url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        p, data = self.run_cli("route", "--endpoint", missing_url, "--model-id", "NOT_RUNNING",
                               "--dataset", self.dataset_file(), test=False)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(data["status"], "FAIL")
        self.assertIsNone(data["result"])
        self.assertIsNone(data["server"])

    def test_route_rejects_train_test_leakage(self):
        examples = corpus()
        examples["examples"][-1]["text"] = examples["examples"][0]["text"]
        with self.assertRaisesRegex(ValueError, "duplicados"):
            s7_readiness.validate_dataset(examples)

    def test_route_malformed_embeddings_fail(self):
        url = self.fake()
        self.servers[0].bad_embeddings = True
        p, data = self.run_cli("route", "--endpoint", url, "--model-id", "TEST_FAKE_PRIMARY",
                               "--dataset", self.dataset_file())
        self.assertEqual(p.returncode, 1)
        self.assertIn("embedding", data["error"])
        self.assertIsNone(data["result"])

    def test_empty_or_nonfinite_embeddings_rejected(self):
        for vector in ([], [0, 0], [float("nan")], ["1", 1], [float("inf")]):
            with self.assertRaises(ValueError):
                s7_readiness.normalize(vector)

    def test_fake_output_under_reports_blocked_and_no_overwrite(self):
        url = self.fake()
        inside_reports = ROOT / "reports" / "phase0" / "S7-FORBIDDEN-TEST-FAKE.json"
        p, data = self.run_cli("route", "--endpoint", url, "--model-id", "TEST_FAKE_PRIMARY",
                               "--dataset", self.dataset_file(), output=inside_reports)
        self.assertEqual(p.returncode, 2)
        self.assertIsNone(data)
        self.assertFalse(inside_reports.exists())
        occupied = Path(self.temp.name) / "existing.json"
        occupied.write_text("do not overwrite")
        p, _ = self.run_cli("route", "--endpoint", url, "--model-id", "TEST_FAKE_PRIMARY",
                            "--dataset", self.dataset_file(), output=occupied)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(occupied.read_text(), "do not overwrite")

    def test_process_baseline_draft_flag_validation(self):
        from unittest.mock import patch
        with patch.object(s7_readiness, "RSSMonitor", return_value=object()), patch.object(
                s7_readiness.subprocess, "check_output", return_value="llama-server -m primary.gguf"):
            with self.assertRaisesRegex(RuntimeError, "--spec-draft-model"):
                s7_readiness.process_evidence(123, draft=True, test_harness=False)
        with patch.object(s7_readiness, "RSSMonitor", return_value=object()), patch.object(
                s7_readiness.subprocess, "check_output", return_value="llama-server --spec-draft-model d.gguf"):
            with self.assertRaisesRegex(RuntimeError, "baseline"):
                s7_readiness.process_evidence(123, draft=False, test_harness=False)

    def test_embedding_cpu_flag_fails_if_missing(self):
        from unittest.mock import patch
        with patch.object(s7_readiness, "RSSMonitor", return_value=object()), patch.object(
                s7_readiness.subprocess, "check_output", return_value="llama-server -m embed.gguf"):
            with self.assertRaisesRegex(RuntimeError, "GPU layers=0"):
                s7_readiness.embedding_cpu_evidence(567, test_harness=False)
        with patch.object(s7_readiness, "RSSMonitor", return_value=object()), patch.object(
                s7_readiness.subprocess, "check_output", return_value="llama-server --n-gpu-layers 0"):
            _, metadata = s7_readiness.embedding_cpu_evidence(567, test_harness=False)
            self.assertTrue(metadata["cpu_only_flag_visible"])


if __name__ == "__main__":
    unittest.main()
