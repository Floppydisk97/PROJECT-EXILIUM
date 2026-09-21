"""Il pianeta come file portatile.

Esiste per rompere un legame: finora il pianeta lo costruiva l'istanza che serve l'API, e
generarlo costa 358 MB misurati su una macchina che ne ha 512. Il pianeta non poteva crescere
perche' la macchina che lo SERVE non aveva la memoria per FARLO -- due cose diverse tenute
insieme da un dettaglio di implementazione.

Quel che questo file deve dimostrare e' una cosa sola, e non e' "il caricamento funziona":
e' che un database riempito dal file e uno riempito dal generatore sono **lo stesso
database**. Se non lo fossero, avremmo due pianeti che si chiamano allo stesso modo -- e di
copie-che-devono-coincidere questo progetto ne ha gia' pagate sette.
"""
from pathlib import Path

import pytest

from app import mapfile, worldgen
from app.db import transaction
from app.mapservice import TILE_COLUMNS, generate_and_store
from app.service import DomainError

SEED = "Prova"
FREQUENCY = 12          # 1442 caselle: abbastanza per coste, fiumi e piu' biomi


@pytest.fixture
def planet_file(tmp_path) -> Path:
    path = tmp_path / "prova.planet.gz"
    mapfile.write(path, SEED, FREQUENCY)
    return path


def snapshot(conn):
    """Tutte le caselle, in ordine, come tuple confrontabili."""
    rows = conn.execute(
        "SELECT {} FROM world_tiles ORDER BY id".format(", ".join(TILE_COLUMNS))
    ).fetchall()
    return [tuple(row[name] for name in TILE_COLUMNS) for row in rows]


def world_row(conn):
    return dict(conn.execute(
        "SELECT name, seed, frequency, sea_level, generator_version FROM world_map WHERE id = 1"
    ).fetchone())


def test_a_loaded_world_is_the_same_world_a_generated_one_is(database, planet_file):
    """La prova che tiene in piedi tutto il resto.

    Si carica, si fotografa, si cancella, si genera, si fotografa di nuovo, e le due
    fotografie devono essere identiche -- casella per casella, colonna per colonna.

    La cancellazione di mezzo spegne i trigger di immutabilita', ed e' lecito qui e solo qui:
    lo schema di questa prova viene distrutto alla fine, e il confronto ha bisogno che le due
    strade riempiano la STESSA tabella vuota. Farlo su un mondo vero sarebbe riscrivere il
    passato, che e' esattamente cio' che quei trigger esistono per impedire.
    """
    with transaction() as conn:
        mapfile.load(conn, planet_file)
        from_file = snapshot(conn)
        file_world = world_row(conn)

    with transaction() as conn:
        conn.execute("ALTER TABLE world_tiles DISABLE TRIGGER world_tiles_immutable")
        conn.execute("ALTER TABLE world_map DISABLE TRIGGER world_map_immutable")
        try:
            conn.execute("DELETE FROM world_tiles")
            conn.execute("DELETE FROM world_map")
        finally:
            conn.execute("ALTER TABLE world_tiles ENABLE TRIGGER world_tiles_immutable")
            conn.execute("ALTER TABLE world_map ENABLE TRIGGER world_map_immutable")

    with transaction() as conn:
        generate_and_store(conn, SEED, FREQUENCY)
        from_generator = snapshot(conn)
        generated_world = world_row(conn)

    assert len(from_file) == len(from_generator) > 1000
    assert file_world == generated_world
    # Non `assert a == b` e basta: a millequattrocento caselle, un fallimento direbbe solo
    # "due elenchi lunghi sono diversi". La prima differenza, invece, dice quale colonna.
    for position, (left, right) in enumerate(zip(from_file, from_generator)):
        if left != right:
            different = [TILE_COLUMNS[i] for i in range(len(TILE_COLUMNS)) if left[i] != right[i]]
            pytest.fail(f"casella in posizione {position}: colonne diverse {different}\n"
                        f"  dal file:       {left}\n  dal generatore: {right}")


def test_the_file_refuses_to_land_on_a_world_that_already_exists(database, planet_file):
    """Il pianeta e' immutabile per regola del gioco. Caricarne un altro sopra non e' una cosa
    che si fa per sbaglio: si fa con una migrazione, dove qualcuno ha guardato."""
    with transaction() as conn:
        mapfile.load(conn, planet_file)
    with transaction() as conn, pytest.raises(DomainError) as refused:
        mapfile.load(conn, planet_file)
    assert refused.value.status == 409


def test_a_truncated_file_leaves_nothing_behind(database, planet_file, tmp_path):
    """Un file interrotto a meta' non deve lasciare mezzo pianeta.

    E' il caso che capita davvero: un dump finito male, una copia interrotta. Il sigillo sta
    in fondo apposta -- chi scrive non puo' saperlo prima -- e chi legge lo verifica DENTRO
    la transazione, quindi o entra tutto o non entra niente.
    """
    import gzip
    whole = gzip.open(planet_file, "rt", encoding="utf-8").read().splitlines()
    cut = tmp_path / "troncato.planet.gz"
    with gzip.open(cut, "wt", encoding="utf-8") as out:
        out.write("\n".join(whole[:-1]) + "\n")      # via il sigillo

    with pytest.raises(DomainError) as refused:
        with transaction() as conn:
            mapfile.load(conn, cut)
    assert refused.value.status == 422
    with transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM world_tiles").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM world_map").fetchone()["n"] == 0


def test_a_corrupt_file_is_refused_even_if_it_is_complete(database, planet_file, tmp_path):
    """Un file intero ma con una casella cambiata. Senza il sigillo passerebbe: il conto delle
    caselle tornerebbe, e nessuno guarda 1442 righe a mano."""
    import gzip
    lines = gzip.open(planet_file, "rt", encoding="utf-8").read().splitlines()
    # La riga 5 e' una casella qualunque; che sia oceano e' un fatto di QUESTO seme, non una
    # legge. Senza questa verifica, il giorno in cui quella casella diventa un deserto la
    # sostituzione non fa niente, il file resta valido, e il test fallisce dicendo la cosa
    # sbagliata -- oppure, peggio, smette di provare qualcosa senza che nessuno lo noti.
    changed = lines[5].replace('"ocean"', '"desert"', 1)
    assert changed != lines[5], "la casella campione non e' piu' oceano: scegline un'altra"
    lines[5] = changed
    broken = tmp_path / "corrotto.planet.gz"
    with gzip.open(broken, "wt", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")

    with pytest.raises(DomainError) as refused:
        with transaction() as conn:
            mapfile.load(conn, broken)
    assert "corrupt" in str(refused.value).lower() or refused.value.status == 422
    with transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM world_tiles").fetchone()["n"] == 0


def test_a_file_written_for_other_columns_is_refused(database, planet_file, tmp_path):
    """Il caso peggiore: un file vecchio, scritto quando una casella aveva altre colonne.
    Caricarlo riempirebbe le colonne sbagliate con valori giusti -- nessun errore, e un
    pianeta storto. L'intestazione porta l'elenco delle colonne proprio per questo."""
    import gzip
    import json
    lines = gzip.open(planet_file, "rt", encoding="utf-8").read().splitlines()
    header = json.loads(lines[0])
    header["columns"] = list(header["columns"])[:-1]
    lines[0] = json.dumps(header, separators=(",", ":"))
    stale = tmp_path / "vecchio.planet.gz"
    with gzip.open(stale, "wt", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")

    with pytest.raises(DomainError) as refused:
        with transaction() as conn:
            mapfile.load(conn, stale)
    assert refused.value.status == 422


def test_the_header_says_which_planet_this_is(planet_file):
    """Il file si descrive da solo: nome, seme, frequenza, versione del generatore. E' quel
    che permette di sapere che pianeta si ha in mano senza caricarlo da nessuna parte."""
    import gzip
    import json
    header = json.loads(gzip.open(planet_file, "rt", encoding="utf-8").readline())
    assert header["format"] == mapfile.FORMAT
    assert header["seed"] == SEED
    assert header["frequency"] == FREQUENCY
    assert header["generator_version"] == worldgen.GENERATOR_VERSION
    assert header["columns"] == list(TILE_COLUMNS)


def test_a_file_cut_mid_gzip_is_refused_like_any_other_broken_file(database, planet_file, tmp_path):
    """Un file tagliato DAVVERO, non ricompattato a regola d'arte.

    E' il caso vero -- una copia interrotta, un disco pieno a meta' scrittura -- e si comporta
    in modo diverso: il gzip non da' una riga in meno, esplode mentre lo si scompatta. Per chi
    guarda e' lo stesso caso ("questo file non si carica") e deve dirlo allo stesso modo,
    invece di far uscire un `EOFError` da un comando amministrativo.
    """
    whole = planet_file.read_bytes()
    cut = tmp_path / "tagliato.planet.gz"
    cut.write_bytes(whole[: len(whole) // 2])

    with pytest.raises(DomainError) as refused:
        with transaction() as conn:
            mapfile.load(conn, cut)
    assert refused.value.status == 422
    with transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM world_tiles").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM world_map").fetchone()["n"] == 0


def test_a_tampered_header_is_refused(database, planet_file, tmp_path):
    """Il sigillo copre anche l'intestazione.

    Prima no: copriva solo le caselle. Un seme cambiato, o una versione del generatore
    cambiata, entravano in `world_map` in silenzio mentre la somma continuava a tornare --
    un pianeta che dichiara di essere un altro pianeta, e nessun modo di accorgersene.
    """
    import gzip
    import json
    lines = gzip.open(planet_file, "rt", encoding="utf-8").read().splitlines()
    header = json.loads(lines[0])
    header["seed"] = "UnAltroSeme"
    lines[0] = json.dumps(header, separators=(",", ":"))
    lying = tmp_path / "bugiardo.planet.gz"
    with gzip.open(lying, "wt", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")

    with pytest.raises(DomainError) as refused:
        with transaction() as conn:
            mapfile.load(conn, lying)
    assert refused.value.status == 422
    with transaction() as conn:
        assert conn.execute("SELECT count(*) AS n FROM world_tiles").fetchone()["n"] == 0


def test_a_header_missing_a_field_says_which_one(database, planet_file, tmp_path):
    """Un'intestazione monca arrivava fino all'INSERT e moriva con un `KeyError`, che dice
    qual e' la chiave e non dice che il file e' sbagliato."""
    import gzip
    import json
    lines = gzip.open(planet_file, "rt", encoding="utf-8").read().splitlines()
    header = json.loads(lines[0])
    del header["sea_level"]
    lines[0] = json.dumps(header, separators=(",", ":"))
    incomplete = tmp_path / "monco.planet.gz"
    with gzip.open(incomplete, "wt", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")

    with pytest.raises(DomainError) as refused:
        with transaction() as conn:
            mapfile.load(conn, incomplete)
    assert refused.value.status == 422
    assert "sea_level" in str(refused.value)


def test_the_load_is_not_cut_short_by_the_request_timeout(database, planet_file):
    """Il difetto che l'audit ha trovato, e che sarebbe esploso solo in produzione.

    `transaction()` mette `statement_timeout` a sessanta secondi perche' protegge le
    RICHIESTE. Ma il pianeta entra con un `COPY` solo, e quel `COPY` dura 36 secondi per un
    pianeta a quattro volte la dimensione di oggi -- su socket locale. Verso un database
    gestito in rete, cioe' l'unico caso per cui questo comando esiste, sessanta secondi si
    sforano: il caricamento sarebbe stato annullato e rifatto indietro a tre quarti dell'opera,
    e sarebbe successo la prima volta che serviva davvero.
    """
    with transaction() as conn:
        assert conn.execute("SHOW statement_timeout").fetchone()["statement_timeout"] == "1min"
        mapfile.load(conn, planet_file)
        # Dentro la stessa transazione, dopo il caricamento: il limite e' stato tolto.
        assert conn.execute("SHOW statement_timeout").fetchone()["statement_timeout"] == "0"
