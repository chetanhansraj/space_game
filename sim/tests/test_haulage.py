"""Freight: the loop the game is built around.

"The moment there are two places with different prices, the game becomes
trade, and that is the real product."
"""

import pytest

from market.money import CREDIT
from sim.seed_world import PEARY, SHACKLETON, build
from sim.ships import ShipState

TONNE = 1_000

#: Long enough for ships to complete round trips and for the ice spread to
#: respond. Kept as low as that allows: a tick is not cheap, and every test
#: in this module reads the same world rather than building its own.
RUN = 160


@pytest.fixture(scope="module")
def flown():
    """One flown world, shared. Read-only for every test below."""
    from market.db import connect

    w = build(connect(":memory:"))
    for _ in range(RUN):
        w.run_tick()
    yield w
    w.ledger.db.close()


def test_ships_actually_fly(flown):
    assert sum(s.voyages for s in flown.ships) > 0
    assert any(e.kind == "departure" for e in flown.events)
    assert any(e.kind == "arrival" for e in flown.events)


@pytest.mark.slow
def test_freight_narrows_the_price_gap(db):
    """The result that says the merchant profession works.

    With nothing moving between them, Shackleton ice sits near twice Peary's.
    Once ships run, the spread should fall toward the cost of the run. If it
    collapsed to nothing the model would be wrong; if it never moved, the
    haulers would not be working.
    """
    still = build(db)
    still.ships.clear()                       # a world with no freight
    for _ in range(RUN):
        still.run_tick()
    idle_gap = (still.books[SHACKLETON].last_price("ICE")
                / still.books[PEARY].last_price("ICE"))

    from market.db import connect
    flying = build(connect(":memory:"))
    for _ in range(RUN):
        flying.run_tick()
    flown_gap = (flying.books[SHACKLETON].last_price("ICE")
                 / flying.books[PEARY].last_price("ICE"))

    assert flown_gap < idle_gap
    assert flown_gap > 1.02        # freight is not free, so a gap survives


def test_a_voyage_conserves_everything(flown):
    flown.ledger.assert_conserved()


def test_ships_burn_propellant_they_paid_for(flown):
    """Where propellant demand comes from. Mass burned leaves the world."""
    from market.ledger import CONSUMPTION

    assert flown.ledger.balance(CONSUMPTION, "PROP") > 0


def test_no_ship_is_lost_in_transit(flown):
    for s in flown.ships:
        assert s.state in (ShipState.DOCKED, ShipState.IN_TRANSIT)
        if s.state is ShipState.IN_TRANSIT:
            assert s.arrive_tick and s.arrive_tick >= s.depart_tick
            assert 0.0 <= s.progress(flown.tick) <= 1.0
        else:
            assert s.destination is None


def test_propellant_reaches_a_node_that_cannot_make_it(flown):
    """Peary Ridge has no refinery. Everything it burns was flown in.

    Excluding propellant from haulable cargo stranded every hauler based
    there: it could never buy the fuel it needed to leave for the only place
    selling fuel.
    """
    assert flown.books[PEARY].last_price("PROP")
