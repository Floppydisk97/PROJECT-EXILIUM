"""Il soft reset: via le colonie, resta il pianeta.

Atterrare e' definitivo, e non per caso: tre guardie indipendenti lo impediscono -- la chiave
esterna dal ledger, il trigger che rende il ledger immutabile, e il vincolo che una colonia a
terra non si sposta. Sono regole del MONDO, e vanno lasciate dove sono.

Questa e' un'operazione di AMMINISTRAZIONE, che sta fuori dal mondo come lo sta cancellare un
salvataggio. Toglie tutto cio' che e' stato giocato -- giocatori, colonie, ordini, impianti,
scorte e ledger -- e lascia in piedi la geografia e l'orologio. Il pianeta e' immutabile e
costa minuti di CPU: rigenerarlo sarebbe un'altra cosa, e non e' questa.

Per farlo deve disattivare di proposito il trigger di immutabilita' del ledger. E' la stessa
cosa che fa `pg_restore --disable-triggers` in `scripts/restore.sh`, e per la stessa ragione:
un archivio che si ricarica, o un mondo che si azzera, non sono modifiche di un fatto passato.
"""
import logging

logger = logging.getLogger("exilium.reset")

# L'ordine conta: ogni tabella prima di quella a cui punta. Le chiavi esterne sono NO ACTION
# di proposito -- niente cancellate a cascata di nascosto -- quindi l'ordine e' esplicito qui.
WIPED = ("orders", "city_works", "city_stock", "resource_ledger", "cities", "players")

# E queste NON si toccano: sono il mondo, non la partita.
KEPT = ("world", "world_map", "world_tiles", "alembic_version")


def soft_reset(conn) -> dict[str, int]:
    """Azzera la partita e lascia il pianeta. Restituisce quante righe sono sparite per tabella."""
    removed: dict[str, int] = {}
    # Il ledger e' immutabile per trigger: qui lo si spegne per il tempo di una transazione,
    # dichiaratamente. Se qualcosa va storto nel mezzo, il rollback lo riporta com'era.
    conn.execute("ALTER TABLE resource_ledger DISABLE TRIGGER ledger_immutable")
    try:
        for table in WIPED:
            deleted = conn.execute(f"DELETE FROM {table}").rowcount
            removed[table] = deleted
    finally:
        conn.execute("ALTER TABLE resource_ledger ENABLE TRIGGER ledger_immutable")

    # La linea del tempo della politica non puo' restare appesa a periodi che parlano di
    # citta' che non esistono piu': si ricomincia da un periodo solo, aperto adesso. Senza,
    # la prima colonia nuova verrebbe liquidata su un intervallo che nessun periodo copre --
    # e quel caso e' RIFIUTATO, non pagato come zero.
    conn.execute("DELETE FROM policy_periods")
    conn.execute(
        "INSERT INTO policy_periods (policy, from_at) "
        "VALUES ('balanced', date_trunc('second', clock_timestamp()))"
    )
    logger.warning("MONDO AZZERATO -- righe rimosse: %s", removed)
    return removed
