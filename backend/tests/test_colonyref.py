"""Il riferimento dice davvero quel che Python genera oggi.

QUAL E' IL BUCO CHE QUESTO CHIUDE. Il terreno di una colonia si genera in tre lingue --
Python sul server, TypeScript nel browser, GDScript nel client -- e le tre devono dare le
stesse celle. L'accordo non si assume: `app.colonyref` scrive `frontend/app/colony/
reference.json` e gli altri due si confrontano con quello, cella per cella.

Ma il confronto e' a stella, non a cerchio. TypeScript e GDScript guardano il FILE; nessuno
guardava se il file dice ancora quel che Python fa. Quindi bastava cambiare una regola in
`citygen.py` e dimenticarsi di rilanciare `python -m app.colonyref`: i due gemelli
continuavano a combaciare col file vecchio, tutto restava verde, e intanto avevano smesso di
combaciare con Python -- cioe' con l'unica copia che decide davvero, perche' e' quella che
gira sul server quando si atterra.

E' esattamente il modo in cui questo progetto si e' gia' fatto male sette volte, seduto sulla
radice della fiducia fra le tre copie. Da qui il cerchio si chiude: Python -> file (qui),
file -> TypeScript (`citygen.test.ts`), file -> GDScript (`client/tests/run.gd`).
"""
import dataclasses
import json
from pathlib import Path

import pytest

from app import citygen, colonyref

pytestmark = pytest.mark.repo      # legge frontend/, che nell'immagine di prova non c'e'

RIGENERA = "Rilancia `python -m app.colonyref` e rimetti il file nel commit."


def committed() -> dict:
    path = Path(__file__).parents[2] / colonyref.OUT
    assert path.exists(), f"riferimento mancante: {path}"
    return json.loads(path.read_text())


def test_the_committed_reference_is_what_python_generates_today():
    """Il file nel repository e quel che `colonyref.build()` produce adesso sono la stessa cosa.

    Se cade, non e' il generatore a essere rotto: e' il file a essere vecchio. Ma finche' e'
    vecchio, il verde di `citygen.test.ts` e di `run.gd` non vuol dire niente -- stanno
    confrontandosi con un pianeta che Python non fa piu'.
    """
    fresh = colonyref.build()
    stored = committed()

    assert stored["size"] == fresh["size"], f"la dimensione del riferimento e' cambiata. {RIGENERA}"
    assert [c["name"] for c in stored["cases"]] == [c["name"] for c in fresh["cases"]], \
        f"i siti del riferimento sono cambiati. {RIGENERA}"

    for mine, theirs in zip(fresh["cases"], stored["cases"]):
        assert mine["site"] == theirs["site"], f"il sito '{mine['name']}' e' cambiato. {RIGENERA}"
        for column in ("ground", "height", "fertility", "vegetation"):
            # Non `assert a == b`: a quattromila celle un fallimento direbbe solo "due elenchi
            # lunghi sono diversi". La PRIMA cella diversa dice dove guardare.
            if mine[column] != theirs[column]:
                where = next(i for i, (a, b) in enumerate(zip(mine[column], theirs[column]))
                             if a != b)
                pytest.fail(
                    f"'{mine['name']}' / {column}: la cella {where} vale {mine[column][where]} "
                    f"adesso e {theirs[column][where]} nel file. {RIGENERA}")
        assert mine["buildable"] == theirs["buildable"], f"'{mine['name']}' edificabili. {RIGENERA}"
        assert mine["economy"] == theirs["economy"], f"'{mine['name']}' economia. {RIGENERA}"

    assert fresh["seeds"] == stored["seeds"], f"i semi sono cambiati. {RIGENERA}"


def test_the_reference_carries_every_number_the_economy_has():
    """Se si aggiunge un campo a `SiteEconomy`, il riferimento deve portarselo dietro.

    E' gia' successo il contrario: le quattro attitudini energetiche sono state aggiunte a
    Python e il riferimento ha continuato a scriverne sei, quindi le due lingue sono divergute
    mentre il test che esiste per accorgersene passava. Da allora `colonyref` usa `asdict`
    invece di un elenco scritto a mano, e questo verifica che continui a farlo.
    """
    expected = {field.name for field in dataclasses.fields(citygen.SiteEconomy)}
    for case in colonyref.build()["cases"]:
        assert set(case["economy"]) == expected, (
            f"'{case['name']}': il riferimento scrive {sorted(case['economy'])}, "
            f"l'economia ha {sorted(expected)}")


def test_the_reference_carries_every_fact_about_a_site():
    """Stessa trappola, dall'altra parte: un campo nuovo in `Site` che il riferimento non
    scrive lascerebbe i gemelli a generare da un sito incompleto -- e a generarlo uguale fra
    loro, quindi verdi, e diverso da quel che il server genera."""
    expected = {field.name for field in dataclasses.fields(citygen.Site)}
    for case in colonyref.build()["cases"]:
        assert set(case["site"]) == expected, (
            f"'{case['name']}': il riferimento scrive {sorted(case['site'])}, "
            f"un sito ha {sorted(expected)}")


def test_the_reference_still_covers_the_branches_that_differ():
    """Cinque prati identici passerebbero qualunque cosa facesse il generatore.

    `citygen.test.ts` lo verifica sul file; qui si verifica su quel che `colonyref` PRODUCE,
    cosi' chi cambia l'elenco dei siti se ne accorge prima di rigenerare invece che dopo.
    """
    cases = colonyref.build()["cases"]
    assert len({c["site"]["biome"] for c in cases}) >= 4
    assert any(c["site"]["river_flow"] > 0 for c in cases)
    assert any(c["site"]["coastal"] for c in cases)
    assert any(c["site"]["temperature"] < -8 for c in cases)      # il ramo del gelo
