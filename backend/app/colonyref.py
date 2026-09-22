"""Write the reference the TypeScript twin is held to.

`frontend/app/colony/citygen.ts` e `client/exilium/citygen.gd` sono porti di `citygen.py`, e
definizioni che devono coincidere sono il modo in cui si scrive un difetto silenzioso. Quindi
l'accordo non si assume: questo scrive cinque siti cella per cella, e le altre due copie li
rigenerano nella loro lingua e confrontano -- `citygen.test.ts` nel browser, `tests/run.gd`
dentro Godot senza finestra. Una cella di scarto fa cadere la build.

Il file di riferimento e' UNO. Le tre copie lo leggono tutte da qui; farne una seconda per
comodita' di un progetto sarebbe esattamente il difetto che questo file esiste per impedire.

    python -m app.colonyref

Va rilanciato ogni volta che una regola di `citygen.py` cambia -- e se ne e' cambiata una
sola delle tre, ci si aspetta che le altre cadano per prime. Quella caduta e' il mestiere di
questo file.

Sixty-four cells a side, not the real 768: the reference exists to catch a rule that differs,
and a rule that differs differs in the first thousand cells. At full size the fixture would be
forty megabytes and nobody would regenerate it.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from app.citygen import GROUND_COLORS, GROUNDS, PALETTE, Site, generate, seed_for

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
            # I numeri economici viaggiano col riferimento: sono cio' che il visore PROMETTE
            # prima di un atterraggio e cio' che il server scrive dopo. Se le due copie li
            # calcolassero diversamente, il sito pesato e quello preso non sarebbero lo stesso
            # -- e ogni confronto cella per cella continuerebbe a passare.
            #
            # `asdict` e non un elenco scritto a mano: un elenco si dimentica. E' successo --
            # le quattro attitudini energetiche sono state aggiunte a Python e il riferimento
            # ha continuato a scriverne sei, quindi le due lingue sono divergute mentre il
            # test che esiste per accorgersene passava. Cosi' invece aggiungere un campo di
            # qua ROMPE subito il test di la', che e' esattamente il suo mestiere.
            "economy": asdict(made.economy),
        })
    seeds = [{"world": world, "tile": tile, "seed": seed_for(world, tile)}
             for world, tile in SEEDS]
    return {
        "size": SIZE, "cases": cases, "seeds": seeds,
        # Le tinte del terreno viaggiano col riferimento: e' l'unica cosa che tutte e tre le
        # lingue leggono, quindi e' il posto giusto per tenere d'accordo le loro tavolozze.
        "ground_colors": [GROUND_COLORS[name] for name in GROUNDS],
        "palette": dict(PALETTE),
    }


def main() -> None:
    out = OUT if OUT.parent.exists() else Path("..") / OUT
    # Compact: 205 KB instead of 605, and nobody reads it -- the test does.
    text = json.dumps(build(), separators=(",", ":"))
    out.write_text(text, encoding="utf-8")
    print(f"{out} scritto: {len(text) / 1024:.0f} KB, {SIZE}x{SIZE} celle su {len(CASES)} siti")


if __name__ == "__main__":
    main()
