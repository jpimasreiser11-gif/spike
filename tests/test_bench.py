import mmap
import os
from pathlib import Path

import pytest

from spike.bench import rss_anon_bytes

MB = 2**20


@pytest.mark.skipif(not Path("/proc/self/status").exists(), reason="needs Linux /proc")
def test_rss_anon_counts_heap_but_not_mmapped_file_pages(tmp_path):
    path = tmp_path / "weights.bin"
    path.write_bytes(os.urandom(64 * MB))
    before = rss_anon_bytes(os.getpid())
    with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
        assert sum(m[i] for i in range(0, len(m), 4096)) >= 0  # fault in every page of the file
        after_mmap = rss_anon_bytes(os.getpid())
    assert after_mmap - before < 16 * MB

    heap = bytearray(64 * MB)
    for i in range(0, len(heap), 4096):
        heap[i] = 1
    assert rss_anon_bytes(os.getpid()) - after_mmap > 48 * MB


def test_rss_anon_is_none_for_a_missing_process():
    assert rss_anon_bytes(2**22 + 12345) is None
