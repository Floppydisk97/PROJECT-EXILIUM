from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path


def load(path: str):
    spec = importlib.util.spec_from_file_location("measured_worldgen", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


parser = argparse.ArgumentParser()
parser.add_argument("--module", required=True)
parser.add_argument("--seed", required=True)
parser.add_argument("--frequency", required=True, type=int)
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()

worldgen = load(args.module)
from worldmetrics import measure

started = time.perf_counter()
world = worldgen.generate(args.seed, args.frequency)
generation_seconds = time.perf_counter() - started
result = measure(world)
result.update({
    "seed": args.seed,
    "frequency": args.frequency,
    "generation_seconds": round(generation_seconds, 6),
    "generator_version": worldgen.GENERATOR_VERSION,
})
args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps({
    "seed": args.seed,
    "frequency": args.frequency,
    "generation_seconds": result["generation_seconds"],
    "land_share": result["land_share"],
    "largest_mass_land_share": result["largest_mass_land_share"],
    "islands_under_20": result["islands_under_20"],
    "peak_to_mean": result["coast_direction_spectrum"]["peak_to_mean"],
}))
