"""Il pianeta come file portatile, e come si rimette dentro un database qualunque.

    python -m app.mapfile dump  --out pianeti/hesperia.planet.gz
    python -m app.mapfile load  pianeti/hesperia.planet.gz

PERCHE' ESISTE. Il pianeta si genera UNA VOLTA SOLA, per sempre: e' immutabile e i trigger
del database lo impongono. Ma finora lo costruiva l'istanza che serve l'API, all'avvio, e
generarlo costa memoria -- 358 MB misurati alla dimensione di oggi, su un'istanza che ne ha
512. Siamo al soffitto: il pianeta non puo' crescere, e non perche' manchi lo spazio su
disco, ma perche' la macchina che lo serve non ha la RAM per FARLO.

Questo rompe il legame. Il pianeta si genera dove c'e' memoria -- un portatile, un runner di
CI, qualunque cosa -- e arriva al database come un flusso di righe. Il server non genera piu'
niente e la RAM smette di essere il vincolo, qualunque provider si scelga.

IL FORMATO, e perche' sta tutto in questo file. Una riga JSON per casella, dentro un gzip:
si scrive e si legge a memoria costante, si guarda con `zcat` quando qualcosa non torna, e
non ha bisogno di una libreria. Le due meta' -- chi scrive e chi legge -- stanno nello stesso
file di proposito: separarle e' il modo in cui un formato comincia a non essere d'accordo
con se stesso, e qui dentro le copie-che-devono-coincidere sono gia' costate abbastanza.

    riga 1        l'intestazione: che pianeta e', quanto e' grande
    righe 2..n+1  una casella per riga, nei valori di `mapservice.TILE_COLUMNS`
    ultima riga   il sigillo: quante caselle e il loro sha256

Il sigillo sta in FONDO e non in testa perche' chi scrive non puo' sapere la somma prima di
aver finito. Chi legge la verifica dopo aver inserito tutto, dentro la stessa transazione:
un file troncato o corrotto non lascia mezzo pianeta nel database, non lascia niente.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from app import worldgen
from app.db import transaction
from app.mapservice import TILE_COLUMNS, as_database_row, tile_values
from app.service import DomainError

FORMAT = "exilium-planet-1"

# I tipi delle colonne, nell'ordine di `TILE_COLUMNS`. Servono a `COPY`, che e' un canale di
# testo e non indovina: senza, un intero e un intero[] si somigliano troppo.
COLUMN_TYPES = (
    "int4", "float8", "float8", "float8", "float8", "float8", "int4", "float8", "int4",
    "text", "int4[]", "jsonb", "float8", "float8", "float8", "int4", "int4", "int4",
)


def write(path: Path, seed: str, frequency: int) -> dict:
    """Genera un pianeta e lo scrive. E' il passo che costa memoria, e l'unico."""
    world = worldgen.generate(seed, frequency)
    digest = hashlib.sha256()
    written = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as out:
        header = {
            "format": FORMAT, "name": worldgen.WORLD_NAME, "seed": world.seed,
            "frequency": world.frequency, "sea_level": world.sea_level,
            "generator_version": worldgen.GENERATOR_VERSION,
            "columns": list(TILE_COLUMNS),
        }
        head = json.dumps(header, separators=(",", ":"))
        # Il sigillo copre ANCHE l'intestazione. Senza, un seme o una versione del generatore
        # corrotti entravano in `world_map` in silenzio mentre la somma continuava a tornare:
        # un pianeta che dichiara di essere un altro pianeta, e nessun modo di accorgersene.
        digest.update(head.encode("utf-8"))
        out.write(head + "\n")
        for values in tile_values(world):
            line = json.dumps(values, separators=(",", ":"))
            digest.update(line.encode("utf-8"))
            out.write(line + "\n")
            written += 1
        out.write(json.dumps({"tiles": written, "sha256": digest.hexdigest()},
                             separators=(",", ":")) + "\n")
    return {"file": str(path), "tiles": written, "bytes": path.stat().st_size,
            "seed": world.seed, "frequency": world.frequency}


REQUIRED_HEADER = ("format", "name", "seed", "frequency", "sea_level",
                   "generator_version", "columns")


def load(conn, path: Path) -> dict:
    """Rimette il pianeta in un database vuoto, a memoria costante.

    `COPY` e non `INSERT`: e' il canale che PostgreSQL usa per farsi riempire una tabella, e
    a due milioni di righe la differenza fra i due non e' una sfumatura.

    Rifiuta se un mondo c'e' gia', e lo rifiuta prima di scrivere un solo byte. Il pianeta e'
    immutabile per regola del gioco -- ci sono i trigger a dirlo -- quindi "caricane un altro
    sopra" non e' una cosa che si fa per sbaglio: si fa con una migrazione, che e' un posto
    dove qualcuno ha guardato cosa stava facendo.
    """
    if conn.execute("SELECT 1 FROM world_map WHERE id = 1").fetchone():
        raise DomainError(409, "World map already generated; a new world needs a new migration")
    try:
        return _load(conn, path)
    except (EOFError, gzip.BadGzipFile, json.JSONDecodeError, UnicodeDecodeError) as broken:
        # Un gzip tagliato a meta' non da' una riga in meno: da' `EOFError` mentre lo si
        # scompatta. Un file che non e' un pianeta da' altro ancora. Sono tutti lo stesso
        # caso per chi guarda -- "questo file non si puo' caricare" -- e devono dirlo cosi'.
        raise DomainError(422, f"Planet file is unreadable: {broken}") from broken


def _load(conn, path: Path) -> dict:
    # Senza limite di tempo, e di proposito. `transaction()` mette `statement_timeout` a
    # sessanta secondi perche' protegge le RICHIESTE: una query che scappa non deve tenere
    # occupato il server. Questo non e' una richiesta -- e' un comando amministrativo che
    # qualcuno lancia guardandolo -- e il pianeta e' un `COPY` solo: misurato, 36 s per un
    # pianeta a quattro volte la dimensione di oggi, su socket locale. Verso un database
    # gestito in rete, cioe' l'unico caso per cui questo comando esiste, sessanta secondi si
    # sforano e il caricamento viene annullato e rifatto indietro a tre quarti dell'opera.
    conn.execute("SET LOCAL statement_timeout = 0")

    with gzip.open(path, "rt", encoding="utf-8") as source:
        header = json.loads(source.readline())
        if not isinstance(header, dict) or header.get("format") != FORMAT:
            raise DomainError(422, f"Not a planet file: {header.get('format') if isinstance(header, dict) else type(header).__name__!r}")
        missing = [key for key in REQUIRED_HEADER if key not in header]
        if missing:
            # Un'intestazione monca arrivava fino all'INSERT e moriva con un KeyError, che
            # dice al lettore qual e' la chiave e non gli dice che il file e' sbagliato.
            raise DomainError(422, f"Planet file header is missing: {', '.join(missing)}")
        if header["columns"] != list(TILE_COLUMNS):
            # Il file e' stato scritto quando una casella aveva altre colonne. Caricarlo
            # riempirebbe le colonne sbagliate con i valori giusti, che e' il modo peggiore
            # di sbagliare: nessun errore, e un pianeta storto.
            raise DomainError(422, "Planet file was written for a different set of columns")

        conn.execute(
            """INSERT INTO world_map(id, name, seed, frequency, sea_level, generator_version)
               VALUES (1, %s, %s, %s, %s, %s)""",
            (header["name"], header["seed"], header["frequency"],
             header["sea_level"], header["generator_version"]),
        )

        digest = hashlib.sha256()
        digest.update(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        read = 0
        statement = "COPY world_tiles ({}) FROM STDIN".format(", ".join(TILE_COLUMNS))
        trailer = None
        with conn.cursor() as cur, cur.copy(statement) as copy:
            copy.set_types(COLUMN_TYPES)
            for line in source:
                line = line.rstrip("\n")
                if not line:
                    continue
                values = json.loads(line)
                if isinstance(values, dict):
                    trailer = values      # il sigillo: le caselle sono finite
                    break
                digest.update(line.encode("utf-8"))
                copy.write_row(as_database_row(values))
                read += 1

    if trailer is None:
        raise DomainError(422, "Planet file has no seal: it was truncated while being written")
    if trailer.get("tiles") != read:
        raise DomainError(422, f"Planet file says {trailer.get('tiles')} tiles, carries {read}")
    if trailer.get("sha256") != digest.hexdigest():
        raise DomainError(422, "Planet file is corrupt: the seal does not match its tiles")
    return {"name": header["name"], "seed": header["seed"],
            "frequency": header["frequency"], "tiles": read}


def main() -> None:
    parser = argparse.ArgumentParser(description="Il pianeta come file portatile")
    sub = parser.add_subparsers(dest="what", required=True)

    writer = sub.add_parser("dump", help="Genera un pianeta e scrivilo in un file")
    writer.add_argument("--out", type=Path, required=True)
    writer.add_argument("--seed", default=worldgen.PRODUCTION_SEED)
    writer.add_argument("--frequency", type=int, default=worldgen.PRODUCTION_FREQUENCY)

    reader = sub.add_parser("load", help="Carica un file in un database vuoto")
    reader.add_argument("path", type=Path)

    args = parser.parse_args()
    if args.what == "dump":
        print(json.dumps(write(args.out, args.seed, args.frequency), default=str))
    else:
        with transaction() as conn:
            print(json.dumps(load(conn, args.path), default=str))


if __name__ == "__main__":
    main()
