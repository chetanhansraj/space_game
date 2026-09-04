"""Seeding a market from docs/seed-data.md.

The commodity table lives in the design documents, not in code. This module
is the one place that transcribes it, so a change to the seed data is a
change to one dict.

Lot masses come from the "Trade unit" column: a tonne for bulk goods, a
kilogram for platinum group metals and helium-3. Base values are the anchor
prices, in credits per lot, which is what the Ark Authority derives its
standing quotes from.
"""

from __future__ import annotations

from .ledger import Ledger
from .money import KG_PER_TONNE, Asset

#: docs/seed-data.md section 2. Ten commodities -- see DECISIONS.md D9.
COMMODITIES: tuple[Asset, ...] = (
    Asset("REGOLITH", "Regolith / silicates", KG_PER_TONNE, 150),
    Asset("ICE",      "Water ice",            KG_PER_TONNE, 400),
    Asset("PROP",     "Propellant (LOX/LH2)", KG_PER_TONNE, 1_800),
    Asset("IRON",     "Iron / nickel",        KG_PER_TONNE, 2_500),
    Asset("VOLATILE", "Volatiles (C, N, NH3)", KG_PER_TONNE, 6_000),
    Asset("FOOD",     "Food",                 KG_PER_TONNE, 12_000),
    Asset("RAREEARTH", "Rare earths",         KG_PER_TONNE, 90_000),
    Asset("GOODS",    "Manufactured goods",   KG_PER_TONNE, 45_000),
    Asset("PGM",      "Platinum group",       1,            1_200),
    Asset("HE3",      "Helium-3",             1,            236_000),
)

#: v1 ships three lunar nodes. docs/seed-data.md section 1.
V1_NODES = ("shackleton_depot", "peary_ridge", "tranquillitatis_flats")


def seed_assets(ledger: Ledger) -> None:
    for asset in COMMODITIES:
        ledger.register_asset(asset)


def by_symbol(symbol: str) -> Asset:
    for asset in COMMODITIES:
        if asset.symbol == symbol:
            return asset
    raise KeyError(symbol)
