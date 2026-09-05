"""The world tick, end to end.

These run a real world for real ticks, so they are slower than the rest of
the suite. That is the point: the interesting failures in a simulation are
emergent, and a unit test of a single function would not have caught either
of the two bugs that mattered most while building this -- agents stacking
duplicate orders until escrow ate their capital, and a reference price with
no anchor ratcheting ice to six times its seed value.
"""

import pytest

from market.money import CREDIT
from sim.deposits import Deposit
from sim.seed_world import PEARY, SHACKLETON, TRANQUILLITATIS, build

SHORT = 40
MEDIUM = 120
#: Long enough for the helium-3 chain to make its first kilogram and sell it.
CHAIN = 90


def test_the_v1_roster_matches_the_bible(world):
    """"fifty bulk agents and five named ones." The named five are voice/."""
    assert len(world.firms) == 50
    assert set(world.books) == {SHACKLETON, PEARY, TRANQUILLITATIS}


def test_conservation_holds_every_single_tick(world):
    """`sim` never moves money itself, so this should be impossible to break.

    Asserted anyway, every tick, because a leak found one tick after it
    happens is debuggable and a leak found a week later is archaeology.
    """
    for _ in range(SHORT):
        world.run_tick()
        world.ledger.assert_conserved()


def test_a_seed_replays_identically(db):
    """CLAUDE.md: a bug report should be replayable."""
    from market.db import connect

    def fingerprint(seed):
        w = build(connect(":memory:"), seed=seed)
        for _ in range(SHORT):
            w.run_tick()
        return (
            [w.books[n].last_price(a) for n, a in
             ((SHACKLETON, "ICE"), (SHACKLETON, "PROP"), (PEARY, "ICE"))],
            [(e.tick, e.kind, e.subject) for e in w.events],
            sorted((f.id, w.ledger.balance(f.account, CREDIT)) for f in w.firms),
        )

    assert fingerprint(20260904) == fingerprint(20260904)
    assert fingerprint(20260904) != fingerprint(99999)


def test_prices_stay_in_a_sane_band(world):
    """The guard against the ratchet bug returning.

    Before mean reversion existed, ice walked to six times its anchor and
    kept going. Nothing here should sit an order of magnitude off its seed
    value while the roster is balanced.
    """
    for _ in range(MEDIUM):
        world.run_tick()
    for node, asset in ((SHACKLETON, "ICE"), (PEARY, "ICE"),
                        (SHACKLETON, "PROP"), (TRANQUILLITATIS, "REGOLITH")):
        last = world.books[node].last_price(asset)
        if last is None:
            continue
        anchor = world.ledger.asset(asset).base_value
        assert anchor / 5 < last < anchor * 5, f"{node} {asset} at {last}"


def test_two_nodes_reach_two_different_prices(world):
    """What v1 is for.

    seed-data: "v1 ships with the first three nodes only. That is enough for
    arbitrage, because arbitrage needs exactly two prices." Shackleton has
    refineries eating ice and Peary does not, so their ice prices must
    diverge -- and that gap is the merchant profession waiting for v2.
    """
    for _ in range(MEDIUM):
        world.run_tick()
    here = world.books[SHACKLETON].last_price("ICE")
    there = world.books[PEARY].last_price("ICE")
    assert here and there
    assert here != there


def test_earth_is_the_only_faucet_and_sinks_are_the_drain(world):
    """The macro loop. See earth.py and docs/DECISIONS.md D40."""
    minted_before = world.ledger.credits_in_existence()
    for _ in range(CHAIN):
        world.run_tick()
    assert world.ledger.credits_in_existence() == minted_before
    assert world.ledger.credits_destroyed() > 0
    assert world.earth.absorbed("HE3") > 0
    assert world.earth.credits_injected() > 0


def test_depletion_reduces_output(world):
    for _ in range(MEDIUM):
        world.run_tick()
    worked = [d for d in world.deposits.values() if d.extracted_kg > 0]
    assert worked
    assert all(d.richness < 1.0 for d in worked)


def test_a_flare_halts_extraction():
    """The bible's first shock: "Solar flares halt transit"."""
    from market.db import connect

    w = build(connect(":memory:"))
    w.run_tick()
    deposit = next(iter(w.deposits.values()))
    w.weather.flare_until = w.tick + 10
    before = deposit.extracted_kg
    for _ in range(5):
        w.run_tick()
    assert deposit.extracted_kg == before


def test_a_broke_firm_is_wound_up_and_its_estate_listed(world):
    """D37 part 1. No bailout, no reserve price -- the book decides."""
    from market.db import transaction

    victim = next(f for f in world.firms if f.upkeep_per_day > 0)
    creditor = next(f for f in world.firms if f is not victim)

    # Make the firm broke the way a firm actually goes broke: its money ends
    # up somewhere else. An earlier version of this test wrote a raw negative
    # posting straight into the ledger, which is unbalanced and is precisely
    # what the append-only design exists to refuse.
    with transaction(world.ledger.db):
        world.ledger.transfer(
            victim.account, creditor.account, CREDIT,
            world.ledger.balance(victim.account, CREDIT),
            kind="trade", game_time=world.game_time(), memo="test: ruin",
        )
    world.run_tick()
    assert victim.insolvent
    assert any(e.kind == "insolvency" and e.subject == victim.id
               for e in world.events)


def test_no_credits_are_created_when_a_firm_spins_off(world):
    """D37 part 3: the parent funds the child out of its own balance sheet."""
    parent = world.firms[0]
    child_account = "agent:test_child"
    before = world.ledger.credits_in_existence()
    parent_before = world.ledger.balance(parent.account, CREDIT)

    result = world.receiver.spin_off(parent, "test_child", child_account,
                                     world.game_time())

    assert world.ledger.credits_in_existence() == before
    assert world.ledger.balance(child_account, CREDIT) == result.capital
    assert (world.ledger.balance(parent.account, CREDIT)
            == parent_before - result.capital)
    world.ledger.assert_conserved()


def test_helium_three_actually_gets_produced_and_sold(world):
    """The whole v1 value chain, which needs sub-lot yields to work.

    A separator makes 0.6 kg of helium-3 from 400 tonnes of regolith. If
    production rounded to trading lots -- as it did in the first draft --
    this chain silently produces nothing forever.
    """
    for _ in range(CHAIN):
        world.run_tick()
    assert world.earth.absorbed("HE3") > 0
