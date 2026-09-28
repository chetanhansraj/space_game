"""The HTTP layer. Thin on purpose.

CLAUDE.md: "Validation, authorisation, and calls into sim and market. No
business logic." Every rule about what a player may do lives in `sim.game`;
this module checks who is asking, turns JSON into arguments, and turns
`GameError` into a 400.

**One world, one lock.** There is exactly one `Game`, one SQLite connection
and one ticker thread. Every request and every tick takes the same lock, so
the world is only ever touched by one thing at a time. That is not a
bottleneck at this scale -- a tick costs about 30 ms and most requests a
few -- and it makes the concurrency story one sentence long. It also means
the server must run as a single process: two workers would be two worlds.

**The ticker** is a thread that keeps the world at the tick the wall clock
says it should be at. It runs one tick per lock acquisition, so a server
catching up after downtime still answers requests between hours.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from sim.game import TICK_REAL_SECONDS, Game, GameError, Player
from voice import render_event, render_letter, speaker

from . import sky

log = logging.getLogger("solar.api")

#: Signups allowed per client address per hour. The development fund is
#: finite, and a script that registers a thousand companies drains it.
SIGNUPS_PER_HOUR = 3


class TradeIn(BaseModel):
    asset: str = Field(max_length=16)
    tonnes: int = Field(ge=1, le=200)
    price: int = Field(ge=1, le=100_000_000)


class DispatchIn(BaseModel):
    destination: str = Field(max_length=64)
    sell_on_arrival: bool = True


class SignupIn(BaseModel):
    name: str = Field(max_length=64)
    access_code: str = Field(default="", max_length=128)


class ReadIn(BaseModel):
    upto: int | None = None


class Ticker(threading.Thread):
    """Keeps the world on the clock."""

    def __init__(self, game_ref, lock: threading.RLock) -> None:
        super().__init__(name="ticker", daemon=True)
        self.game_ref = game_ref
        self.lock = lock
        self.halt = threading.Event()
        self.failures = 0

    def run(self) -> None:
        while not self.halt.is_set():
            try:
                with self.lock:
                    game = self.game_ref()
                    due = game.due_tick()
                    if game.world.tick < due:
                        game.step()
                        self.failures = 0
                        continue
                    wait = (game.tick_starts_at(game.world.tick + 1)
                            .timestamp() - time.time())
            except Exception:
                # A tick that fails has rolled back completely, so the world
                # is intact. Log it loudly and back off, rather than spin on
                # the same failure sixty times a second.
                self.failures += 1
                log.exception("tick failed (%d in a row)", self.failures)
                self.halt.wait(min(60, 2 ** min(self.failures, 6)))
                continue
            self.halt.wait(max(0.05, min(wait, 1.0)))

    def stop(self) -> None:
        self.halt.set()


def create_app(game: Game | None = None, *, db_path: str | None = None,
               access_code: str | None = None, web_dir: str | None = None,
               run_ticker: bool = True) -> FastAPI:
    lock = threading.RLock()
    holder: dict = {"game": game}
    access_code = (os.environ.get("SOLAR_ACCESS_CODE", "")
                   if access_code is None else access_code)
    signups: dict[str, deque] = defaultdict(deque)
    cache: dict = {}

    def the_game() -> Game:
        return holder["game"]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if holder["game"] is None:
            path = db_path or os.environ.get("SOLAR_DB", "data/world.db")
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            holder["game"] = Game.open(path, threadsafe=True)
            log.info("world open at %s, tick %d", path,
                     holder["game"].world.tick)
        ticker = Ticker(the_game, lock) if run_ticker else None
        if ticker:
            ticker.start()
        app.state.ticker = ticker
        yield
        if ticker:
            ticker.stop()
            ticker.join(timeout=5)

    app = FastAPI(title="Lunar Ark", lifespan=lifespan, docs_url=None,
                  redoc_url=None)

    @app.exception_handler(GameError)
    async def refused(request: Request, exc: GameError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    def player_for(authorization: str = Header(default="")) -> Player:
        token = authorization.removeprefix("Bearer ").strip()
        with lock:
            player = the_game().authenticate(token)
        if player is None:
            raise HTTPException(401, "Sign in again.")
        return player

    # -- the world -------------------------------------------------------

    def _companies(game: Game) -> dict[str, str]:
        return {p.id: p.name for p in game.players()}

    @app.get("/api/health")
    def health():
        with lock:
            game = the_game()
            return {"ok": True, "tick": game.world.tick,
                    "behind": game.due_tick() - game.world.tick}

    @app.get("/api/world")
    def world():
        with lock:
            game = the_game()
            key = ("world", game.world.tick, game.version)
            if cache.get("world_key") != key:
                view = game.world_view()
                companies = _companies(game)
                view["feed"] = [
                    {**e, "text": render_event(e, companies)}
                    for e in game.feed(limit=30)]
                cache["world"], cache["world_key"] = view, key
            return cache["world"]

    @app.get("/api/sky")
    def sky_view():
        with lock:
            game = the_game()
            tick = game.world.tick
            if cache.get("sky_tick") != tick:
                from orbital.clock import to_jd
                jd = to_jd(game.sky_time())
                cache["sky"] = {
                    "tick": tick, "sky_time": game.sky_time().isoformat(),
                    "bodies": sky.positions(game.world.routes.registry, jd),
                    "moon": sky.moon_phase(jd),
                }
                cache["sky_tick"] = tick
            return cache["sky"]

    @app.get("/api/market/{node}")
    def market(node: str):
        with lock:
            return the_game().market_view(node)

    def _contract(game: Game, c: dict) -> dict:
        return {**c, "issuer_character": speaker(c["issuer"]).as_dict()}

    @app.get("/api/contracts")
    def contracts():
        with lock:
            game = the_game()
            return [_contract(game, c) for c in game.contracts_view()]

    # -- joining ---------------------------------------------------------

    @app.post("/api/signup")
    def signup(body: SignupIn, request: Request):
        if access_code and not secrets.compare_digest(
                body.access_code.strip().encode(), access_code.encode()):
            raise HTTPException(403, "That access code is not right. The "
                                     "world is invitation-only for now.")
        who = request.client.host if request.client else "unknown"
        recent = signups[who]
        now = time.time()
        while recent and now - recent[0] > 3_600:
            recent.popleft()
        if len(recent) >= SIGNUPS_PER_HOUR:
            raise HTTPException(429, "Too many new companies from here. "
                                     "Try again in an hour.")
        with lock:
            player, token = the_game().signup(body.name)
        recent.append(now)
        return {"token": token, "player": {"id": player.id,
                                           "name": player.name}}

    # -- the player ------------------------------------------------------

    @app.get("/api/me")
    def me(player: Player = Depends(player_for)):
        with lock:
            game = the_game()
            view = game.company_view(player)
            view["unread"] = game.db.execute(
                "SELECT COUNT(*) FROM message WHERE player_id = ? AND read = 0",
                (player.id,)).fetchone()[0]
            return view

    @app.post("/api/session")
    def session(player: Player = Depends(player_for)):
        """Called once when the client opens: what happened while away."""
        with lock:
            return the_game().touch(player)

    @app.get("/api/inbox")
    def inbox(player: Player = Depends(player_for)):
        with lock:
            game = the_game()
            messages = game.inbox(player)
            wanted = {c for m in messages if m["kind"] == "offers"
                      for c in m["data"].get("contracts", [])}
            known = {}
            for cid in wanted:
                try:
                    known[cid] = game.board.get(cid).as_dict()
                except Exception:
                    pass
            return [render_letter(m, {"contracts": known}) for m in messages]

    @app.post("/api/inbox/read")
    def read(body: ReadIn, player: Player = Depends(player_for)):
        with lock:
            the_game().mark_read(player, body.upto)
        return {"ok": True}

    @app.post("/api/buy")
    def buy(body: TradeIn, player: Player = Depends(player_for)):
        with lock:
            return the_game().buy(player, body.asset, body.tonnes, body.price)

    @app.post("/api/sell")
    def sell(body: TradeIn, player: Player = Depends(player_for)):
        with lock:
            return the_game().sell(player, body.asset, body.tonnes, body.price)

    @app.post("/api/dispatch")
    def dispatch(body: DispatchIn, player: Player = Depends(player_for)):
        with lock:
            return the_game().dispatch(player, body.destination,
                                       body.sell_on_arrival)

    @app.post("/api/contracts/{cid}/accept")
    def accept(cid: int, player: Player = Depends(player_for)):
        with lock:
            return the_game().accept(player, cid)

    @app.post("/api/contracts/{cid}/abandon")
    def abandon(cid: int, player: Player = Depends(player_for)):
        with lock:
            return the_game().abandon(player, cid)

    @app.post("/api/contracts/{cid}/deliver")
    def deliver(cid: int, player: Player = Depends(player_for)):
        with lock:
            return the_game().deliver(player, cid)

    # -- the client ------------------------------------------------------

    web = Path(web_dir or os.environ.get(
        "SOLAR_WEB", Path(__file__).resolve().parents[3] / "web"))
    if web.is_dir():
        @app.get("/")
        def index():
            return FileResponse(web / "index.html")
        app.mount("/", StaticFiles(directory=web, html=True), name="web")

    app.state.lock = lock
    app.state.the_game = the_game
    app.state.tick_seconds = TICK_REAL_SECONDS
    return app
