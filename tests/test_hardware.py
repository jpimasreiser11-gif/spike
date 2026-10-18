"""Starting settings from the machine: RAM sets the quantization and context, and without a GPU the context stays
at 8K because a long prompt is slow there (measured: evals/results/bench-x86-16gb-20261018)."""

from spike.runtime.hardware import CPU_CONTEXT, HardwareInfo, recommend


def machine(ram: float, apple: bool = False) -> HardwareInfo:
    return HardwareInfo(os="Darwin" if apple else "Linux", arch="arm64" if apple else "x86_64", cpu_model="test",
                        physical_cores=4, logical_cores=4, total_ram_gb=ram, available_ram_gb=ram / 2,
                        apple_silicon=apple, cpu_flags=[] if apple else ["avx2"])


def test_cpu_only_keeps_the_context_at_8k():
    rec = recommend(machine(15.7))
    assert (rec.quant, rec.context, rec.gpu_layers) == ("Q4_K_M", CPU_CONTEXT, 0)
    assert any("CPU only" in n for n in rec.notes)
    assert recommend(machine(64)).context == CPU_CONTEXT and recommend(machine(64)).quant == "Q8_0"
    assert recommend(machine(6)).context == 8192 and not any("CPU only" in n for n in recommend(machine(6)).notes)


def test_apple_silicon_uses_metal_and_the_ram_based_context():
    assert (recommend(machine(16, apple=True)).context, recommend(machine(16, apple=True)).gpu_layers) == (32768, 99)
    assert recommend(machine(36, apple=True)).context == 65536
