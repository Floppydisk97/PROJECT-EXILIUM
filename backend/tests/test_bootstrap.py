"""La prima colonia di un mondo online.

Quello che va provato non e' che funzioni -- e' `provision`, gia' coperto -- ma che le due
guardie tengano: senza la variabile non succede NIENTE, e con un giocatore gia' dentro non
succede niente lo stesso. Un bootstrap che conia un token a ogni riavvio sarebbe una fabbrica
di proprietari su un mondo condiviso.
"""
from app.bootstrap import bootstrap_first_colony
from app.db import transaction


def players(conn):
    return conn.execute("SELECT count(*) AS n FROM players").fetchone()["n"]


def test_without_the_variable_it_does_nothing(database, monkeypatch):
    monkeypatch.delenv("BOOTSTRAP_COLONY", raising=False)
    assert bootstrap_first_colony() == "disabled"
    with transaction() as conn:
        assert players(conn) == 0


def test_a_blank_name_is_not_a_request(database, monkeypatch):
    # Una variabile impostata a vuoto e' come non impostata: su Render si svuota un campo
    # piu' spesso di quanto lo si cancelli.
    monkeypatch.setenv("BOOTSTRAP_COLONY", "   ")
    assert bootstrap_first_colony() == "disabled"
    with transaction() as conn:
        assert players(conn) == 0


def test_it_mints_exactly_one_colony_and_then_refuses(database, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_COLONY", "Prima colonia")
    assert bootstrap_first_colony() == "provisioned"
    with transaction() as conn:
        assert players(conn) == 1
        name = conn.execute("SELECT name FROM cities").fetchone()["name"]
    assert name == "Prima colonia"

    # Il riavvio successivo -- che su un'istanza gratuita arriva ogni volta che il servizio
    # si risveglia -- non deve coniare un secondo proprietario del mondo.
    assert bootstrap_first_colony() == "already_populated"
    with transaction() as conn:
        assert players(conn) == 1
