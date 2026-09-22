"""L'istantanea che il client Godot mostra dice ancora quel che il server manda.

QUAL E' IL BUCO CHE QUESTO CHIUDE. `client/tests/city.sample.json` e' una risposta VERA di
`read_city`, presa una volta e messa nel repository: serve allo schermo della citta' per
mostrarsi senza un server acceso, e a `client/tests/run.gd` per provare che il client legge i
campi giusti.

Ma un'istantanea invecchia in silenzio. Il client si confronta col file; nessuno guardava se
il file dice ancora quel che il server fa. Bastava aggiungere un campo a `read_city` -- o
togliercene uno -- e il client restava verde contro una risposta che il server non manda piu',
cioe' contro una fotografia del passato. E' il settimo modo in cui questo progetto ha gia'
avuto due copie che si giuravano uguali.

Da qui il cerchio si chiude: server -> istantanea (qui), istantanea -> GDScript
(`client/tests/run.gd`).

Si confrontano i NOMI dei campi e non i valori: i valori di questa citta' sono una situazione
particolare, scelta perche' mostra tutti e tre gli stati dello stallo, e non c'e' ragione
perche' restino uguali. La forma della risposta si'.
"""
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.db import transaction
from app.service import provision, read_city

SAMPLE = Path(__file__).parents[2] / "client" / "tests" / "city.sample.json"

RIGENERA = (
    "La forma della risposta di `read_city` e' cambiata. Rifai l'istantanea "
    f"({SAMPLE.relative_to(Path(__file__).parents[2])}) da un server vero e rimettila nel commit."
)


def committed() -> dict:
    assert SAMPLE.exists(), f"istantanea mancante: {SAMPLE}"
    return json.loads(SAMPLE.read_text())["city"]


@pytest.mark.repo
def test_the_sample_says_what_it_came_from():
    """Un'istantanea senza provenienza e' un file che nessuno sa piu' se aggiornare."""
    whole = json.loads(SAMPLE.read_text())
    assert "_" in whole and "read_city" in whole["_"], (
        "l'istantanea non dice da dove viene: senza quella riga, fra sei mesi nessuno sa se "
        "e' una risposta vera o una scritta a mano"
    )


def test_the_sample_has_the_fields_the_server_sends_today(database):
    """I nomi dei campi dell'istantanea e quelli di una risposta di adesso, gli stessi.

    Una citta' appena fondata basta: i campi che `read_city` mette nel dizionario non
    dipendono da quanto e' avanti la partita, e cio' che cambia sono i valori, che qui non si
    guardano.
    """
    with transaction() as conn:
        made = provision(conn, "Campione")
        now = read_city(conn, made["city_id"], made["player_id"])

    old = committed()
    assert set(now) == set(old), (
        f"{RIGENERA}\n  in piu' nel server: {sorted(set(now) - set(old))}"
        f"\n  solo nell'istantanea: {sorted(set(old) - set(now))}"
    )

    # E anche dentro le parti annidate che lo schermo apre: un `catalogue` che perde `label`
    # e' uno schermo che mostra `windfarm` al posto di `Eolico`, e nient'altro se ne accorge.
    for entry in now["catalogue"].values():
        first_old = next(iter(old["catalogue"].values()))
        assert set(entry) == set(first_old), (
            f"{RIGENERA}\n  una voce del catalogo e' cambiata di forma:"
            f"\n  in piu' nel server: {sorted(set(entry) - set(first_old))}"
            f"\n  solo nell'istantanea: {sorted(set(first_old) - set(entry))}"
        )

    assert set(now["site_power"]) == set(old["site_power"]), RIGENERA
    assert set(now["stock_milli"]) == set(old["stock_milli"]), RIGENERA
    assert set(now["stalls_in_seconds"]) == set(old["stalls_in_seconds"]), RIGENERA
