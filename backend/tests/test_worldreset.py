"""Il soft reset: via le colonie, resta il pianeta.

Le tre cose che contano, e nessuna e' "non si rompe": che cancelli DAVVERO cio' che tre
guardie del mondo impediscono di cancellare, che NON tocchi la geografia -- il pianeta costa
minuti di CPU e non si rigenera per sbaglio -- e che dopo il mondo sia di nuovo giocabile,
non solo vuoto.
"""
from uuid import uuid4

import psycopg
import pytest

from app.db import transaction
from app.mapservice import generate_and_store
from app.service import land, provision, read_city, start_upgrade
from app.worldreset import soft_reset


def count(conn, table) -> int:
    return conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]


def a_played_world():
    """Un mondo con dentro una partita vera: pianeta, giocatore, colonia a terra, un impegno."""
    with transaction() as conn:
        generate_and_store(conn, "Church", frequency=6)
        player = provision(conn, "Da cancellare")
        tile = conn.execute(
            "SELECT id FROM world_tiles WHERE elevation >= 0 AND biome <> 'ocean' LIMIT 1"
        ).fetchone()["id"]
        land(conn, player["city_id"], player["player_id"], tile)
        start_upgrade(conn, player["city_id"], player["player_id"], uuid4())
    return player


def test_it_removes_what_the_world_itself_refuses_to_remove(database):
    a_played_world()
    with transaction() as conn:
        assert count(conn, "cities") == 1 and count(conn, "resource_ledger") > 0
        assert count(conn, "orders") == 1
        removed = soft_reset(conn)
    assert removed["cities"] == 1 and removed["players"] == 1
    assert removed["resource_ledger"] > 0
    with transaction() as conn:
        for table in ("orders", "city_works", "city_stock", "resource_ledger", "cities", "players"):
            assert count(conn, table) == 0, table


def test_the_planet_survives(database):
    a_played_world()
    with transaction() as conn:
        tiles_before = count(conn, "world_tiles")
        assert tiles_before > 0
        soft_reset(conn)
    with transaction() as conn:
        # La geografia e' immutabile e costa minuti di CPU: un reset della PARTITA non la tocca.
        assert count(conn, "world_tiles") == tiles_before
        assert count(conn, "world_map") == 1
        assert count(conn, "world") == 1


def test_the_world_is_playable_again_and_not_merely_empty(database):
    """La prova che vale davvero: si riparte. Un mondo svuotato male resta svuotato e basta --
    senza un periodo di politica aperto, la prima colonia nuova verrebbe liquidata su un
    intervallo che nessun periodo copre, e quel caso e' rifiutato."""
    first = a_played_world()
    with transaction() as conn:
        tile = conn.execute("SELECT tile_id FROM cities WHERE id = %s",
                            (first["city_id"],)).fetchone()["tile_id"]
        soft_reset(conn)
    with transaction() as conn:
        assert count(conn, "policy_periods") == 1
        again = provision(conn, "Seconda vita")
        # E la casella di prima e' libera: era occupata per sempre da un vincolo di unicita'.
        land(conn, again["city_id"], again["player_id"], tile)
        view = read_city(conn, again["city_id"], again["player_id"])
    assert view["level"] == 0 and view["stock_milli"]


def test_the_ledger_is_immutable_again_afterwards(database):
    """Il trigger viene spento di proposito per la durata del reset. Se restasse spento, il
    ledger smetterebbe di essere la fonte di verita' immutabile su cui regge tutto il resto --
    e sarebbe un difetto invisibile: tutto continuerebbe a funzionare, finche' qualcuno non
    riscrive il passato."""
    a_played_world()
    with transaction() as conn:
        soft_reset(conn)
    with transaction() as conn:
        after = provision(conn, "Dopo il reset")
    with pytest.raises(psycopg.errors.CheckViolation), transaction() as conn:
        conn.execute("DELETE FROM resource_ledger WHERE city_id = %s", (after["city_id"],))


def test_the_online_trigger_is_idempotent(database, monkeypatch):
    """La guardia che conta davvero.

    Una variabile d'ambiente si dimentica addosso a un servizio, e un'istanza gratuita si
    riavvia da sola ogni volta che si risveglia. Senza memoria di cio' che e' gia' stato
    fatto, il mondo verrebbe azzerato a ogni risveglio -- e nessuno capirebbe perche' la
    colonia sparisce di notte.
    """
    from app.bootstrap import reset_world_if_asked

    monkeypatch.delenv("RESET_WORLD", raising=False)
    a_played_world()
    assert reset_world_if_asked() == "disabled"
    with transaction() as conn:
        assert count(conn, "cities") == 1, "senza la variabile non deve succedere niente"

    monkeypatch.setenv("RESET_WORLD", "ricomincio-da-qui")
    assert reset_world_if_asked() == "reset"
    with transaction() as conn:
        assert count(conn, "cities") == 0

    # Il riavvio successivo, con la variabile ancora li'.
    with transaction() as conn:
        again = provision(conn, "Nata dopo")
    assert reset_world_if_asked() == "already_done"
    with transaction() as conn:
        assert count(conn, "cities") == 1, "la stessa parola NON deve azzerare due volte"
        assert conn.execute("SELECT name FROM cities").fetchone()["name"] == "Nata dopo"
    assert again

    # Per azzerare di nuovo si cambia parola: e' una scelta, non un riavvio.
    monkeypatch.setenv("RESET_WORLD", "e-adesso-di-nuovo")
    assert reset_world_if_asked() == "reset"
    with transaction() as conn:
        assert count(conn, "cities") == 0
