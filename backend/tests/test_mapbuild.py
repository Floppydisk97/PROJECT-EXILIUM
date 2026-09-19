"""The rule that keeps the front door open.

Generating the planet used to sit in the start command, before `exec uvicorn`, so the port
stayed closed for the whole build. Render gives up on a service that never binds, and at
0.15 of a core the build outgrew the wait: 13 s with CPU burst, 6 min 30 s without, and past
27 minutes on the third attempt. These tests pin the arrangement that replaced it -- they
cannot reproduce Render's timeout, but they can hold the two decisions that avoid it.
"""
import json
import subprocess
from types import SimpleNamespace

import pytest

from app import mapbuild, mapcli


@pytest.fixture(autouse=True)
def fresh_guard():
    """`start_background_build` is once-per-process by design; tests need it armed again."""
    mapbuild._done = False
    yield
    mapbuild._done = False


def test_the_cli_stands_down_when_the_api_owns_the_build(monkeypatch, capsys):
    """This is what makes the start command return at once: the same `python -m app.mapcli`
    that used to block for minutes prints a line and exits. If this regressed, the port
    would go back to staying shut for the length of a build."""
    monkeypatch.setattr(mapbuild, "BACKGROUND", True)
    monkeypatch.setattr("sys.argv", ["mapcli"])
    mapcli.main()
    assert "skipped" in json.loads(capsys.readouterr().out)


def test_asking_explicitly_still_builds(monkeypatch):
    """`--now` is how the API asks the child to do the work, so it must pierce the guard --
    otherwise nothing would ever build the map at all."""
    monkeypatch.setattr(mapbuild, "BACKGROUND", True)
    monkeypatch.setattr("sys.argv", ["mapcli", "--now"])
    called = {}

    class FakeConn:
        pass

    import contextlib

    @contextlib.contextmanager
    def fake_transaction():
        yield FakeConn()

    def fake_generate(conn, seed, frequency):
        called["seed"], called["frequency"] = seed, frequency
        return {"ok": True}

    monkeypatch.setattr(mapcli, "transaction", fake_transaction)
    monkeypatch.setattr(mapcli, "generate_and_store", fake_generate)
    mapcli.main()
    from app import worldgen
    assert called == {"seed": worldgen.PRODUCTION_SEED, "frequency": worldgen.PRODUCTION_FREQUENCY}


def test_nothing_happens_unless_the_deployment_asked_for_it(monkeypatch):
    """A deployment that still generates from its start command must be untouched by this."""
    monkeypatch.setattr(mapbuild, "BACKGROUND", False)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    assert mapbuild.start_background_build() == "disabled"


def test_a_world_that_already_exists_is_not_built_again(monkeypatch):
    """The map is immutable and one-shot; spawning a build over a live world would at best
    waste 370 MB and at worst race the thing it duplicates."""
    monkeypatch.setattr(mapbuild, "BACKGROUND", True)
    monkeypatch.setattr(mapbuild, "map_is_missing", lambda conn: False)
    monkeypatch.setattr("app.db.transaction", _fake_transaction)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    assert mapbuild.start_background_build() == "map already present"


def test_it_only_ever_starts_once(monkeypatch):
    spawned = []
    monkeypatch.setattr(mapbuild, "BACKGROUND", True)
    monkeypatch.setattr(mapbuild, "map_is_missing", lambda conn: True)
    monkeypatch.setattr("app.db.transaction", _fake_transaction)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: spawned.append(a) or SimpleNamespace())
    assert mapbuild.start_background_build() == "started"
    assert mapbuild.start_background_build() == "already started"
    assert len(spawned) == 1
    assert "--now" in spawned[0][0]


def test_the_build_is_not_silenced(monkeypatch):
    """The first version sent the child's stdout and stderr to DEVNULL. It cost exactly what
    you would expect: asked whether the planet had been generated, the logs could say that a
    process had been started and nothing else, and the answer had to come from restarting the
    service to see what it said about a map it already had. Detaching the child is
    `start_new_session`; muting it was never part of the job."""
    spawned = []
    monkeypatch.setattr(mapbuild, "BACKGROUND", True)
    monkeypatch.setattr(mapbuild, "map_is_missing", lambda conn: True)
    monkeypatch.setattr("app.db.transaction", _fake_transaction)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: spawned.append(k) or SimpleNamespace())
    assert mapbuild.start_background_build() == "started"
    assert spawned[0].get("stdout") is None, "the build's output must reach the service log"
    assert spawned[0].get("stderr") is None, "a failed build must be able to say so"
    assert spawned[0]["start_new_session"] is True


def test_a_failure_to_build_never_takes_the_server_down(monkeypatch):
    """The server's job is to answer, including to answer that there is no map yet. A world
    that cannot be built must not also cost us the only process able to say so."""
    monkeypatch.setattr(mapbuild, "BACKGROUND", True)
    monkeypatch.setattr(mapbuild, "map_is_missing", lambda conn: True)
    monkeypatch.setattr("app.db.transaction", _fake_transaction)

    def explode(*_args, **_kwargs):
        raise OSError("no fork for you")

    monkeypatch.setattr(subprocess, "Popen", explode)
    assert mapbuild.start_background_build() == "spawn failed"

    mapbuild._done = False
    monkeypatch.setattr("app.db.transaction", _broken_transaction)
    assert mapbuild.start_background_build() == "check failed"


def _forbidden(*_args, **_kwargs):
    raise AssertionError("no generator should have been spawned")


import contextlib


@contextlib.contextmanager
def _fake_transaction():
    yield object()


@contextlib.contextmanager
def _broken_transaction():
    raise RuntimeError("database unreachable")
    yield  # pragma: no cover
