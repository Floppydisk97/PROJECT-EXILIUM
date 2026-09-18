from __future__ import annotations

import json
import os
import re
import statistics
from pathlib import Path

root = Path(os.environ.get("BENCHMARK_OUTPUT", "benchmark-output"))


def timed(kind: str):
    runs = []
    for index in range(1, 4):
        data = json.loads((root / f"{kind}-run-{index}.json").read_text())
        timing = (root / f"{kind}-run-{index}.time").read_text()
        rss = int(re.search(r"Maximum resident set size \(kbytes\):\s*(\d+)", timing).group(1))
        runs.append({"seconds": data["generation_seconds"], "rss_kb": rss})
    return runs


baseline_runs, candidate_runs = timed("baseline"), timed("candidate")
spectra = []
worldgen_ok = True
spectrum_ok = True
for frequency in (60, 139):
    for seed in ("Hesperia-01", "Hesperia-02", "Hesperia-03", "Hesperia-04"):
        baseline = json.loads((root / f"spectrum-baseline-{seed}-f{frequency}.json").read_text())
        candidate = json.loads((root / f"spectrum-candidate-{seed}-f{frequency}.json").read_text())
        baseline_peak = baseline["coast_direction_spectrum"]["peak_to_mean"]
        candidate_peak = candidate["coast_direction_spectrum"]["peak_to_mean"]
        own_baseline_ok = candidate_peak <= baseline_peak
        topology_ok = (
            abs(candidate["land_share"] - 0.24) <= 0.0002
            and candidate["continent_count"] >= 3
            and candidate["largest_mass_land_share"] < 0.55
            and candidate["dry_land_share"] < 0.25
            and (seed != "Hesperia-01" or frequency != 139
                 or candidate["islands_under_20"] == 34)
        )
        spectrum_ok &= own_baseline_ok
        worldgen_ok &= topology_ok
        spectra.append((seed, frequency, baseline_peak, candidate_peak,
                        own_baseline_ok, topology_ok, candidate))

candidate_max_rss = max(run["rss_kb"] for run in candidate_runs)
memory_ok = candidate_max_rss <= 330 * 1024
baseline_times = [run["seconds"] for run in baseline_runs]
candidate_times = [run["seconds"] for run in candidate_runs]
time_ok = statistics.median(candidate_times) <= statistics.median(baseline_times) * 1.10

lines = [
    "# Hesperia Linux benchmark",
    "",
    f"- Runner: `{os.environ['RUNNER_NAME_TEXT']}` / `{os.environ['RUNNER_OS_TEXT']}` / `{os.environ['RUNNER_ARCH_TEXT']}`",
    f"- Kernel: `{os.environ['KERNEL_TEXT']}`",
    f"- CPU: `{os.environ['CPU_TEXT']}`",
    f"- RAM available: `{os.environ['RAM_TEXT']}`",
    f"- Image ID: `{os.environ['IMAGE_ID_TEXT']}`",
    f"- Base image digest: `{os.environ['BASE_DIGEST_TEXT']}`",
    f"- Baseline commit: `{os.environ['BASELINE_SHA']}`",
    f"- Candidate commit: `{os.environ['CANDIDATE_SHA']}`",
    "",
    "## Timed clean processes (Hesperia-01, f=139)",
    "",
    "| variant | run | generation seconds | maximum RSS KiB |",
    "|---|---:|---:|---:|",
]
for kind, runs in (("baseline", baseline_runs), ("candidate", candidate_runs)):
    for index, run in enumerate(runs, 1):
        suffix = " (cold start)" if index == 1 else ""
        lines.append(f"| {kind} | {index}{suffix} | {run['seconds']:.6f} | {run['rss_kb']} |")
lines += [
    "",
    "| variant | median seconds | maximum seconds | maximum RSS MiB |",
    "|---|---:|---:|---:|",
    f"| baseline | {statistics.median(baseline_times):.6f} | {max(baseline_times):.6f} | {max(r['rss_kb'] for r in baseline_runs)/1024:.2f} |",
    f"| candidate | {statistics.median(candidate_times):.6f} | {max(candidate_times):.6f} | {candidate_max_rss/1024:.2f} |",
    "",
    "## World and directional spectrum",
    "",
    "Contract: `1.667` is the Hesperia-01 v3 baseline, not a universal cross-seed ceiling. "
    "Each candidate seed must be no worse than its own v3 baseline at the same frequency.",
    "",
    "| seed | f | baseline peak/mean | candidate peak/mean | spectrum | land | continents | largest | dry | islands <20 | world |",
    "|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---|",
]
for seed, frequency, baseline_peak, candidate_peak, spectral, topology, data in spectra:
    lines.append(
        f"| {seed} | {frequency} | {baseline_peak:.6f} | {candidate_peak:.6f} | "
        f"{'PASS' if spectral else 'FAIL'} | {data['land_share']:.6f} | "
        f"{data['continent_count']} | {data['largest_mass_land_share']:.6f} | "
        f"{data['dry_land_share']:.6f} | {data['islands_under_20']} | "
        f"{'PASS' if topology else 'FAIL'} |"
    )
lines += [
    "",
    "## Verdicts",
    "",
    f"- Memory (`<=330 MiB`): **{'PASS' if memory_ok else 'FAIL'}**",
    f"- Time (candidate median `<=110%` baseline median): **{'PASS' if time_ok else 'FAIL'}**",
    f"- Worldgen constraints: **{'PASS' if worldgen_ok else 'FAIL'}**",
    f"- Spectrum versus own seed baseline: **{'PASS' if spectrum_ok else 'FAIL'}**",
]
(root / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
if not memory_ok:
    raise SystemExit("candidate RSS exceeded 330 MiB")
