"""The HTTP layer: who may ask, and that asking goes through sim.

The game rules are tested in sim/. What is tested here is the boundary --
authentication, the access code, the signup limit, JSON in and out, and
that a refusal from the game comes back as a readable 400 rather than a 500.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from api.server import SIGNUPS_PER_HOUR, create_app
from sim.game import Game
from sim.persist import default_routes

T0 = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)


@pytest.fixture(scope="module")
def routes():
    return default_routes()


@pytest.fixture
def game(routes):
    g = Game.open(":memory:", now=T0, routes=routes, threadsafe=True)
    yield g
    g.db.close()


@pytest.fixture
def client(game, tmp_path):
    (tmp_path / "index.html").write_text("<title>Lunar Ark</title>")
    app = create_app(game, access_code="ark-2190", web_dir=str(tmp_path),
                     run_ticker=False)
    with TestClient(app) as c:
        yield c


def _join(client, name="Test Freight"):
    r = client.post("/api/signup", json={"name": name,
                                         "access_code": "ark-2190"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_the_world_is_public(client):
    r = client.get("/api/world")
    assert r.status_code == 200
    body = r.json()
    assert {n["id"] for n in body["nodes"]} == {
        "shackleton_depot", "peary_ridge", "tranquillitatis_flats"}
    assert body["tick_seconds"] > 0
    assert client.get("/api/sky").json()["bodies"]
    assert client.get("/api/market/shackleton_depot").json()["assets"]
    assert client.get("/").status_code == 200


def test_signup_needs_the_access_code(client):
    r = client.post("/api/signup", json={"name": "Gatecrash",
                                         "access_code": "wrong"})
    assert r.status_code == 403


def test_signup_is_rate_limited_per_address(client):
    for i in range(SIGNUPS_PER_HOUR):
        _join(client, f"Company {i}")
    r = client.post("/api/signup", json={"name": "One Too Many",
                                         "access_code": "ark-2190"})
    assert r.status_code == 429


def test_private_views_need_a_token(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={
        "Authorization": "Bearer nonsense"}).status_code == 401


def test_the_first_session(client):
    auth = _join(client)
    me = client.get("/api/me", headers=auth).json()
    assert me["credits"] == 120_000
    assert me["ship"]["location"] == "shackleton_depot"
    assert me["ship"]["fuel_kg"] == 40_000
    assert me["unread"] >= 2
    letters = client.get("/api/inbox", headers=auth).json()
    senders = {l["from"]["name"] for l in letters}
    assert "The Archivist" in senders and "Yusuf Brandt" in senders
    assert all(l["subject"] and l["body"] for l in letters)
    away = client.post("/api/session", headers=auth).json()
    assert "unread" in away


def test_a_refusal_is_a_readable_400(client):
    auth = _join(client)
    r = client.post("/api/dispatch", headers=auth,
                    json={"destination": "shackleton_depot"})
    assert r.status_code == 400
    assert "already docked" in r.json()["detail"]
    r = client.post("/api/buy", headers=auth,
                    json={"asset": "ICE", "tonnes": 0, "price": 400})
    assert r.status_code == 422


def test_fly_somewhere_and_hear_about_it(client, game):
    auth = _join(client)
    r = client.post("/api/dispatch", headers=auth,
                    json={"destination": "peary_ridge"})
    assert r.status_code == 200, r.text
    assert client.get("/api/me", headers=auth).json()["ship"]["state"] == \
        "in_transit"
    game.step()
    me = client.get("/api/me", headers=auth).json()
    assert me["ship"]["location"] == "peary_ridge"
    letters = client.get("/api/inbox", headers=auth).json()
    assert letters[0]["subject"].startswith("Docked at Peary Ridge")
    feed = client.get("/api/world").json()["feed"]
    assert any("Peary Ridge" in e["text"] for e in feed)
