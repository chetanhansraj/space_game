"""The Ark Authority.

Two things it must achieve, from the bible: a lone player has a functioning
market on day one with no other participants, and its volume falls toward
zero on its own as real quotes arrive. Plus one thing the bible did not say
but invariant 3 requires: it must not be a printing press.
"""

import pytest

from market.authority import ACCOUNT as ARK
from market.authority import ASK_PERCENT, BID_PERCENT, ask_price, bid_price
from market.book import ASK, BID
from market.db import transaction
from market.ledger import GENESIS
from market.money import CREDIT

from conftest import T0

TONNE = 1_000


def test_quotes_sit_at_the_seed_value_floor_and_ceiling(db, ledger, book,
                                                        authority):
    with transaction(db):
        authority.endow("ICE", 200 * TONNE, T0)
    quote = authority.quote("ICE", T0)

    assert quote.bid_price == 400 * BID_PERCENT // 100   # 240
    assert quote.ask_price == 400 * ASK_PERCENT // 100   # 700
    assert book.best_bid("ICE") == 240
    assert book.best_ask("ICE") == 700
    ledger.assert_conserved()


def test_a_lone_player_has_a_working_market(db, ledger, book, authority,
                                            trader):
    """The day-one test. One player, no agents, no other humans."""
    with transaction(db):
        authority.endow("ICE", 500 * TONNE, T0)
    authority.quote("ICE", T0)
    trader("alice", credits=1_000_000, ICE=50 * TONNE)

    # She can sell into the floor...
    sale = book.place("ICE", ASK, 240, 50 * TONNE, "alice", T0)
    assert sale.filled_kg == 50 * TONNE
    assert ledger.balance("alice", CREDIT) == 1_000_000 + 50 * 240

    # ...and buy from the ceiling.
    buy = book.place("ICE", BID, 700, 20 * TONNE, "alice", T0)
    assert buy.filled_kg == 20 * TONNE
    assert ledger.balance("alice", "ICE") == 20 * TONNE
    ledger.assert_conserved()


def test_the_authority_never_mints_while_trading(db, ledger, book, authority,
                                                 trader):
    """Invariant 3. Everything it pays out, it had."""
    with transaction(db):
        authority.endow("ICE", 500 * TONNE, T0)

    treasury_before = ledger.balance(ARK, CREDIT)
    minted_before = ledger.credits_in_existence()

    authority.quote("ICE", T0, bid_lots=200)
    trader("alice", credits=0, ICE=200 * TONNE)

    # Quoting alone already moved the money: a standing bid is collateralised
    # from the moment it is placed, so the Authority's free balance drops
    # when it quotes, not when it fills. This is the same escrow every other
    # participant is subject to -- it gets no special treatment in the engine.
    value = 200 * 240
    assert ledger.balance(ARK, CREDIT) == treasury_before - value

    book.place("ICE", ASK, 240, 200 * TONNE, "alice", T0)

    # Every credit Alice received came out of that escrow, not thin air.
    assert ledger.credits_in_existence() == minted_before
    assert ledger.balance("alice", CREDIT) == value
    assert ledger.balance(ARK, CREDIT) == treasury_before - value
    # 500 t endowed, less the 50 t locked in its own standing ask, plus the
    # 200 t just bought. Both sides of a quote are collateralised.
    assert ledger.balance(ARK, "ICE") == 650 * TONNE
    ledger.assert_conserved()


def test_the_treasury_is_finite(db, ledger, book, trader):
    """A drained Authority stops bidding. That is an event, not a bug."""
    from market.authority import ArkAuthority

    ark = ArkAuthority(db, ledger, book)
    with transaction(db):
        ark.establish(T0, treasury=2_400)   # ten lots at the 240 floor
    quote = ark.quote("ICE", T0, bid_lots=100)
    assert quote.bid_kg == 10 * TONNE       # trimmed to what it can afford

    trader("alice", credits=0, ICE=10 * TONNE)
    book.place("ICE", ASK, 240, 10 * TONNE, "alice", T0)
    assert ledger.balance(ARK, CREDIT) == 0

    exhausted = ark.quote("ICE", T0, bid_lots=100)
    assert exhausted.bid_kg == 0
    assert book.best_bid("ICE") is None
    ledger.assert_conserved()


def test_funding_is_a_single_auditable_genesis_entry(db, ledger, authority):
    rows = db.execute(
        "SELECT t.kind, t.memo, p.amount FROM posting p JOIN txn t ON t.id = p.txn_id "
        "WHERE p.account_id = ? AND p.asset = ?", (GENESIS, CREDIT)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["kind"] == "genesis"
    assert "Ark Authority" in rows[0]["memo"]
    assert rows[0]["amount"] == -500_000_000


def test_endowment_is_booked_as_extraction_not_conjured(db, ledger, authority):
    from market.ledger import EXTRACTION

    with transaction(db):
        authority.endow("ICE", 300 * TONNE, T0)
    assert ledger.balance(ARK, "ICE") == 300 * TONNE
    assert ledger.balance(EXTRACTION, "ICE") == -300 * TONNE
    ledger.assert_conserved()


def test_real_quotes_take_priority_and_the_wheels_come_off(db, ledger, book,
                                                           authority, trader):
    """The mechanism by which the Authority fades. No switch is flipped."""
    with transaction(db):
        authority.endow("ICE", 500 * TONNE, T0)
    authority.quote("ICE", T0)

    trader("agent", credits=1_000_000, ICE=100 * TONNE)
    trader("alice", credits=1_000_000)

    # An agent quotes inside the Authority's spread: better ask than 700.
    book.place("ICE", ASK, 450, 100 * TONNE, "agent", T0)

    result = book.place("ICE", BID, 700, 100 * TONNE, "alice", T0)
    assert all(f.price == 450 for f in result.fills)
    assert ledger.balance("agent", CREDIT) == 1_000_000 + 100 * 450
    assert authority.share_of_volume("ICE") == 0.0
    ledger.assert_conserved()


@pytest.mark.parametrize("base,expected_bid,expected_ask", [
    (150, 90, 262),          # regolith
    (400, 240, 700),         # water ice
    (1_800, 1_080, 3_150),   # propellant
    (236_000, 141_600, 413_000),  # helium-3
])
def test_quote_arithmetic_is_exact_for_every_seed_commodity(
    base, expected_bid, expected_ask
):
    assert bid_price(base) == expected_bid
    assert ask_price(base) == expected_ask
