import json
import threading
import time
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, model_validator

from app import mapbuild, mapservice
from app.db import transaction
from app.service import DomainError, owned_city, read_city, submit_order, token_hash


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Bind the port first, build the planet after.

    Generating the world is minutes of CPU on a small instance. Doing it before the server
    exists means the port stays closed for those minutes, and Render gives up on a service
    that never binds -- which is what happened. Here the server comes up immediately and,
    only if the map is missing, hands the build to a separate process. Until that finishes
    `/world/map` answers 404 and the client already says so in as many words.

    Does nothing unless MAP_BUILD=background, so a deployment still generating from its
    start command is untouched.
    """
    print(json.dumps({"mapbuild": mapbuild.start_background_build()}), flush=True)
    yield


app = FastAPI(title="Project Exilium", version="0.1.0", lifespan=lifespan)
# The world map is several MB of JSON; compress it (and any other large payload).
app.add_middleware(GZipMiddleware, minimum_size=1024)
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


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["upgrade", "policy_vote"]
    choice: Literal["balanced", "industrial"] | None = None

    @model_validator(mode="after")
    def valid_choice(self):
        if (self.kind == "policy_vote") != (self.choice is not None):
            raise ValueError("Only policy_vote requires a choice")
        return self


def order_view(order):
    # IDs and economic integers are strings on the wire to avoid JS precision loss.
    return {**order, "id": str(order["id"]), "target_tick": str(order["target_tick"])}


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    with transaction() as conn:
        state = conn.execute("SELECT next_tick_at > clock_timestamp() AS ready FROM world WHERE id = 1").fetchone()
    if not state or not state["ready"]:
        raise DomainError(503, "World requires tick recovery")
    return {"status": "ready"}


@app.get("/world")
def world_state():
    with transaction() as conn:
        world = conn.execute("SELECT policy, last_tick, next_tick_at, clock_timestamp() AS server_time FROM world WHERE id = 1").fetchone()
    return {**world, "last_tick": str(world["last_tick"])}


@app.get("/world/map")
def world_map(request: Request):
    # Public, immutable geography: the geodesic tiles the client renders as the planet.
    # Built once per process and served as bytes; only a cache miss touches the database.
    payload = mapservice.cached_payload()
    if payload is None:
        with transaction() as conn:
            payload = mapservice.build_payload(conn)
    headers = {
        "ETag": payload["etag"],
        # Immutable for the life of this world: a new map only ever arrives with a deploy,
        # and the ETag changes with it.
        "Cache-Control": "public, max-age=86400, immutable",
    }
    if request.headers.get("if-none-match") == payload["etag"]:
        return Response(status_code=304, headers=headers)
    if "gzip" in request.headers.get("accept-encoding", ""):
        # Pre-compressed, so the gzip middleware passes it through untouched rather than
        # spending CPU on twelve megabytes per request.
        return Response(payload["gzip"], media_type="application/json",
                        headers={**headers, "Content-Encoding": "gzip",
                                 "Vary": "Accept-Encoding"})
    return Response(payload["raw"], media_type="application/json", headers=headers)


@app.get("/me/cities")
def my_cities(owner: Owner):
    with transaction() as conn:
        return conn.execute("SELECT id, name FROM cities WHERE owner_id = %s ORDER BY id", (owner,)).fetchall()


@app.get("/cities/{city_id}")
def city_state(city_id: UUID, owner: Owner):
    with transaction() as conn:
        return read_city(conn, city_id, owner)


@app.post("/cities/{city_id}/orders")
def create_order(city_id: UUID, command: Command, owner: Owner,
                 idempotency_key: Annotated[UUID, Header()]):
    with transaction() as conn:
        return order_view(submit_order(conn, city_id, owner, idempotency_key, command.kind, command.choice))


@app.get("/cities/{city_id}/orders")
def list_orders(city_id: UUID, owner: Owner, after: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    with transaction() as conn:
        owned_city(conn, city_id, owner)
        rows = conn.execute("SELECT * FROM orders WHERE city_id = %s AND id > %s ORDER BY id LIMIT %s", (city_id, after, limit)).fetchall()
    return [order_view(row) for row in rows]


@app.get("/cities/{city_id}/ledger")
def list_ledger(city_id: UUID, owner: Owner, after: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    with transaction() as conn:
        owned_city(conn, city_id, owner)
        rows = conn.execute("SELECT * FROM resource_ledger WHERE city_id = %s AND id > %s ORDER BY id LIMIT %s", (city_id, after, limit)).fetchall()
    return [{**row, "id": str(row["id"]), "amount": str(row["amount"])} for row in rows]
