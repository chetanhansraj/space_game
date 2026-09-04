"""Market errors.

All of these are refusals, not failures. Every one of them means the market
declined to do something and left the world exactly as it was. There is no
error in this module that can be raised halfway through a state change --
that is what the transaction boundary in ``db`` is for.
"""

from __future__ import annotations


class MarketError(Exception):
    """Base for everything this package refuses to do."""


class InsufficientFunds(MarketError):
    """The account does not hold enough of an asset to cover the request."""


class InvalidQuantity(MarketError):
    """Quantity is not a positive whole number of lots."""


class InvalidPrice(MarketError):
    """Price is not a positive whole number of credits."""


class UnknownAsset(MarketError):
    """No such commodity."""


class UnknownAccount(MarketError):
    """No such account."""


class UnknownOrder(MarketError):
    """No such order, or it is no longer open."""


class SelfTrade(MarketError):
    """An account tried to trade with itself.

    Prevented rather than tolerated. One account per person is an invariant,
    and wash trading against yourself is how a player would manufacture a
    price history to sell into.
    """


class LedgerImbalance(MarketError):
    """A transaction's postings do not sum to zero.

    This should be impossible to trigger from outside the package. If it is
    ever raised in production, the correct response is to stop the world, not
    to retry.
    """
