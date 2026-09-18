"""Render deterministic orthographic SVG review views without a browser or projection map."""
from __future__ import annotations

import argparse
import html
import importlib.util
import math
import sys
from pathlib import Path

from app import worldgen

COLORS = {
    "ice_sheet": "#e7f0f5", "snow_cap": "#f4f6f7", "bare_rock": "#77736a",
    "tundra": "#898b75", "boreal_forest": "#355f49", "temperate_forest": "#568247",
    "temperate_swamp": "#477062", "arid_shrubland": "#9c915f", "desert": "#cbb27c",
    "tropical_rainforest": "#34733a", "tropical_swamp": "#3e6852", "lake": "#214c6d",
}
VIEWS = (("view-a", 0.0, 18.0), ("view-b", 120.0, 18.0), ("view-c", 240.0, 18.0))


def _basis(longitude: float, latitude: float):
    lon, lat = math.radians(longitude), math.radians(latitude)
    forward = (math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat))
    east = (-math.sin(lon), math.cos(lon), 0.0)
    north = (-math.sin(lat) * math.cos(lon), -math.sin(lat) * math.sin(lon), math.cos(lat))
    return forward, east, north


def render(world, output: Path, label: str) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for name, longitude, latitude in VIEWS:
        forward, east, north = _basis(longitude, latitude)
        paths = []
        visible = sorted((tile for tile in world.tiles if tile.elevation >= 0
                          and sum(a*b for a, b in zip(tile.center, forward)) > 0),
                         key=lambda tile: sum(a*b for a, b in zip(tile.center, forward)))
        for tile in visible:
            points = []
            for point in tile.polygon:
                x = 600 + 520 * sum(a*b for a, b in zip(point, east))
                y = 600 - 520 * sum(a*b for a, b in zip(point, north))
                points.append(f"{x:.1f},{y:.1f}")
            paths.append(f'<polygon points="{" ".join(points)}" fill="{COLORS.get(tile.biome, "#777")}"/>')
        title = html.escape(f"{label} · {world.seed} · f={world.frequency} · lon {longitude:.0f}°")
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1200" viewBox="0 0 1200 1200">'
               '<rect width="1200" height="1200" fill="#05070d"/>'
               '<circle cx="600" cy="600" r="522" fill="#153a59" stroke="#718ca3" stroke-width="2"/>'
               + "".join(paths)
               + f'<text x="40" y="55" fill="#e2e8f2" font-family="sans-serif" font-size="25">{title}</text>'
               '</svg>')
        (output / f"{name}.svg").write_text(svg, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("seed")
    parser.add_argument("--frequency", type=int, default=60)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--worldgen-file", type=Path)
    args = parser.parse_args()
    generator = worldgen
    if args.worldgen_file:
        spec = importlib.util.spec_from_file_location("review_worldgen", args.worldgen_file)
        generator = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = generator
        spec.loader.exec_module(generator)
    render(generator.generate(args.seed, args.frequency), args.output, args.label)


if __name__ == "__main__":
    main()
