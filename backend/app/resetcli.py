"""Azzerare la partita dalla riga di comando. Amministrazione locale, come `app.cli`.

    python -m app.resetcli --confirm

Il flag non e' burocrazia: questo comando cancella tutto cio' che e' stato giocato, e un
comando distruttivo che parte senza dirlo e' un comando che prima o poi parte per sbaglio.
"""
import argparse
import json

from app.db import transaction
from app.worldreset import KEPT, WIPED, soft_reset


def main() -> None:
    parser = argparse.ArgumentParser(description="Soft reset: via le colonie, resta il pianeta")
    parser.add_argument("--confirm", action="store_true",
                        help="richiesto: senza, non fa niente e dice cosa farebbe")
    args = parser.parse_args()
    if not args.confirm:
        print(json.dumps({"svuoterebbe": list(WIPED), "lascerebbe": list(KEPT),
                          "serve": "--confirm"}, ensure_ascii=False))
        return
    with transaction() as conn:
        removed = soft_reset(conn)
    print(json.dumps({"azzerato": removed}, ensure_ascii=False))


if __name__ == "__main__":
    main()
