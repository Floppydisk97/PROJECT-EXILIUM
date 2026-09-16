import os
from typing import Annotated, Literal
from uuid import UUID

import psycopg
from fastapi import Cookie, Depends, FastAPI, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db import transaction
from app.service import (
    DomainError, authenticate_session, available_cells, build_extractor, enter_world,
    found_colony, login, owned_city, profile, read_city, register, revoke_session,
    submit_order,
)

app = FastAPI(title="Project Exilium", version="0.2.0")
SESSION_COOKIE = "exilium_session"
COOKIE_MAX_AGE = 30 * 24 * 60 * 60


def production_mode():
    return os.getenv("APP_ENV", "production").lower() == "production"


def cookie_secure():
    if production_mode():
        return True
    return os.getenv("SESSION_COOKIE_SECURE", "true").lower() not in {"0", "false", "no"}


def trusted_origins():
    return {
        origin.strip().rstrip("/")
        for origin in os.getenv("TRUSTED_ORIGINS", "").split(",")
        if origin.strip()
    }


def set_session_cookie(response: Response, token: str):
    response.set_cookie(
        SESSION_COOKIE, token, max_age=COOKIE_MAX_AGE, httponly=True,
        secure=cookie_secure(), samesite="lax", path="/",
    )


@app.middleware("http")
async def request_security(request: Request, call_next):
    mutating = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    authenticated = SESSION_COOKIE in request.cookies
    if production_mode() and mutating and authenticated:
        origin = request.headers.get("origin", "").rstrip("/")
        if not origin or origin not in trusted_origins():
            return JSONResponse(
                {"detail": "Untrusted request origin"}, status_code=403,
                headers={"Cache-Control": "no-store"},
            )
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(DomainError)
async def domain_error(_request, error):
    headers = {"Retry-After": "5"} if error.status == 503 else {}
    return JSONResponse({"detail": error.detail}, status_code=error.status, headers=headers)


@app.exception_handler(psycopg.OperationalError)
async def database_unavailable(_request, _error):
    return JSONResponse(
        {"detail": "Database temporarily unavailable"}, status_code=503,
        headers={"Retry-After": "5"},
    )


def authenticate(raw_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None):
    with transaction() as conn:
        return authenticate_session(conn, raw_token)["id"]


Owner = Annotated[UUID, Depends(authenticate)]


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    handle: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=10, max_length=128)


class ColonyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    cell_id: int = Field(gt=0)

    @model_validator(mode="after")
    def name_has_content(self):
        if not self.name.strip():
            raise ValueError("Colony name cannot be blank")
        return self


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
    return {**order, "id": str(order["id"]), "target_tick": str(order["target_tick"])}


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    with transaction() as conn:
        state = conn.execute(
            "SELECT next_tick_at > clock_timestamp() AS ready FROM world WHERE id = 1"
        ).fetchone()
    if not state or not state["ready"]:
        raise DomainError(503, "World requires tick recovery")
    return {"status": "ready"}


@app.get("/world")
def world_state():
    with transaction() as conn:
        world = conn.execute(
            """SELECT slug, policy, last_tick, next_tick_at,
                      clock_timestamp() AS server_time FROM world WHERE id = 1"""
        ).fetchone()
    return {**world, "last_tick": str(world["last_tick"])}


@app.post("/auth/register", status_code=201)
def register_account(credentials: Credentials, response: Response):
    with transaction() as conn:
        result = register(conn, credentials.handle, credentials.password)
    set_session_cookie(response, result.pop("token"))
    return result


@app.post("/auth/login")
def login_account(credentials: Credentials, response: Response):
    with transaction() as conn:
        result = login(conn, credentials.handle, credentials.password)
    set_session_cookie(response, result.pop("token"))
    return result


@app.post("/auth/logout", status_code=204)
def logout(response: Response, raw_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None):
    with transaction() as conn:
        revoke_session(conn, raw_token)
    response.delete_cookie(
        SESSION_COOKIE, httponly=True, secure=cookie_secure(), samesite="lax", path="/"
    )


@app.get("/me")
def me(owner: Owner):
    with transaction() as conn:
        return profile(conn, owner)


@app.post("/worlds/exilium-prime/enter")
def enter_exilium_prime(owner: Owner):
    with transaction() as conn:
        return enter_world(conn, owner)


@app.get("/worlds/exilium-prime/cells")
def list_available_cells(owner: Owner):
    with transaction() as conn:
        return available_cells(conn, owner)


@app.post("/worlds/exilium-prime/colonies", status_code=201)
def create_colony(
    request: ColonyRequest, owner: Owner, idempotency_key: Annotated[UUID, Header()]
):
    with transaction() as conn:
        return found_colony(conn, owner, idempotency_key, request.name, request.cell_id)


@app.get("/me/cities")
def my_cities(owner: Owner):
    with transaction() as conn:
        return conn.execute(
            "SELECT id, name, is_capital FROM cities WHERE owner_id = %s ORDER BY created_at, id",
            (owner,),
        ).fetchall()


@app.get("/cities/{city_id}")
def city_state(city_id: UUID, owner: Owner):
    with transaction() as conn:
        return read_city(conn, city_id, owner)


@app.post("/cities/{city_id}/buildings/extractor", status_code=201)
def create_extractor(city_id: UUID, owner: Owner, idempotency_key: Annotated[UUID, Header()]):
    with transaction() as conn:
        return build_extractor(conn, city_id, owner, idempotency_key)


@app.post("/cities/{city_id}/orders")
def create_order(
    city_id: UUID, command: Command, owner: Owner,
    idempotency_key: Annotated[UUID, Header()],
):
    with transaction() as conn:
        return order_view(
            submit_order(conn, city_id, owner, idempotency_key, command.kind, command.choice)
        )


@app.get("/cities/{city_id}/orders")
def list_orders(
    city_id: UUID, owner: Owner, after: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    with transaction() as conn:
        owned_city(conn, city_id, owner)
        rows = conn.execute(
            "SELECT * FROM orders WHERE city_id = %s AND id > %s ORDER BY id LIMIT %s",
            (city_id, after, limit),
        ).fetchall()
    return [order_view(row) for row in rows]


@app.get("/cities/{city_id}/ledger")
def list_ledger(
    city_id: UUID, owner: Owner, after: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    with transaction() as conn:
        owned_city(conn, city_id, owner)
        rows = conn.execute(
            """SELECT * FROM resource_ledger WHERE city_id = %s AND id > %s
               ORDER BY id LIMIT %s""",
            (city_id, after, limit),
        ).fetchall()
    return [{**row, "id": str(row["id"]), "amount": str(row["amount"])} for row in rows]
