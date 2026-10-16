"""Measure RSS of an already-running process; no model/server lifecycle control."""

import os
from pathlib import Path
import platform
import subprocess
import threading
import time


def parse_linux_status(source):
    """Parse /proc/PID/status in kB; VmHWM is kernel's process-lifetime peak."""
    values = {}
    for line in source.splitlines():
        key, _, value = line.partition(":")
        if key in ("VmRSS", "VmHWM"):
            words = value.split()
            if len(words) >= 2 and words[1] == "kB" and words[0].isdigit():
                values[key] = int(words[0]) * 1024
    return values.get("VmRSS"), values.get("VmHWM")


def parse_mac_ps_rss(source):
    """ps -o rss= reports KiB resident for one process."""
    raw = source.strip().split()
    if len(raw) != 1 or not raw[0].isdigit():
        raise ValueError("ps RSS no es un único número válido")
    return int(raw[0]) * 1024


def command_name(pid):
    output = subprocess.check_output(
        ["ps", "-p", str(pid), "-o", "comm="],
        stderr=subprocess.DEVNULL, text=True, timeout=5,
    ).strip()
    return Path(output).name


def read_rss(pid, os_name=None):
    os_name = os_name or platform.system()
    if os_name == "Linux":
        status = Path(f"/proc/{pid}/status").read_text(encoding="ascii")
        rss, hwm = parse_linux_status(status)
        if rss is None:
            raise ValueError("VmRSS no disponible en /proc/PID/status")
        return rss, hwm
    if os_name == "Darwin":
        output = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "rss="],
            stderr=subprocess.DEVNULL, text=True, timeout=5,
        )
        return parse_mac_ps_rss(output), None
    raise ValueError(f"SO no soportado para RSS: {os_name}")


class RSSMonitor:
    """Sample RSS. Observed peak != maximum between samples.

    On Linux additionally reports kernel VmHWM since PID start, which may
    include allocations before this measurement.
    """

    def __init__(self, pid, interval=0.1, test_fixture=False):
        if not isinstance(pid, int) or pid <= 0:
            raise ValueError("--pid exige entero positivo")
        if not 0.02 <= interval <= 2.0:
            raise ValueError("intervalo RSS entre 0.02 y 2 segundos")
        self.pid = pid
        self.interval = interval
        self.os_name = platform.system()
        actual = command_name(pid)
        if not test_fixture and actual != "llama-server":
            raise ValueError(f"PID {pid} corresponde a {actual!r}, no llama-server")
        self.process_name = actual
        self.samples = []
        self.hwm_bytes = None
        self.errors = []
        self._stop = threading.Event()
        self._thread = None

    def _sample(self):
        try:
            rss, hwm = read_rss(self.pid, self.os_name)
            self.samples.append(rss)
            if hwm is not None:
                self.hwm_bytes = max(hwm, self.hwm_bytes or 0)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self.errors.append(str(exc))
            self._stop.set()

    def _collect(self):
        while not self._stop.wait(self.interval):
            self._sample()

    def start(self):
        self._sample()  # initial reading also verifies PID still exists
        if self.errors:
            raise RuntimeError("RSS inicial falló: " + self.errors[0])
        self._thread = threading.Thread(target=self._collect, daemon=True)
        self._thread.start()

    def finish(self):
        if self._thread is not None:
            self._stop.set()
            self._thread.join(timeout=3)
            self._sample()
            self._thread = None
        return {
            "pid": self.pid,
            "process_name": self.process_name,
            "method": "proc_status_VmRSS_VmHWM" if self.os_name == "Linux" else "ps_rss_KiB",
            "interval_seconds": self.interval,
            "sample_count": len(self.samples),
            "rss_initial_bytes": self.samples[0] if self.samples else None,
            "rss_final_bytes": self.samples[-1] if self.samples else None,
            "rss_peak_sampled_bytes": max(self.samples) if self.samples else None,
            "kernel_vmhwm_bytes_since_process_start": self.hwm_bytes,
            "limitations": "Sampled peak may miss bursts; Linux VmHWM covers whole PID lifetime. "
                           "Excludes subprocesses, GPU allocations, mmap not resident and host pressure.",
            "errors": self.errors,
        }
