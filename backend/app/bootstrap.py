"""La prima colonia di un mondo appena messo online.

Un giocatore nasce da `app.cli`, che e' amministrazione locale e non ha mai avuto una rotta
HTTP: e' la ragione per cui rendere pubblico il repository non ha aperto niente a nessuno.
Ma su un'istanza del piano gratuito non esiste una shell, quindi quel comando li' dentro non
si puo' lanciare, e un mondo online senza un solo giocatore non si puo' provare.

Questo e' quel comando, eseguito UNA volta all'avvio e solo quando qualcuno lo chiede con una
variabile d'ambiente che puo' scrivere il proprietario del servizio.

Le due guardie che lo rendono innocuo, e sono guardie e non cortesie:

  - senza `BOOTSTRAP_COLONY` non fa assolutamente niente;
  - se esiste GIA' un giocatore, si rifiuta. Non e' un modo di coniare token a ripetizione:
    e' il primo, e uno solo. Il secondo si fa dalla riga di comando, come tutti gli altri.

Il token finisce nei log del servizio, che nel piano gratuito sono l'unica superficie da cui
il proprietario puo' leggerlo. Sono privati del workspace; la variabile va tolta dopo.
"""
import json
import logging
import os

from app.db import transaction
from app.service import provision
from app.worldreset import soft_reset

logger = logging.getLogger("exilium.bootstrap")


def reset_world_if_asked() -> str:
    """Azzera la partita se `RESET_WORLD` porta una parola non ancora onorata.

    Idempotente di proposito, e la ragione e' concreta: una variabile si dimentica addosso a
    un servizio, e un'istanza gratuita si riavvia da sola a ogni risveglio. Senza memoria di
    cio' che e' gia' stato fatto, il mondo sparirebbe ogni notte. La stessa parola non fa
    niente due volte; per azzerare di nuovo se ne cambia una.
    """
    token = (os.getenv("RESET_WORLD") or "").strip()
    if not token:
        return "disabled"
    with transaction() as conn:
        done = conn.execute("SELECT last_reset_token FROM world WHERE id = 1").fetchone()
        if done and done["last_reset_token"] == token:
            return "already_done"
        soft_reset(conn)
        conn.execute("UPDATE world SET last_reset_token = %s WHERE id = 1", (token,))
    return "reset"


def bootstrap_first_colony() -> str:
    """Conia la prima colonia se richiesto. Restituisce cosa e' stato fatto, per i log."""
    name = (os.getenv("BOOTSTRAP_COLONY") or "").strip()
    if not name:
        return "disabled"
    with transaction() as conn:
        existing = conn.execute("SELECT count(*) AS n FROM players").fetchone()["n"]
        if existing:
            # Non un errore: il mondo ha gia' un proprietario, e questa e' esattamente la
            # condizione in cui non si deve fare niente.
            return "already_populated"
        result = provision(conn, name)
    # Una riga sola, come tutto cio' che questo servizio scrive: si legge dalla dashboard.
    logger.warning(
        "PRIMA COLONIA CREATA -- %s",
        json.dumps({"city": name, "city_id": str(result["city_id"]), "token": result["token"]}),
    )
    return "provisioned"
