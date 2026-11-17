"""The town's rules, run on the server.

A town is the city builder: the same simulation the browser plays at
sim.lunarark.com, with its habitats and greenhouses, its crew and their
missions, its zones, its shuttle and its long lunar night. docs/DECISIONS.md
D69 is why it runs here as the same code rather than as a translation of it:
the game Chetan built and likes is those rules, and a second implementation
would be a second game that drifted from the first.

So this module is a thin, careful wrapper. `town_engine.js` is
city/src/sim bundled by `npm run build:engine`; it is pure computation,
JSON in and JSON out, exactly like `orbital/`: no ledger, no database, no
clock. It runs in an embedded JavaScript engine with a time limit and a
memory limit. Everything that touches value stays in Python, in
`sim.towngame`.

Deterministic: the simulation carries its own seeded random state inside the
town's state, so the same state and the same request give the same result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ENGINE = Path(__file__).with_name("town_engine.js")
#: A request that takes longer than this is refused; a town's hour is ten
#: small steps and takes a few milliseconds.
TIMEOUT_SEC = 4
MAX_MEMORY = 256 * 1024 * 1024


class TownError(Exception):
    """The engine could not run a request. The town is left as it was."""


@dataclass
class Result:
    state: str          # the town, as JSON text; never parsed on this side
    credits: float      # the wallet as the rules left it, in town credits
    summary: dict


class Engine:
    """One embedded engine with the town's rules loaded. Rebuilt on failure."""

    def __init__(self) -> None:
        self._ctx = None

    def _context(self):
        if self._ctx is None:
            from py_mini_racer import MiniRacer
            ctx = MiniRacer()
            ctx.eval(ENGINE.read_text(encoding="utf-8"))
            self._ctx = ctx
        return self._ctx

    def _call(self, name: str, *args) -> dict:
        try:
            return json.loads(self._context().call(
                f"Town.{name}", *args, timeout_sec=TIMEOUT_SEC,
                max_memory=MAX_MEMORY))
        except Exception as exc:
            # After any failure the engine is thrown away and built fresh:
            # nothing it held can be trusted, and it holds nothing we need.
            self._ctx = None
            detail = str(exc).splitlines()[0][:200] if str(exc) else ""
            raise TownError(f"town engine failed in {name}: "
                            f"{type(exc).__name__}: {detail}") from exc

    @staticmethod
    def _result(reply: dict) -> Result:
        return Result(reply["state"], float(reply["credits"]),
                      reply["summary"])

    def create(self, seed: int, credits: float) -> Result:
        return self._result(self._call("create", int(seed), float(credits)))

    def apply(self, state: str, intent: dict, credits: float
              ) -> tuple[Result | None, str]:
        """(the town after the request, or None with the reason it was refused)."""
        reply = self._call("apply", state, json.dumps(intent), float(credits))
        if not reply.get("ok"):
            return None, reply.get("reason") or "That cannot be done"
        return self._result(reply), ""

    def tick(self, state: str, hours: float, credits: float) -> Result:
        return self._result(self._call("tick", state, float(hours),
                                       float(credits)))

    def summary(self, state: str) -> dict:
        return self._call("summary", state)
