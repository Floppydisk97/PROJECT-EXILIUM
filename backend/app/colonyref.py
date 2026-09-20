"""Write the reference the TypeScript twin is held to.

`frontend/app/colony/citygen.ts` is a port of `citygen.py`, and two definitions that must
agree are how a silent bug gets written. So the agreement is not assumed: this writes five
sites cell by cell, and `citygen.test.ts` regenerates them in the browser's language and
compares. A drift of one cell fails the build.

    python -m app.colonyref

Run it whenever a rule in `citygen.py` changes -- and expect the TypeScript side to fail
first if only one of the two was changed. That failure is the whole point of the file.

Sixty-four cells a side, not the real 768: the reference exists to catch a rule that differs,
and a rule that differs differs in the first thousand cells. At full size the fixture would be
forty megabytes and nobody would regenerate it.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.citygen import Site, generate, seed_for

SIZE = 64
OUT = Path("frontend/app/colony/reference.json")

# Five sites chosen for their BRANCHES, not their looks: a river, a desert crossed by a great
# river, a coast with a delta, everything frozen, and bare stone high up. Five identical
# meadows would pass whatever the code did.
CASES: list[tuple[str, Site]] = [
    ("foresta",  Site("temperate_forest",   220,  12.0, 1100,  900, False)),
    ("nilo",     Site("desert",             300,  31.0,   90, 3100, False)),
    ("delta",    Site("tropical_swamp",      40,  26.0, 2400, 2600, True)),
    ("ghiaccio", Site("ice_sheet",          600, -28.0,  150,    0, False)),
    ("roccia",   Site("bare_rock",         2400,  -2.0,  400,    0, True)),
]


# The seed itself crosses the wire between the two copies: the client derives it from the
# world seed and the tile, the server stores what IT derived, and if those two ever differ the
# client draws a place the authoritative map does not have. It was checked only against itself.
SEEDS: list[tuple[str, int]] = [("Erebo-01", 1234), ("Erebo-01", 150000), ("Altrove", 0)]


def build() -> dict:
    cases = []
    for name, site in CASES:
        made = generate(f"ref:{name}", site, SIZE)
        cases.append({
            "name": name,
            "seed": f"ref:{name}",
            "site": {
                "biome": site.biome, "elevation": site.elevation,
                "temperature": site.temperature, "rainfall": site.rainfall,
                "river_flow": site.river_flow, "coastal": site.coastal,
            },
            "ground": list(made.ground),
            "height": list(made.height),
            "fertility": list(made.fertility),
            "vegetation": list(made.vegetation),
            "buildable": made.buildable,
            # The three economic numbers travel with the reference too. They are what the
            # viewer PROMISES before a landing and what the server writes down after it: if
            # the two copies computed them differently, the site you weighed and the site you
            # took would not be the same site, and every cell-for-cell check would still pass.
            "economy": {"food": made.economy.food, "timber": made.economy.timber,
                        "stone": made.economy.stone, "effort": made.economy.effort,
                        "room": made.economy.room},
        })
    seeds = [{"world": world, "tile": tile, "seed": seed_for(world, tile)}
             for world, tile in SEEDS]
    return {"size": SIZE, "cases": cases, "seeds": seeds}


def main() -> None:
    out = OUT if OUT.parent.exists() else Path("..") / OUT
    # Compact: 205 KB instead of 605, and nobody reads it -- the test does.
    text = json.dumps(build(), separators=(",", ":"))
    out.write_text(text, encoding="utf-8")
    print(f"{out} scritto: {len(text) / 1024:.0f} KB, {SIZE}x{SIZE} celle su {len(CASES)} siti")


if __name__ == "__main__":
    main()
