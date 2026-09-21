"""Il file della CI e' codice, e questo progetto si e' gia' fatto male cinque volte con due
elenchi che dovevano coincidere e hanno smesso di farlo in silenzio.

Qui gli elenchi sono le condizioni che impediscono a una revisione di girare due volte: una
per job, identiche, perche' GitHub non ha un `if` a livello di workflow. Una che si separa
dalle altre non rompe niente di visibile -- fa girare un job in piu' o in meno, e non se ne
accorge nessuno finche' non arriva la fattura o una PR non provata.

Si legge il TESTO e non il modello YAML, per due ragioni. La proprieta' che interessa e'
testuale -- tre righe devono essere lo stesso carattere per carattere -- e leggere questo
file con PyYAML vorrebbe dire aggiungere una dipendenza per una riga sola, piu' convivere
con il fatto che in YAML 1.1 la chiave `on:` si carica come `True`.
"""
import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def lines() -> list[str]:
    return WORKFLOW.read_text().splitlines()


def job_names() -> list[str]:
    body = WORKFLOW.read_text().split("\njobs:\n", 1)[1]
    return re.findall(r"^  ([a-z][a-z0-9_-]*):$", body, re.MULTILINE)


def test_every_job_guards_against_running_a_revision_twice():
    jobs = job_names()
    assert len(jobs) >= 3, jobs
    guards = [line for line in lines() if line.startswith("    if:")]
    assert len(guards) == len(jobs), f"{len(guards)} guardie per {len(jobs)} job: {jobs}"
    assert len(set(guards)) == 1, guards
    # La guardia esclude UN caso -- la PR che nasce da un ramo di qui, gia' coperta dal suo
    # push -- invece di elencare i casi ammessi. Scritta al contrario, un evento nuovo
    # resterebbe fuori in silenzio: e' successo con l'avvio a mano.
    only = guards[0]
    assert "github.event_name != 'pull_request'" in only
    assert "head.repo.full_name != github.repository" in only


def test_the_workflow_can_be_started_by_hand():
    # Quando il giro va storto per una ragione che col codice non c'entra, l'alternativa a
    # questo bottone e' un commit finto.
    assert any(line.strip() == "workflow_dispatch:" for line in lines())


def test_both_events_ignore_the_same_documents():
    blocks = re.findall(r"    paths-ignore:\n((?:      - .*\n)+)", WORKFLOW.read_text())
    assert len(blocks) == 2, blocks
    # Se i due elenchi divergessero, un commit di soli documenti girerebbe da un lato solo --
    # cioe' proprio il doppio giro che la guardia serve a togliere.
    assert blocks[0] == blocks[1], blocks


def test_no_job_can_burn_six_hours():
    # Il limite di GitHub, taciuto, e' sei ore: un job piantato costa da solo piu' minuti di
    # un mese di lavoro normale, e su un repository privato quelli sono la risorsa scarsa.
    caps = [int(line.split(":")[1]) for line in lines() if line.startswith("    timeout-minutes:")]
    assert len(caps) == len(job_names()), caps
    assert all(0 < cap <= 30 for cap in caps), caps
