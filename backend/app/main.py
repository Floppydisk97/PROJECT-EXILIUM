from typing import Annotated, Literal
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, Header, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, model_validator

from app.db import transaction
from app.mapservice import read_map
from app.service import DomainError, owned_city, read_city, submit_order, token_hash

app = FastAPI(title="Project Exilium", version="0.1.0")
# The world map is several MB of JSON; compress it (and any other large payload).
app.add_middleware(GZipMiddleware, minimum_size=1024)
bearer = HTTPBearer(auto_error=False)


@app.middleware("http")
async def disable_state_caching(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
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
def world_map():
    # Public, immutable geography: the geodesic tiles the client renders as the planet.
    with transaction() as conn:
        return read_map(conn)


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
