"""Hardware detection and conservative runtime recommendations."""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

import psutil

GIB = 1024**3


@dataclass
class HardwareInfo:
    os: str
    arch: str
    cpu_model: str
    physical_cores: int
    logical_cores: int
    total_ram_gb: float
    available_ram_gb: float
    apple_silicon: bool
    cpu_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _cpu_model_and_flags() -> tuple[str, list[str]]:
    system = platform.system()
    if system == "Linux":
        model, flags = platform.processor() or "unknown", []
        try:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name") and model in ("unknown", ""):
                    model = line.split(":", 1)[1].strip()
                elif line.startswith(("flags", "Features")) and not flags:
                    flags = line.split(":", 1)[1].split()
        except OSError:
            pass
        interesting = {"avx", "avx2", "avx512f", "avx512_vnni", "avx_vnni", "f16c", "fma", "asimd", "sve", "i8mm", "dotprod", "asimddp"}
        return model, sorted(f for f in flags if f in interesting)
    if system == "Darwin":
        try:
            model = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True,
                                   timeout=2).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            model = "unknown"
        return model or "Apple", ["neon"] if platform.machine() == "arm64" else []
    return platform.processor() or "unknown", []


def detect() -> HardwareInfo:
    mem = psutil.virtual_memory()
    model, flags = _cpu_model_and_flags()
    return HardwareInfo(
        os=platform.system(),
        arch=platform.machine(),
        cpu_model=model,
        physical_cores=psutil.cpu_count(logical=False) or os.cpu_count() or 1,
        logical_cores=psutil.cpu_count(logical=True) or 1,
        total_ram_gb=round(mem.total / GIB, 1),
        available_ram_gb=round(mem.available / GIB, 1),
        apple_silicon=platform.system() == "Darwin" and platform.machine() == "arm64",
        cpu_flags=flags,
    )


@dataclass
class Recommendation:
    quant: str
    context: int
    kv_cache_type: str
    threads: int
    gpu_layers: int
    notes: list[str]


CPU_CONTEXT = 8192


def recommend(hw: HardwareInfo) -> Recommendation:
    """Pick settings that leave headroom for the OS and the user's other apps.

    Numbers are starting points; `spike bench` measures the real machine and should be used to tune them.
    """
    notes: list[str] = []
    ram = hw.total_ram_gb
    if ram < 7.5:
        quant, context = "Q4_K_M", 8192
        notes.append("Less than 8 GB RAM: expect slow generation; close other apps.")
    elif ram < 15.5:
        quant, context = "Q4_K_M", 16384
    elif ram < 31:
        quant, context = "Q4_K_M", 32768
    else:
        quant, context = "Q8_0", 65536
    threads = max(1, min(hw.physical_cores, 8 if not hw.apple_silicon else hw.physical_cores))
    if hw.arch in ("x86_64", "AMD64") and "avx2" not in hw.cpu_flags and hw.os == "Linux":
        notes.append("CPU without AVX2 detected: llama.cpp will run, but several times slower.")
    gpu_layers = 99 if hw.apple_silicon else 0  # Metal on Apple Silicon; CPU elsewhere by default
    if not gpu_layers and context > CPU_CONTEXT:
        # Measured on a 4-core x86 with 16 GB (evals/results/bench-x86-16gb-20261018): memory is fine at 32K, but a
        # prompt that long takes over 1.5 h before the first word; 8K takes about 13 min. Raise it in Settings on a
        # faster CPU.
        context = CPU_CONTEXT
        notes.append("CPU only: context set to 8K because long prompts are slow without a GPU; raise it in Settings "
                     "if your CPU is fast.")
    return Recommendation(quant=quant, context=context, kv_cache_type="q8_0", threads=threads,
                          gpu_layers=gpu_layers, notes=notes)
