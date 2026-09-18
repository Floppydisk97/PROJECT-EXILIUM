"""Generate a machine-readable Hesperia measurement report without persisting a map."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import threading
import time
from pathlib import Path

from app import worldgen
from app.worldmetrics import measure


class _PeakRss:
    def __init__(self):
        self.peak = 0
        self.stop = threading.Event()

    @staticmethod
    def current() -> int:
        if os.name != "nt":
            import resource
            return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = (ctypes.c_void_p, ctypes.POINTER(Counters),
                                               ctypes.c_ulong)
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        if not psapi.GetProcessMemoryInfo(
                kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(counters.WorkingSetSize)

    def sample(self):
        while not self.stop.is_set():
            self.peak = max(self.peak, self.current())
            self.stop.wait(0.02)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("seed")
    parser.add_argument("--frequency", type=int, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reports = []
    for frequency in args.frequency:
        rss = _PeakRss()
        sampler = threading.Thread(target=rss.sample, daemon=True)
        start = time.perf_counter()
        sampler.start()
        world = worldgen.generate(args.seed, frequency)
        elapsed = time.perf_counter() - start
        rss.stop.set(); sampler.join()
        result = measure(world)
        result.update({"seed": args.seed, "frequency": frequency,
                       "generation_seconds": round(elapsed, 3),
                       "peak_rss_mb": round(rss.peak / 1024 / 1024, 1),
                       "generator_version": worldgen.GENERATOR_VERSION})
        reports.append(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"runs": reports}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "runs": reports}, indent=2))


if __name__ == "__main__":
    main()
