"""market -- order books, escrow, settlement, and the ledger.

The most correctness-critical code in the repository. Money movements are
transactional or they are bugs.

The organising idea is that **conservation is structural, not tested**. Every
economic event is a set of postings that sum to zero per asset, so credits and
goods cannot be created or destroyed by any code path -- not by a bug in the
matching engine, not by a partially applied transaction, not by a future
feature written by someone who has not read this file. The property tests do
not establish conservation; they check that the structure has not been
subverted.

Reading order: ``money`` for the units, ``ledger`` for the accounting model,
``book`` for the matching engine, ``authority`` for the Ark's standing quotes.
"""

__version__ = "0.1.0"
