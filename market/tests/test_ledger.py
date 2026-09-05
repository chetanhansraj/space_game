"""The ledger's own rules.

Everything else in the package is built on the guarantee that a transaction
either balances and applies, or does not apply at all.
"""

import pytest

from market.db import transaction
from market.errors import InsufficientFunds, LedgerImbalance
from market.ledger import CONSUMPTION, EXTRACTION, GENESIS, SINK, Posting
from market.money import CREDIT

from conftest import T0


def test_balances_are_derived_not_stored(db, ledger, trader):
    trader("alice", credits=100_000)
    assert ledger.balance("alice") == 100_000
    columns = [r[1] for r in db.execute("PRAGMA table_info(account)")]
    assert "balance" not in columns
    assert not any("balance" in c for c in columns)


def test_unbalanced_postings_are_refused(db, ledger, trader):
    trader("alice", credits=1_000)
    trader("bob")
    with pytest.raises(LedgerImbalance):
        with transaction(db):
            ledger.post("trade", T0, [
                Posting("alice", CREDIT, -500),
                Posting("bob", CREDIT, 400),   # 100 credits vanish
            ])
    assert ledger.balance("alice") == 1_000
    assert ledger.balance("bob") == 0


def test_creating_value_is_refused(db, ledger, trader):
    trader("alice", credits=1_000)
    trader("bob")
    with pytest.raises(LedgerImbalance):
        with transaction(db):
            ledger.post("trade", T0, [
                Posting("alice", CREDIT, -500),
                Posting("bob", CREDIT, 600),   # 100 credits appear
            ])
    assert ledger.credits_in_existence() == 1_000


def test_accounts_cannot_go_negative(db, ledger, trader):
    trader("alice", credits=100)
    trader("bob")
    with pytest.raises(InsufficientFunds):
        with transaction(db):
            ledger.transfer("alice", "bob", CREDIT, 101,
                            kind="trade", game_time=T0)
    assert ledger.balance("alice") == 100


def test_world_accounts_may_go_negative(db, ledger, trader):
    """That is what they are for -- genesis is negative by construction."""
    trader("alice", credits=50_000)
    assert ledger.balance(GENESIS, CREDIT) == -50_000
    assert ledger.credits_in_existence() == 50_000
    ledger.assert_conserved()


def test_a_rollback_leaves_nothing_behind(db, ledger, trader):
    trader("alice", credits=1_000)
    trader("bob")
    with pytest.raises(RuntimeError):
        with transaction(db):
            ledger.transfer("alice", "bob", CREDIT, 400,
                            kind="trade", game_time=T0)
            raise RuntimeError("something went wrong mid-settlement")
    assert ledger.balance("alice") == 1_000
    assert ledger.balance("bob") == 0
    ledger.assert_conserved()


def test_postings_cannot_be_updated(db, ledger, trader):
    """Append-only, enforced by the database rather than by convention."""
    trader("alice", credits=1_000)
    with pytest.raises(Exception, match="append-only"):
        db.execute("UPDATE posting SET amount = 999999 WHERE account_id = 'alice'")


def test_postings_cannot_be_deleted(db, ledger, trader):
    trader("alice", credits=1_000)
    with pytest.raises(Exception, match="append-only"):
        db.execute("DELETE FROM posting WHERE account_id = 'alice'")


def test_sinks_remove_credits_from_the_world(db, ledger, trader):
    """Invariant 7. The sink balance is the audit of money leaving."""
    trader("alice", credits=10_000)
    with transaction(db):
        ledger.burn("alice", 800, T0, memo="docking fee, Shackleton Depot")
    assert ledger.balance("alice") == 9_200
    assert ledger.credits_destroyed() == 800
    assert ledger.credits_in_existence() == 10_000  # minted, some now in the sink
    ledger.assert_conserved()


def test_extraction_and_consumption_conserve_mass(db, ledger, trader):
    trader("miner", ICE=50_000)
    assert ledger.balance("miner", "ICE") == 50_000
    assert ledger.balance(EXTRACTION, "ICE") == -50_000
    with transaction(db):
        ledger.consume("miner", "ICE", 12_000, T0, memo="life support")
    assert ledger.balance("miner", "ICE") == 38_000
    assert ledger.balance(CONSUMPTION, "ICE") == 12_000
    ledger.assert_conserved()


def test_float_amounts_are_refused(db, ledger, trader):
    """Money is integer credits. Never floats."""
    trader("alice", credits=1_000)
    trader("bob")
    with pytest.raises(LedgerImbalance):
        with transaction(db):
            ledger.post("trade", T0, [
                Posting("alice", CREDIT, -0.5),
                Posting("bob", CREDIT, 0.5),
            ])
