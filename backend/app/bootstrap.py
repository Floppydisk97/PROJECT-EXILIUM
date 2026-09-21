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

logger = logging.getLogger("exilium.bootstrap")


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
