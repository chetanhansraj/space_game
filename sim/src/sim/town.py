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
    made: int = 0       # whole kilograms of goods the foundries made
    used: int = 0       # whole kilograms the buildings took from the yard as parts
    landed: float = 0.0  # kilograms of parts Earth landed, already paid for


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
                      reply["summary"], int(reply.get("made") or 0),
                      int(reply.get("used") or 0),
                      float(reply.get("landed") or 0))

    def create(self, seed: int, credits: float, plot: dict | None = None,
               world: dict | None = None) -> Result:
        """A new town. ``plot`` is the ground it stands on (sim.plots);
        ``world`` is the hour as the world has it (see ``tick``)."""
        args = [int(seed), float(credits),
                json.dumps(plot, sort_keys=True) if plot else None,
                json.dumps(world, sort_keys=True) if world else None]
        while args and args[-1] is None:
            args.pop()
        return self._result(self._call("create", *args))

    def apply(self, state: str, intent: dict, credits: float
              ) -> tuple[Result | None, str]:
        """(the town after the request, or None with the reason it was refused)."""
        reply = self._call("apply", state, json.dumps(intent), float(credits))
        if not reply.get("ok"):
            return None, reply.get("reason") or "That cannot be done"
        return self._result(reply), ""

    def tick(self, state: str, hours: float, credits: float,
             yard: dict | None = None, world: dict | None = None) -> Result:
        """Advance a town. ``yard`` is ``{"cap": kg, "held": kg}``.

        Given a yard, the foundries make goods into it instead of being
        paid, and ``Result.made`` is the whole kilograms they made.

        With ``"wear": True`` in the yard the buildings also use goods as
        spare parts: ``Result.used`` is the whole kilograms they took from
        it, and ``Result.landed`` what Earth landed because it was empty,
        charged to the wallet at ``"importAt"`` town credits a kilogram.

        ``world`` is the hour as the world has it: ``{"noon": hours since
        the Sun was highest over the town, "pace": game hours in a real
        minute}``. The town sets its day by the first and sizes the waits
        a person must answer by the second.
        """
        args = [state, float(hours), float(credits),
                json.dumps(yard) if yard is not None else None,
                json.dumps(world, sort_keys=True) if world else None]
        while args and args[-1] is None:
            args.pop()
        return self._result(self._call("tick", *args))

    def topup(self, state: str, world: dict | None = None) -> Result:
        """Fill a town's batteries. Used once, at the move to the one Sun."""
        args = [state] + ([json.dumps(world, sort_keys=True)] if world else [])
        return self._result(self._call("topup", *args))

    def steward(self, state: str, credits: float, keep: bool = False,
                style: dict | None = None) -> list[dict]:
        """The requests a careful player would send this hour. Changes nothing.

        With ``keep``, only what a caretaker would send: what is urgent.
        ``style`` is a temperament: how this company likes to build once
        its crew is safe (``Style`` in city/src/steward.ts).
        """
        args = [state, float(credits), bool(keep)]
        if style:
            args.append(json.dumps(style, sort_keys=True))
        return self._call("steward", *args)["intents"]

    def summary(self, state: str) -> dict:
        return self._call("summary", state)
