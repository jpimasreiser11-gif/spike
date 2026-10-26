---
name: performance-profiler
description: Use for Python performance profiling with cProfile and measured bottleneck analysis.
license: Apache-2.0
allowed-tools:
- read_file
- python
metadata:
  author: SPIKE contributors
  spike-specialists:
  - code
  spike-keywords: cprofile, perfila, rendimiento, cuellos de botella, profile performance, bottlenecks, profiling
---

# Performance profiler

1. Establish a reproducible workload, expected output and resource budget. Read the code first; do not profile
   untrusted or expensive jobs automatically. Reply in the user's language.
2. With execution permission, use the Python standard library: cProfile.Profile().runcall(target, *args), then
   pstats.Stats(profile).strip_dirs().sort_stats("cumulative").print_stats(20). Save reports only in the workspace.
   Keep imports, input setup and the measured region explicit. cProfile adds overhead; it is not a latency SLA.
3. Repeat a small baseline with time.perf_counter for wall time. Record Python version, input size and repetitions.
   Compare total versus cumulative time and call counts; identify the limiting function before proposing a change.
4. Change one thing and rerun the same workload and correctness checks. Report measured values and variation,
   with profiler overhead and environment limits. Never fabricate speedups or claim real-weight performance.
5. If execution or the workload is unavailable, return the commands and label the investigation not measured.
   Do not start models, downloads, training or large benchmarks. Use normal tool permissions for all execution.
