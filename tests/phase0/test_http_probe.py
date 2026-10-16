"""TEST ONLY: fake HTTP servers verify parser/harness, NEVER benchmark results."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "phase0" / "smoke_http.sh"
sys.path.insert(0, str(ROOT / "scripts" / "phase0"))
import rss_monitor  # noqa: E402


class FakeLlamaHandler(BaseHTTPRequestHandler):
    """TEST FAKE only. No inference, no model, no benchmark."""

    def log_message(self, *args):
        pass

    def _json(self, value):
        content = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if self.path == "/health":
            self._json({"status": self.server.health})
        elif self.path == "/v1/models":
            self._json(self.server.models)
        elif self.path == "/lora-adapters":
            self._json(self.server.adapters)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        length = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(length))
        self.server.requests.append(payload)
        adapter = (payload.get("lora") or [{}])[0].get("id")
        if adapter == 0:
            content = "ALPHA"
        elif adapter == 1:
            content = "BETA"
        else:
            content = "READY"
        if self.server.bleed_a2 and len(self.server.requests) == 3:
            content = "BETA"
        self.send_response(200)
        self.send_header(
            "Content-Type", "application/json" if self.server.bad_content_type else "text/event-stream")
        self.end_headers()
        if self.server.bad_content_type:
            self.wfile.write(b'{"choices":[]}')
        else:
            event = [] if self.server.invalid_event else {"choices": [{"delta": {"content": content}}]}
            chunk = json.dumps(event).encode()
            self.wfile.write(b"data: " + chunk + b"\n\n")
            if not self.server.no_done:
                self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


class FakeHarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="spike-TEST-fake-")
        self.addCleanup(self.temp.cleanup)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeLlamaHandler)
        self.server.health = "ok"
        self.server.models = {"data": [{"id": "FAKE_TEST_MODEL"}]}
        self.server.adapters = [{"id": 0, "path": "FAKE_TEST_A"}, {"id": 1, "path": "FAKE_TEST_B"}]
        self.server.requests = []
        self.server.no_done = False
        self.server.bad_content_type = False
        self.server.invalid_event = False
        self.server.bleed_a2 = False
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = "http://127.0.0.1:" + str(self.server.server_port)

    def invoke(self, *extra, url=None, output=None, test=True, cwd=None):
        out = Path(output or Path(self.temp.name) / "test-output.json")
        args = ["bash", str(SCRIPT), "--url", url or self.url,
                "--output", str(out), "--timeout", "2"]
        if test:
            args.append("--test-harness")
        args.extend(extra)
        result = subprocess.run(args, cwd=cwd or self.temp.name, text=True,
                                capture_output=True, timeout=12)
        try:
            data = json.loads(out.read_text()) if out.exists() else None
        except json.JSONDecodeError:
            data = None  # File intentionally contains non-JSON in no-overwrite test.
        return result, data

    def test_test_fake_smoke_has_real_sse_parser_and_explicit_label(self):
        result, data = self.invoke("--expected-model", "FAKE_TEST_MODEL", "--pid", str(__import__("os").getpid()))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(data["status"], "TEST_FAKE_PASS_HTTP_SMOKE_ONLY")
        self.assertEqual(data["evidence_kind"], "TEST_FAKE_HARNESS_NOT_BENCHMARK")
        self.assertEqual(data["server"]["model_id"], "FAKE_TEST_MODEL")
        self.assertGreaterEqual(data["measurement"]["ttft_ms"], 0)
        self.assertEqual(data["measurement"]["visible_response_preview"], "READY")
        self.assertTrue(data["measurement"]["stream_done"])
        self.assertGreaterEqual(data["memory"]["sample_count"], 2)
        self.assertGreater(data["memory"]["rss_peak_sampled_bytes"], 0)
        self.assertEqual(self.server.requests[0]["cache_prompt"], False)

    def test_aba_uses_three_distinct_real_http_requests(self):
        result, data = self.invoke("--isolation-a", "0", "--isolation-b", "1",
                                   "--isolation-prompt", "TEST: A or B?",
                                   "--expect-a", "ALPHA", "--expect-b", "BETA")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(data["status"], "TEST_FAKE_PASS_ABA_SENTINELS_ONLY")
        self.assertEqual([x["step"] for x in data["isolation"]["steps"]], ["A1", "B", "A2"])
        self.assertEqual([x["adapter_id"] for x in data["isolation"]["steps"]], [0, 1, 0])
        self.assertTrue(all(data["isolation"]["assertions"].values()))
        self.assertEqual([r["lora"][0]["id"] for r in self.server.requests], [0, 1, 0])
        self.assertTrue(all(r["messages"][0]["content"] == "TEST: A or B?" for r in self.server.requests))

    def test_aba_contamination_fails(self):
        self.server.bleed_a2 = True
        result, data = self.invoke("--isolation-a", "0", "--isolation-b", "1",
                                   "--isolation-prompt", "TEST: A or B?",
                                   "--expect-a", "ALPHA", "--expect-b", "BETA")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(data["status"], "TEST_FAKE_FAIL")
        self.assertFalse(data["isolation"]["assertions"]["a_reproducible_exact"])

    def test_missing_adapter_fails_before_chat(self):
        self.server.adapters = [{"id": 0, "path": "FAKE_TEST_A"}]
        result, data = self.invoke("--isolation-a", "0", "--isolation-b", "1",
                                   "--isolation-prompt", "test",
                                   "--expect-a", "ALPHA", "--expect-b", "BETA")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.server.requests, [])
        self.assertIn("no aparecen", data["error"])

    def test_missing_done_and_invalid_content_type_fail(self):
        self.server.no_done = True
        result, data = self.invoke()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(data["status"], "TEST_FAKE_FAIL")
        self.server.no_done = False
        self.server.bad_content_type = True
        output = Path(self.temp.name) / "content-type.json"
        result, data = self.invoke(output=output)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no devolvió SSE", data["error"])

    def test_malformed_sse_and_models_emit_fail_json(self):
        self.server.invalid_event = True
        result, data = self.invoke()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(data["status"], "TEST_FAKE_FAIL")
        self.assertIn("evento SSE", data["error"])
        self.server.invalid_event = False
        self.server.models = []
        result, data = self.invoke(output=Path(self.temp.name) / "bad-models.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("/v1/models", data["error"])

    def test_health_and_model_mismatch_fail(self):
        self.server.health = "loading model"
        result, data = self.invoke()
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(data["server"]["model_id"])
        self.server.health = "ok"
        result, data = self.invoke("--expected-model", "REAL_MODEL", output=Path(self.temp.name) / "wrong.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no coincide", data["error"])

    def test_no_server_writes_fail_without_fake_timings(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        result, data = self.invoke(url=f"http://127.0.0.1:{port}", test=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(data["status"], "FAIL")
        self.assertEqual(data["evidence_kind"], "LIVE_SERVER_UNVERIFIED_MODEL")
        self.assertIsNone(data["measurement"]["ttft_ms"])
        self.assertIsNone(data["server"]["model_id"])

    def test_reject_remote_urls_and_missing_aba_flags(self):
        result, data = self.invoke(url="http://example.org:8080")
        self.assertEqual(result.returncode, 1)
        self.assertIn("127.0.0.1", data["error"])
        result, data = self.invoke("--isolation-a", "0", output=Path(self.temp.name) / "argparse.json")
        self.assertEqual(result.returncode, 2)
        self.assertIsNone(data)

    def test_path_safety_no_overwrite_and_no_fake_under_reports(self):
        out = Path(self.temp.name) / "exists.json"
        out.write_text("DO_NOT_REPLACE")
        result, _ = self.invoke(output=out)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(out.read_text(), "DO_NOT_REPLACE")
        result, data = self.invoke(output=ROOT / "reports" / "phase0" / "FORBIDDEN_FAKE.json")
        self.assertEqual(result.returncode, 2)
        self.assertIsNone(data)

    def test_live_mode_rejects_non_llama_pid_without_fake_http(self):
        import os
        with self.assertRaisesRegex(ValueError, "no llama-server"):
            rss_monitor.RSSMonitor(os.getpid(), test_fixture=False)


class MemoryParserTests(unittest.TestCase):
    def test_linux_status_peak_and_rss_bytes(self):
        sample = "Name:\tllama-server\nVmHWM:\t  200000 kB\nVmRSS:\t 123456 kB\n"
        self.assertEqual(rss_monitor.parse_linux_status(sample),
                         (123456 * 1024, 200000 * 1024))
        self.assertEqual(rss_monitor.parse_linux_status("Name: x\n"), (None, None))

    def test_darwin_ps_parser(self):
        self.assertEqual(rss_monitor.parse_mac_ps_rss("  4321\n"), 4321 * 1024)
        with self.assertRaises(ValueError):
            rss_monitor.parse_mac_ps_rss("not a number")


if __name__ == "__main__":
    unittest.main()
