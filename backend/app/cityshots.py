"""Review images of a colony's ground, without a browser and without a dependency.

A generator you cannot look at is a generator you are guessing about. `worldshots` does this
for the planet; this does it for the square of ground a landing opens. PNG is written by hand
here -- it is about thirty lines of zlib and a CRC, which is cheaper than a dependency and
means a review image can always be made, anywhere.
"""
from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path

from app.citygen import BIOME_RULES, GROUNDS, Site, generate

COLORS = {
    "deep_water": (18, 52, 86), "water": (38, 92, 134), "marsh": (74, 96, 72),
    "sand": (214, 192, 140), "soil": (108, 88, 62), "gravel": (140, 134, 118),
    "rock": (118, 114, 106), "ice": (226, 236, 242),
}
# A saturated green, because a review image has to make a band of vegetation VISIBLE. A
# thirty-per-cent blend toward a dark forest green just makes sand look dull, and the fertile
# strip along a desert river -- the entire reason to land there -- disappeared into the sand
# even though the data had it. The mix stays proportional: only the endpoint changed.
VEGETATION = (58, 138, 52)


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))


def write_png(path: Path, width: int, height: int, pixels: bytes) -> None:
    """Truecolour, 8 bits, one filter byte per row. `pixels` is width*height*3 bytes."""
    raw = b"".join(
        b"\x00" + pixels[y * width * 3:(y + 1) * width * 3] for y in range(height)
    )
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def render(city_map, scale: int = 4) -> tuple[int, bytes]:
    """The map as pixels. Ground gives the colour, vegetation darkens it toward green, and
    relief shades it, so a picture shows the three things a colonist would care about."""
    size = city_map.size
    highest = max(1, max(abs(h) for h in city_map.height))
    row_bytes = bytearray()
    rows: list[bytes] = []
    for y in range(size):
        row_bytes.clear()
        for x in range(size):
            i = y * size + x
            r, g, b = COLORS[GROUNDS[city_map.ground[i]]]
            green = city_map.vegetation[i] / 100.0
            r = r + (VEGETATION[0] - r) * green
            g = g + (VEGETATION[1] - g) * green
            b = b + (VEGETATION[2] - b) * green
            shade = 0.82 + 0.36 * (city_map.height[i] / highest)
            row_bytes += bytes(
                max(0, min(255, int(channel * shade))) for channel in (r, g, b)
            )
        rows.append(bytes(row_bytes) * 1)
    wide = b"".join(
        b"".join(row[x * 3:(x + 1) * 3] * scale for x in range(size)) for row in rows
        for _ in range(scale)
    )
    return size * scale, wide


def main() -> None:
    parser = argparse.ArgumentParser(description="Render review images of colony ground.")
    parser.add_argument("--out", type=Path, default=Path("artifacts/colonies"))
    parser.add_argument("--seed", default="review")
    parser.add_argument("--scale", type=int, default=4)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    # One of each biome a colony can actually land on, plus the two cases that change the
    # ground more than the biome does: a river, and a coast.
    sites = [(name, Site(name, 400, 12.0, 900, 0, False)) for name in sorted(BIOME_RULES)]
    sites += [
        ("temperate_forest+fiume", Site("temperate_forest", 220, 12.0, 1100, 4200, False)),
        ("temperate_forest+costa", Site("temperate_forest", 90, 13.0, 1000, 0, True)),
        ("desert+fiume", Site("desert", 300, 31.0, 90, 3100, False)),
    ]
    for name, site in sites:
        city_map = generate(f"{args.seed}:{name}", site)
        width, pixels = render(city_map, args.scale)
        write_png(args.out / f"{name}.png", width, width, pixels)
        print(f"{name:<26} edificabili {city_map.buildable:>6}  "
              f"fertilita' media {sum(city_map.fertility) // len(city_map.fertility):>3}")


if __name__ == "__main__":
    main()
