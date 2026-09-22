"""Un server che si comporta male apposta, per provare `api.gd` contro la rete vera.

Non e' il gioco: e' il minimo che serve per vedere se il client sopravvive a un'istanza che
dorme, a un token rifiutato e a un rifiuto motivato -- che sono le tre cose che si rompono in
silenzio e che nessuna prova pura vede.

    python3 client/tests/fakeserver.py 8099 &
    EXILIUM_TEST_API=http://127.0.0.1:8099 godot --headless --path client --script tests/run.gd
"""
import json
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

# Quante volte /sveglia ha gia' detto di no. Due, come un'istanza gratuita che si sta
# accendendo: abbastanza perche' il client debba aspettare almeno una pausa vera.
asleep_for = 2

SAMPLE = Path(__file__).with_name("city.sample.json")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        global asleep_for
        # Una rotta che dice solo "sono in piedi", per chi aspetta che il server parta. Le
        # altre rispondono male apposta, e `curl -f` non distingue un 422 voluto da un server
        # che non c'e' ancora.
        if self.path == "/pronto":
            return self.reply(200, {"status": "ok"})
        if self.path == "/sveglia":
            if asleep_for > 0:
                asleep_for -= 1
                return self.reply(503, {"detail": "waking up"})
            # Si torna a dormire subito dopo aver risposto, cosi' ogni giro di prove trova
            # una partenza a freddo. Senza, il secondo giro rispondeva al primo colpo e la
            # prova "ha aspettato" passava per il motivo sbagliato -- il che e' peggio che
            # non averla.
            asleep_for = 2
            return self.reply(200, {"status": "ok"})
        # Le due rotte che servono allo SCHERMO della citta', servite dall'istantanea: cosi'
        # si puo' fotografare il client mentre parla davvero con qualcuno, invece di
        # fotografare il suo ripiego e sperare che il resto funzioni.
        if self.path == "/me/cities":
            city = json.loads(SAMPLE.read_text())["city"]
            return self.reply(200, [{"id": city["id"], "name": city["name"]}])
        if self.path.startswith("/cities/"):
            return self.reply(200, json.loads(SAMPLE.read_text())["city"])
        if self.path == "/rifiuto-token":
            return self.reply(401, {"detail": "Invalid bearer token"})
        if self.path == "/rifiuto":
            return self.reply(422, {"detail": "tile already taken"})
        return self.reply(404, {"detail": "no such thing"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode()
        # Si rimanda indietro cio' che si e' RICEVUTO, non cio' che il client crede di aver
        # mandato: e' l'unico modo di provare che le intestazioni ci sono davvero.
        self.reply(200, {
            "authorization": self.headers.get("Authorization", ""),
            "idempotency_key": self.headers.get("Idempotency-Key", ""),
            "body": body,
        })


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
