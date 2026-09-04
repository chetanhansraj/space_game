"""Matching, pricing, escrow and the rules that stop clever people."""

import pytest

from market.book import ASK, BID
from market.errors import InsufficientFunds, InvalidPrice, InvalidQuantity
from market.money import CREDIT

from conftest import T0

TONNE = 1_000


def test_a_resting_order_escrows_immediately(db, ledger, book, trader):
    trader("alice", credits=1_000_000)
    book.place("ICE", BID, 400, 10 * TONNE, "alice", T0)
    # 10 lots at 400 = 4,000 credits, now held in escrow not by alice
    assert ledger.balance("alice") == 996_000
    assert book.best_bid("ICE") == 400


def test_an_ask_escrows_the_goods(db, ledger, book, trader):
    trader("miner", ICE=20 * TONNE)
    book.place("ICE", ASK, 500, 15 * TONNE, "miner", T0)
    assert ledger.balance("miner", "ICE") == 5 * TONNE
    assert book.best_ask("ICE") == 500


def test_you_cannot_promise_what_you_do_not_have(db, ledger, book, trader):
    trader("alice", credits=1_000)
    with pytest.raises(InsufficientFunds):
        book.place("ICE", BID, 400, 10 * TONNE, "alice", T0)  # needs 4,000
    assert ledger.balance("alice") == 1_000
    assert book.best_bid("ICE") is None
    ledger.assert_conserved()


def test_a_simple_crossing_trade_settles(db, ledger, book, trader):
    trader("miner", ICE=10 * TONNE)
    trader("alice", credits=100_000)
    book.place("ICE", ASK, 400, 10 * TONNE, "miner", T0)
    result = book.place("ICE", BID, 400, 10 * TONNE, "alice", T0)

    assert result.filled_kg == 10 * TONNE
    assert ledger.balance("alice", "ICE") == 10 * TONNE
    assert ledger.balance("miner", CREDIT) == 4_000
    assert ledger.balance("alice", CREDIT) == 96_000
    assert ledger.balance("miner", "ICE") == 0
    ledger.assert_conserved()


def test_the_resting_order_sets_the_price(db, ledger, book, trader):
    """A generous buyer keeps the difference; it is refunded from escrow."""
    trader("miner", ICE=10 * TONNE)
    trader("alice", credits=100_000)
    book.place("ICE", ASK, 400, 10 * TONNE, "miner", T0)
    result = book.place("ICE", BID, 900, 10 * TONNE, "alice", T0)

    assert result.fills[0].price == 400
    assert ledger.balance("miner", CREDIT) == 4_000
    # alice was willing to pay 9,000 but only paid 4,000
    assert ledger.balance("alice", CREDIT) == 96_000
    ledger.assert_conserved()


def test_price_priority(db, ledger, book, trader):
    trader("cheap", ICE=10 * TONNE)
    trader("dear", ICE=10 * TONNE)
    trader("alice", credits=100_000)
    book.place("ICE", ASK, 500, 10 * TONNE, "dear", T0)
    book.place("ICE", ASK, 380, 10 * TONNE, "cheap", T0)

    result = book.place("ICE", BID, 600, 10 * TONNE, "alice", T0)
    assert result.fills[0].price == 380
    assert ledger.balance("cheap", CREDIT) == 3_800
    assert ledger.balance("dear", CREDIT) == 0


def test_time_priority_among_equal_prices(db, ledger, book, trader):
    trader("first", ICE=10 * TONNE)
    trader("second", ICE=10 * TONNE)
    trader("alice", credits=100_000)
    book.place("ICE", ASK, 400, 10 * TONNE, "first", T0)
    book.place("ICE", ASK, 400, 10 * TONNE, "second", T0)

    book.place("ICE", BID, 400, 10 * TONNE, "alice", T0)
    assert ledger.balance("first", CREDIT) == 4_000
    assert ledger.balance("second", CREDIT) == 0


def test_partial_fills_leave_the_remainder_resting(db, ledger, book, trader):
    trader("miner", ICE=4 * TONNE)
    trader("alice", credits=100_000)
    book.place("ICE", ASK, 400, 4 * TONNE, "miner", T0)
    result = book.place("ICE", BID, 400, 10 * TONNE, "alice", T0)

    assert result.filled_kg == 4 * TONNE
    assert result.resting_kg == 6 * TONNE
    assert book.best_bid("ICE") == 400
    assert ledger.balance("alice", "ICE") == 4 * TONNE
    ledger.assert_conserved()


def test_an_order_sweeps_multiple_levels(db, ledger, book, trader):
    trader("a", ICE=5 * TONNE)
    trader("b", ICE=5 * TONNE)
    trader("c", ICE=5 * TONNE)
    trader("alice", credits=1_000_000)
    book.place("ICE", ASK, 300, 5 * TONNE, "a", T0)
    book.place("ICE", ASK, 400, 5 * TONNE, "b", T0)
    book.place("ICE", ASK, 500, 5 * TONNE, "c", T0)

    result = book.place("ICE", BID, 500, 15 * TONNE, "alice", T0)
    assert [f.price for f in result.fills] == [300, 400, 500]
    assert result.filled_kg == 15 * TONNE
    assert ledger.balance("alice", "ICE") == 15 * TONNE
    assert ledger.balance("alice", CREDIT) == 1_000_000 - (1_500 + 2_000 + 2_500)
    ledger.assert_conserved()


def test_cancelling_returns_exactly_what_is_left(db, ledger, book, trader):
    trader("miner", ICE=4 * TONNE)
    trader("alice", credits=100_000)
    book.place("ICE", ASK, 400, 4 * TONNE, "miner", T0)
    result = book.place("ICE", BID, 400, 10 * TONNE, "alice", T0)

    book.cancel(result.order_id, T0)
    # 4 t bought for 1,600; the other 6 t of escrow comes back
    assert ledger.balance("alice", CREDIT) == 100_000 - 1_600
    assert book.best_bid("ICE") is None
    ledger.assert_conserved()


def test_self_trading_is_skipped(db, ledger, book, trader):
    """One account per person, so trading with yourself is wash trading."""
    trader("alice", credits=100_000, ICE=10 * TONNE)
    book.place("ICE", ASK, 400, 10 * TONNE, "alice", T0)
    result = book.place("ICE", BID, 900, 10 * TONNE, "alice", T0)

    assert result.filled_kg == 0
    assert result.resting_kg == 10 * TONNE
    assert db.execute("SELECT COUNT(*) c FROM trade").fetchone()["c"] == 0
    ledger.assert_conserved()


def test_a_third_party_clears_a_crossed_book(db, ledger, book, trader):
    """The cost of skipping rather than rejecting, and it clears itself."""
    trader("alice", credits=100_000, ICE=10 * TONNE)
    trader("bob", credits=100_000)
    book.place("ICE", ASK, 400, 10 * TONNE, "alice", T0)
    book.place("ICE", BID, 900, 10 * TONNE, "alice", T0)

    result = book.place("ICE", BID, 400, 10 * TONNE, "bob", T0)
    assert result.filled_kg == 10 * TONNE
    ledger.assert_conserved()


def test_partial_lots_are_refused(db, ledger, book, trader):
    """Prices are per lot, so half a lot has no integer price."""
    trader("miner", ICE=10 * TONNE)
    with pytest.raises(InvalidQuantity):
        book.place("ICE", ASK, 400, 1_500, "miner", T0)   # 1.5 tonnes


def test_helium_trades_in_kilograms(db, ledger, book, trader):
    """PGM and He-3 have a 1 kg lot, per the seed data trade unit column."""
    trader("miner", HE3=5)
    trader("alice", credits=2_000_000)
    book.place("HE3", ASK, 236_000, 5, "miner", T0)
    result = book.place("HE3", BID, 236_000, 5, "alice", T0)
    assert result.filled_kg == 5
    assert ledger.balance("miner", CREDIT) == 5 * 236_000
    ledger.assert_conserved()


def test_zero_and_negative_are_refused(db, ledger, book, trader):
    trader("alice", credits=100_000)
    with pytest.raises(InvalidPrice):
        book.place("ICE", BID, 0, TONNE, "alice", T0)
    with pytest.raises(InvalidPrice):
        book.place("ICE", BID, -400, TONNE, "alice", T0)
    with pytest.raises(InvalidQuantity):
        book.place("ICE", BID, 400, 0, "alice", T0)
    with pytest.raises(InvalidQuantity):
        book.place("ICE", BID, 400, -TONNE, "alice", T0)


def test_escrow_accounts_always_end_empty(db, ledger, book, trader):
    """No escrow account may retain value once its order is closed."""
    trader("miner", ICE=10 * TONNE)
    trader("alice", credits=100_000)
    book.place("ICE", ASK, 400, 10 * TONNE, "miner", T0)
    book.place("ICE", BID, 700, 10 * TONNE, "alice", T0)

    rows = db.execute(
        "SELECT escrow_id FROM book_order WHERE status != 'OPEN'"
    ).fetchall()
    assert rows
    for row in rows:
        assert ledger.holdings(row["escrow_id"]) == {}
