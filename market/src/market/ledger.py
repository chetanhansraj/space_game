"""The ledger. Append-only, double-entry, balances derived.

Every economic mutation is a transaction made of postings, and the postings
of a transaction sum to zero for each asset they touch. That single rule is
what makes conservation structural: there is no way to write a posting that
creates value, because the write is rejected unless something else in the
same transaction destroys exactly as much.

Value enters and leaves the world only through named world accounts, and
because they are ordinary accounts on the same ledger, every credit ever
created and every credit ever destroyed is a queryable number:

``world:genesis``      The only source of credits. Its balance is the negative
                       of every credit in existence. Nothing but world setup
                       and institutional funding may post against it, and each
                       time it is used the reason is in the transaction memo.

``world:sink``         Where credits go to die: fuel burn, maintenance,
                       docking fees, wages, licensing, tariffs, insurance,
                       wear, claim renewal. Invariant 7 says every feature
                       that creates credits must ship with its matching sink;
                       this account is how you check whether it did.

``world:extraction``   The source of mined commodities. Goes negative as mass
                       is pulled out of the ground.

``world:consumption``  The sink for consumed commodities -- life support,
                       propellant burned, food eaten.

Balances are never stored as a source of truth. Asking for a balance sums the
postings -- the ones since the last checkpoint, on top of a checkpoint that is
itself nothing but a sum of the postings before it (schema migration 3). The
postings are the one source of truth about what an account holds, and
``verify_checkpoints`` proves the cache agrees with them.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from .errors import (
    InsufficientFunds,
    LedgerImbalance,
    UnknownAccount,
    UnknownAsset,
)
from .money import CREDIT, Asset

GENESIS = "world:genesis"
SINK = "world:sink"
EXTRACTION = "world:extraction"
CONSUMPTION = "world:consumption"

WORLD_ACCOUNTS = (GENESIS, SINK, EXTRACTION, CONSUMPTION)


@dataclass(frozen=True)
class Posting:
    """One leg of a transaction. Signed."""

    account_id: str
    asset: str
    amount: int


class Ledger:
    """Accounting over a connection. Does not manage its own transactions.

    Every mutating method here must be called inside ``db.transaction``. That
    is deliberate: it forces the caller to decide the atomicity boundary,
    which for a fill spans postings, order updates and the trade record.
    """

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    # -- setup ---------------------------------------------------------

    def bootstrap(self, game_time: str) -> None:
        """Create the world accounts. Idempotent."""
        for account_id in WORLD_ACCOUNTS:
            self.db.execute(
                "INSERT OR IGNORE INTO account (id, kind, label, created_at) "
                "VALUES (?, 'world', ?, ?)",
                (account_id, account_id.split(":", 1)[1], game_time),
            )
        self.db.execute(
            "INSERT OR IGNORE INTO asset (symbol, name, lot_mass_kg, base_value) "
            "VALUES (?, 'Credit', 1, 1)",
            (CREDIT,),
        )

    def register_asset(self, asset: Asset) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO asset (symbol, name, lot_mass_kg, base_value) "
            "VALUES (?, ?, ?, ?)",
            (asset.symbol, asset.name, asset.lot_mass_kg, asset.base_value),
        )

    def asset(self, symbol: str) -> Asset:
        row = self.db.execute(
            "SELECT symbol, name, lot_mass_kg, base_value FROM asset WHERE symbol = ?",
            (symbol,),
        ).fetchone()
        if row is None:
            raise UnknownAsset(symbol)
        return Asset(row["symbol"], row["name"], row["lot_mass_kg"], row["base_value"])

    def open_account(self, account_id: str, kind: str, game_time: str,
                     label: str = "") -> str:
        self.db.execute(
            "INSERT INTO account (id, kind, label, created_at) VALUES (?, ?, ?, ?)",
            (account_id, kind, label, game_time),
        )
        return account_id

    def account_kind(self, account_id: str) -> str:
        row = self.db.execute(
            "SELECT kind FROM account WHERE id = ?", (account_id,)
        ).fetchone()
        if row is None:
            raise UnknownAccount(account_id)
        return row["kind"]

    # -- reading -------------------------------------------------------

    def _mark(self) -> int:
        return int(self.db.execute(
            "SELECT through_posting FROM checkpoint_mark WHERE id = 1"
        ).fetchone()[0])

    def balance(self, account_id: str, asset: str = CREDIT) -> int:
        """Checkpoint plus every posting since. See schema migration 3."""
        row = self.db.execute(
            "SELECT"
            " COALESCE((SELECT amount FROM balance_checkpoint"
            "           WHERE account_id = :a AND asset = :s), 0)"
            " + COALESCE((SELECT SUM(amount) FROM posting"
            "           WHERE account_id = :a AND asset = :s AND id >"
            "           (SELECT through_posting FROM checkpoint_mark"
            "            WHERE id = 1)), 0) AS b",
            {"a": account_id, "s": asset},
        ).fetchone()
        return int(row["b"])

    def holdings(self, account_id: str) -> dict[str, int]:
        """Every non-zero balance an account holds."""
        rows = self.db.execute(
            "SELECT asset, SUM(amount) AS b FROM ("
            "  SELECT asset, amount FROM balance_checkpoint"
            "  WHERE account_id = :a"
            "  UNION ALL"
            "  SELECT asset, amount FROM posting WHERE account_id = :a"
            "  AND id > (SELECT through_posting FROM checkpoint_mark"
            "            WHERE id = 1)"
            ") GROUP BY asset HAVING b != 0",
            {"a": account_id},
        ).fetchall()
        return {r["asset"]: int(r["b"]) for r in rows}

    def total_by_asset(self) -> dict[str, int]:
        """Sum of every posting, per asset. Must be zero for all of them."""
        rows = self.db.execute(
            "SELECT asset, SUM(amount) AS total FROM ("
            "  SELECT asset, amount FROM balance_checkpoint"
            "  UNION ALL"
            "  SELECT asset, amount FROM posting"
            "  WHERE id > (SELECT through_posting FROM checkpoint_mark"
            "              WHERE id = 1)"
            ") GROUP BY asset"
        ).fetchall()
        return {r["asset"]: int(r["total"]) for r in rows}

    def checkpoint(self) -> int:
        """Fold every posting since the last mark into the checkpoint.

        Must run inside a transaction, like every other write here. The new
        mark is the highest posting id that exists at the moment it runs, so
        a transaction can never straddle it: postings are only ever read
        after their transaction committed or from inside it.

        Returns how many postings were folded in.
        """
        lo = self._mark()
        hi = int(self.db.execute(
            "SELECT COALESCE(MAX(id), 0) FROM posting").fetchone()[0])
        if hi <= lo:
            return 0
        self.db.execute(
            "INSERT INTO balance_checkpoint (account_id, asset, amount) "
            "SELECT account_id, asset, SUM(amount) FROM posting "
            "WHERE id > ? AND id <= ? GROUP BY account_id, asset "
            "ON CONFLICT (account_id, asset) "
            "DO UPDATE SET amount = amount + excluded.amount",
            (lo, hi),
        )
        # A missing row means zero. Every closed escrow account would
        # otherwise leave a row behind forever.
        self.db.execute("DELETE FROM balance_checkpoint WHERE amount = 0")
        self.db.execute(
            "UPDATE checkpoint_mark SET through_posting = ? WHERE id = 1",
            (hi,))
        return hi - lo

    def verify_checkpoints(self) -> list[tuple[str, str, int, int]]:
        """Recompute the checkpoint from the raw ledger and compare.

        Returns every (account, asset, cached, true) that disagrees -- which
        must always be an empty list. Slow on purpose: it reads the whole
        history. For tests and for audits, never for the tick.
        """
        mark = self._mark()
        rows = self.db.execute(
            "SELECT account_id, asset, SUM(c) AS cached, SUM(t) AS truth"
            " FROM ("
            "  SELECT account_id, asset, amount AS c, 0 AS t"
            "  FROM balance_checkpoint"
            "  UNION ALL"
            "  SELECT account_id, asset, 0, amount FROM posting WHERE id <= ?"
            ") GROUP BY account_id, asset HAVING SUM(c) != SUM(t)",
            (mark,),
        ).fetchall()
        return [(r["account_id"], r["asset"], int(r["cached"]), int(r["truth"]))
                for r in rows]

    def assert_conserved(self) -> None:
        """The invariant, checkable at any moment.

        Cheap enough to call in tests after every single operation, which is
        exactly what the property tests do.
        """
        bad = {a: t for a, t in self.total_by_asset().items() if t != 0}
        if bad:
            raise LedgerImbalance(f"assets not conserved: {bad}")

    def credits_in_existence(self) -> int:
        """Every credit that exists, from the genesis account's own records."""
        return -self.balance(GENESIS, CREDIT)

    def credits_destroyed(self) -> int:
        """Every credit removed from the world by a sink."""
        return self.balance(SINK, CREDIT)

    # -- writing -------------------------------------------------------

    def post(
        self,
        kind: str,
        game_time: str,
        postings: list[Posting],
        ref: str | None = None,
        memo: str = "",
    ) -> int:
        """Write one transaction. Refuses anything that does not balance.

        Two checks, both of which reject the whole transaction:

        1. Postings sum to zero per asset. Without this, value is created.
        2. No non-world account is left negative. Without this, an account
           can spend what it does not have, and the shortfall silently
           becomes everyone else's inflation.
        """
        if not postings:
            raise LedgerImbalance("a transaction must have at least one posting")

        totals: dict[str, int] = defaultdict(int)
        deltas: dict[tuple[str, str], int] = defaultdict(int)
        for entry in postings:
            if not isinstance(entry.amount, int) or isinstance(entry.amount, bool):
                raise LedgerImbalance(
                    f"posting amount must be an int, got {type(entry.amount).__name__}"
                )
            totals[entry.asset] += entry.amount
            deltas[(entry.account_id, entry.asset)] += entry.amount

        unbalanced = {a: t for a, t in totals.items() if t != 0}
        if unbalanced:
            raise LedgerImbalance(
                f"postings do not sum to zero per asset: {unbalanced}"
            )

        for (account_id, asset), delta in deltas.items():
            if delta >= 0:
                continue
            if self.account_kind(account_id) == "world":
                continue  # world accounts are where value enters and leaves
            resulting = self.balance(account_id, asset) + delta
            if resulting < 0:
                raise InsufficientFunds(
                    f"{account_id} would hold {resulting} of {asset}"
                )

        cursor = self.db.execute(
            "INSERT INTO txn (kind, game_time, ref, memo) VALUES (?, ?, ?, ?)",
            (kind, game_time, ref, memo),
        )
        txn_id = int(cursor.lastrowid)
        self.db.executemany(
            "INSERT INTO posting (txn_id, account_id, asset, amount) "
            "VALUES (?, ?, ?, ?)",
            [(txn_id, p.account_id, p.asset, p.amount) for p in postings],
        )
        return txn_id

    def transfer(
        self,
        source: str,
        destination: str,
        asset: str,
        amount: int,
        kind: str,
        game_time: str,
        ref: str | None = None,
        memo: str = "",
    ) -> int:
        """Move value between two accounts. The common case."""
        if amount <= 0:
            raise LedgerImbalance(f"transfer amount must be positive, got {amount}")
        return self.post(
            kind,
            game_time,
            [
                Posting(source, asset, -amount),
                Posting(destination, asset, amount),
            ],
            ref=ref,
            memo=memo,
        )

    def mint(self, destination: str, amount: int, game_time: str,
             memo: str) -> int:
        """Bring credits into existence. Genesis only, and always explained.

        Every use of this is a permanent, auditable entry against
        ``world:genesis``. There is no other way to create a credit, and
        nothing in the trading path calls it.
        """
        return self.transfer(GENESIS, destination, CREDIT, amount,
                             kind="genesis", game_time=game_time, memo=memo)

    def burn(self, source: str, amount: int, game_time: str, memo: str,
             ref: str | None = None) -> int:
        """Remove credits from the world. Invariant 7's other half."""
        return self.transfer(source, SINK, CREDIT, amount,
                             kind="sink", game_time=game_time, ref=ref, memo=memo)

    def extract(self, destination: str, asset: str, qty_kg: int,
                game_time: str, memo: str = "") -> int:
        """Mass out of the ground and into an account."""
        return self.transfer(EXTRACTION, destination, asset, qty_kg,
                             kind="extraction", game_time=game_time, memo=memo)

    def consume(self, source: str, asset: str, qty_kg: int, game_time: str,
                memo: str = "") -> int:
        """Mass used up: life support, propellant burned, food eaten."""
        return self.transfer(source, CONSUMPTION, asset, qty_kg,
                             kind="consumption", game_time=game_time, memo=memo)
