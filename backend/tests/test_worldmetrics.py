import math

from app import worldgen
from app.worldmetrics import measure


def test_metrics_partition_land_and_measure_local_coast_directions():
    world = worldgen.generate("metrics", frequency=8)
    report = measure(world)
    assert sum(mass["area"] for mass in report["masses"]) == report["land_tiles"]
    assert report["mass_count"] == len(report["masses"])
    assert all(mass["perimeter"] >= 0 for mass in report["masses"])
    assert all(math.isclose(mass["perimeter_per_sqrt_area"],
                            mass["perimeter"] / math.sqrt(mass["area"]), abs_tol=1e-6)
               for mass in report["masses"])
    spectrum = report["coast_direction_spectrum"]
    assert len(spectrum["bin_shares"]) == 18
    assert math.isclose(sum(spectrum["bin_shares"]), 1.0, abs_tol=1e-5)
    assert set(spectrum["harmonic_magnitudes"]) == {"2", "4", "6", "8"}
    assert 0 <= report["thin_land_share"] <= 1
