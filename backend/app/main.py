import json
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import bootstrap, gameclock, mapbuild, mapservice
from app.sim.config import WORK_KINDS
from app.db import transaction
from app.service import (
    DomainError, cast_vote, city_ground, current_policy, land, owned_city, read_city,
    demolish_work, set_work_running, start_upgrade, start_work, token_hash,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Bind the port first, build the planet after.

    Generating the world is minutes of CPU on a small instance. Doing it before the server
    exists means the port stays closed for those minutes, and Render gives up on a service
    that never binds -- which is what happened. Here the server comes up immediately and,
    only if the map is missing, hands the build to a separate process. Atterrare vuole le
    caselle nel database, quindi la mappa si costruisce ancora: cio' che non c'e' piu' e' la
    rotta che la SERVIVA, perche' il visore legge il pianeta da un file statico.

    Does nothing unless MAP_BUILD=background, so a deployment still generating from its
    start command is untouched.
    """
    print(json.dumps({"mapbuild": mapbuild.start_background_build()}), flush=True)
    # E, se il proprietario del servizio l'ha chiesto, la prima colonia. Una sola volta:
    # vedi `app/bootstrap.py` per le due guardie che lo rendono innocuo.
    print(json.dumps({"bootstrap": bootstrap.bootstrap_first_colony()}), flush=True)
    yield


app = FastAPI(title="Project Exilium", version="0.1.0", lifespan=lifespan)
# Le risposte grandi vengono compresse. Non ce n'e' piu' nessuna da molti MB -- il pianeta
# e' un file statico -- ma un elenco lungo di movimenti lo e' abbastanza da valerne la pena.
app.add_middleware(GZipMiddleware, minimum_size=1024)

# The viewer is a static site on its own host, so the city screen is cross-origin BY DESIGN:
# the planet ships as a file and only the authoritative state comes from here. That is the
# shape the downloadable client wants too, so the browser has to be told it is allowed.
#
# Named origins, never "*". Credentials travel in an Authorization header rather than a
# cookie, so a wildcard would not be refused by the browser -- it would simply let any page
# on the internet spend a token it had got hold of, which is a worse failure for being quiet.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    max_age=600,
)
bearer = HTTPBearer(auto_error=False)


# A crude fixed window, per client address, over the whole API. It is not a fairness
# mechanism; it is there so one client cannot keep a single small instance busy. Health
# checks are exempt: Render polls them from one address and must never be throttled out.
RATE_LIMIT = 120
RATE_WINDOW = 60.0
_rate_lock = threading.Lock()
_rate: dict[str, tuple[float, int]] = {}


def client_address(request: Request) -> str:
    # Behind Render's proxy the socket address is the proxy, so the forwarded header is
    # what identifies a caller. It is only trustworthy because a proxy we control sets it.
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "?")


def over_rate_limit(address: str) -> bool:
    now = time.monotonic()
    with _rate_lock:
        # Bounded memory: a flood of distinct addresses resets the table rather than growing it.
        if len(_rate) > 10_000:
            _rate.clear()
        start, count = _rate.get(address, (now, 0))
        if now - start >= RATE_WINDOW:
            start, count = now, 0
        _rate[address] = (start, count + 1)
        return count >= RATE_LIMIT


@app.middleware("http")
async def throttle_and_cache_policy(request: Request, call_next):
    if not request.url.path.startswith("/health/") and over_rate_limit(client_address(request)):
        return JSONResponse({"detail": "Too many requests"}, status_code=429,
                            headers={"Retry-After": "60", "Cache-Control": "no-store"})
    response = await call_next(request)
    # Everything here is live state and must not be cached -- except where the handler has
    # already said otherwise, which only the immutable map does.
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(DomainError)
async def domain_error(_request, error):
    headers = {"Retry-After": "5"} if error.status == 503 else {}
    if error.status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse({"detail": error.detail}, status_code=error.status, headers=headers)


@app.exception_handler(psycopg.OperationalError)
async def database_unavailable(_request, _error):
    return JSONResponse({"detail": "Database temporarily unavailable"}, status_code=503, headers={"Retry-After": "5"})


def authenticate(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if credentials is None:
        raise DomainError(401, "Bearer token required")
    with transaction() as conn:
        player = conn.execute("SELECT id FROM players WHERE token_hash = %s", (token_hash(credentials.credentials),)).fetchone()
    if player is None:
        raise DomainError(401, "Invalid bearer token")
    return player["id"]


Owner = Annotated[UUID, Depends(authenticate)]


class Vote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    choice: Literal["balanced", "industrial"]


def commitment_view(row):
    # IDs and economic integers are strings on the wire to avoid JS precision loss.
    return {**row, "id": str(row["id"]), "cost_milli": str(row["cost_milli"])}


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    """A continuous world has nothing to be behind on: production accrues from timestamps and
    commitments complete when they are read. What readiness means now is that the policy
    timeline is intact -- without an open period a city cannot be settled at all."""
    with transaction() as conn:
        open_periods = conn.execute(
            "SELECT count(*) AS n FROM policy_periods WHERE to_at IS NULL"
        ).fetchone()["n"]
    if open_periods != 1:
        raise DomainError(503, "World policy timeline is broken")
    return {"status": "ready"}


@app.get("/world")
def world_state():
    with transaction() as conn:
        world = conn.execute(
            f"""SELECT time_speed, {gameclock.NOW_SQL} AS server_time FROM world WHERE id = 1"""
        ).fetchone()
        policy = current_policy(conn)
    # `time_speed` travels with the state on purpose: a client counting down to something has
    # to know how fast this world's seconds go by, and a world running at anything but 1
    # should be able to say so rather than look broken.
    return {**world, "policy": policy}


@app.get("/me/cities")
def my_cities(owner: Owner):
    with transaction() as conn:
        return conn.execute("SELECT id, name FROM cities WHERE owner_id = %s ORDER BY id", (owner,)).fetchall()


@app.get("/cities/{city_id}")
def city_state(city_id: UUID, owner: Owner):
    with transaction() as conn:
        return read_city(conn, city_id, owner)


@app.post("/cities/{city_id}/upgrade")
def begin_upgrade(city_id: UUID, owner: Owner, idempotency_key: Annotated[UUID, Header()]):
    """Commit the city to an upgrade. The alloy goes now, the level arrives when it is done,
    and until then the city is busy -- which is the whole of the game's scarcity."""
    with transaction() as conn:
        return commitment_view(start_upgrade(conn, city_id, owner, idempotency_key))


class Landing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tile_id: int = Field(ge=0)


@app.post("/cities/{city_id}/land")
def land_colony(city_id: UUID, landing: Landing, owner: Owner):
    """Take a tile. Once, and for ever: the colony's own ground is rolled here and the seed
    that rolled it is what gets kept."""
    with transaction() as conn:
        return land(conn, city_id, owner, landing.tile_id)


@app.get("/cities/{city_id}/ground")
def colony_ground(city_id: UUID, owner: Owner):
    """The seed the colony's ground grows from, and what the planet says about the site.

    Not the cells: they are a pure function of these few numbers, and whoever asked can grow
    them faster than this instance can serialise them."""
    with transaction() as conn:
        return city_ground(conn, city_id, owner)


class Work(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Non un Literal scritto a mano: l'elenco vive in `sim/config`, e un secondo elenco qui
    # significherebbe poter aggiungere un impianto alle regole e al database e vederselo
    # rifiutare dall'API con un messaggio che parla di un tipo solo. E' gia' successo.
    kind: str

    @field_validator("kind")
    @classmethod
    def known(cls, value: str) -> str:
        if value not in WORK_KINDS:
            raise ValueError(f"unknown work: {value}")
        return value


@app.post("/cities/{city_id}/works")
def build_work(city_id: UUID, work: Work, owner: Owner,
               idempotency_key: Annotated[UUID, Header()]):
    """Mettere in piedi un'opera. Consuma e produce di continuo: e' cio' che trasforma un
    magazzino che sale in una catena che puo' restare a secco."""
    with transaction() as conn:
        return commitment_view(start_work(conn, city_id, owner, work.kind, idempotency_key))


class Running(BaseModel):
    model_config = ConfigDict(extra="forbid")
    running: int = Field(ge=0, le=64)


@app.put("/cities/{city_id}/works/{kind}")
def set_running(city_id: UUID, kind: str, wanted: Running, owner: Owner):
    """Quanti impianti di questo tipo tenere accesi. Istantaneo: e' un interruttore."""
    with transaction() as conn:
        return set_work_running(conn, city_id, owner, kind, wanted.running)


@app.delete("/cities/{city_id}/works/{kind}")
def remove_work(city_id: UUID, kind: str, owner: Owner):
    """Abbattere un impianto di questo tipo. Senza rimborso."""
    with transaction() as conn:
        return demolish_work(conn, city_id, owner, kind)


@app.put("/cities/{city_id}/vote")
def set_vote(city_id: UUID, vote: Vote, owner: Owner):
    """A standing preference, not an order aimed at a deadline: the majority is whatever the
    held preferences currently say, and it takes effect the moment it moves."""
    with transaction() as conn:
        return cast_vote(conn, city_id, owner, vote.choice)


@app.get("/cities/{city_id}/commitments")
def list_commitments(city_id: UUID, owner: Owner, after: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    with transaction() as conn:
        owned_city(conn, city_id, owner)
        rows = conn.execute("SELECT * FROM orders WHERE city_id = %s AND id > %s ORDER BY id LIMIT %s", (city_id, after, limit)).fetchall()
    return [commitment_view(row) for row in rows]


@app.get("/cities/{city_id}/ledger")
def list_ledger(city_id: UUID, owner: Owner, after: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    with transaction() as conn:
        owned_city(conn, city_id, owner)
        rows = conn.execute("SELECT * FROM resource_ledger WHERE city_id = %s AND id > %s ORDER BY id LIMIT %s", (city_id, after, limit)).fetchall()
    return [{**row, "id": str(row["id"]), "amount": str(row["amount"])} for row in rows]
