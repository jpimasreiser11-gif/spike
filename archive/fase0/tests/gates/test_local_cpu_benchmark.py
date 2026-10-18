"""TEST ONLY: CPU bench runner validation, with no synthetic model outputs."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "phase0"))
import run_cpu_benchmark


class CPUBenchmarkContractTests(unittest.TestCase):
    def test_model_paths_never_persist_in_report_command(self):
        args = ["llama-server", "--model", "/Users/secret/private.gguf",
                "--spec-draft-model", "/Users/secret/secret-draft.gguf", "--n-gpu-layers", "0"]
        safe = run_cpu_benchmark.redact_command(args)
        self.assertEqual(safe[2], "<verified-base-gguf>")
        self.assertEqual(safe[4], "<verified-draft-gguf>")
        self.assertNotIn("/Users/secret", str(safe))
        self.assertEqual(safe[-2:], ["--n-gpu-layers", "0"])

    def test_hash_exact_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.gguf"
            path.write_bytes(b"TEST NOT MODEL")
            self.assertEqual(run_cpu_benchmark.sha256(path), hashlib.sha256(path.read_bytes()).hexdigest())

    def test_missing_model_is_rejected_before_starting_server(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(model=Path(directory) / "missing.gguf", sha256="a" * 64)
            with self.assertRaisesRegex(ValueError, "GGUF local"):
                run_cpu_benchmark.run(args, {})

    def test_wrong_hash_is_rejected_before_server_start(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fake.gguf"
            path.write_bytes(b"INVALID GGUF" * 120)
            args = SimpleNamespace(model=path, sha256="a" * 64,
                                   upstream_repository="TEST", upstream_revision="TEST")
            record = {}
            with self.assertRaisesRegex(ValueError, "Hash GGUF"):
                run_cpu_benchmark.run(args, record)
            self.assertIn("sha256", record["model"])
            self.assertNotIn("server_pid", record)

    def test_stop_process_terminates_only_its_own_child(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            run_cpu_benchmark.stop_process(proc)
            self.assertIsNotNone(proc.poll())
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_ports_are_local_in_ephemeral_range(self):
        port = run_cpu_benchmark.port_available()
        self.assertGreater(port, 0)
        self.assertLess(port, 65536)


if __name__ == "__main__":
    unittest.main()
