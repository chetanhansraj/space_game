"""Units, and the arithmetic that must never round.

Two rules from CLAUDE.md drive everything here:

    Money is integer credits. Never floats.
    Mass is kilograms in the database, displayed in tonnes.

Those two are in tension. Regolith is 150 cr per tonne, which is 0.15 cr per
kilogram -- not representable as an integer. Buying one kilogram of regolith
has no integer price, and a market that silently rounds it has invented or
destroyed value.

The resolution is that **orders are priced per lot and sized in whole lots**,
which is also how real commodity markets work. A lot is one tonne for bulk
goods and one kilogram for platinum group metals and helium-3, matching the
trade units in docs/seed-data.md. Quantities are still *stored* in kilograms
as CLAUDE.md requires, but they are constrained to whole multiples of the lot
mass, so converting between the two is exact in both directions and the cost
of a fill is a plain integer multiplication.

There is no float anywhere in this package. There is no rounding anywhere in
this package. If a calculation cannot be done exactly in integers, it is
refused.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import InvalidPrice, InvalidQuantity

#: The credit is the base unit and is not subdivided. One credit is one
#: gigajoule of delivered energy. Trade is quoted in kcr and Mcr for display
#: only; nothing is ever stored in them.
CREDIT = "CREDIT"

KG_PER_TONNE = 1_000


@dataclass(frozen=True)
class Asset:
    """A tradeable commodity.

    ``lot_mass_kg`` is the smallest tradeable quantity and the denomination
    of the quoted price. ``base_value`` is the seed-data anchor price per
    lot, used by the Ark Authority to derive its standing quotes.
    """

    symbol: str
    name: str
    lot_mass_kg: int
    base_value: int

    def lots(self, qty_kg: int) -> int:
        """Whole lots in a quantity. Refuses anything that does not divide."""
        if qty_kg <= 0 or qty_kg % self.lot_mass_kg != 0:
            raise InvalidQuantity(
                f"{qty_kg} kg is not a positive whole number of "
                f"{self.lot_mass_kg} kg lots of {self.symbol}"
            )
        return qty_kg // self.lot_mass_kg

    def kg(self, lots: int) -> int:
        if lots <= 0:
            raise InvalidQuantity(f"{lots} is not a positive lot count")
        return lots * self.lot_mass_kg

    def cost(self, price_per_lot: int, qty_kg: int) -> int:
        """Exact cost in credits. Integer multiplication, never division."""
        return check_price(price_per_lot) * self.lots(qty_kg)


def check_price(price: int) -> int:
    if not isinstance(price, int) or isinstance(price, bool):
        raise InvalidPrice(f"price must be an int, got {type(price).__name__}")
    if price <= 0:
        raise InvalidPrice(f"price must be positive, got {price}")
    return price


def check_quantity(qty_kg: int) -> int:
    if not isinstance(qty_kg, int) or isinstance(qty_kg, bool):
        raise InvalidQuantity(f"quantity must be an int, got {type(qty_kg).__name__}")
    if qty_kg <= 0:
        raise InvalidQuantity(f"quantity must be positive, got {qty_kg}")
    return qty_kg


def format_credits(amount: int) -> str:
    """Display only. Never parse this back."""
    if abs(amount) >= 1_000_000:
        return f"{amount / 1_000_000:.2f} Mcr"
    if abs(amount) >= 1_000:
        return f"{amount / 1_000:.1f} kcr"
    return f"{amount} cr"


def format_mass(qty_kg: int) -> str:
    """Display only. Kilograms are what is stored."""
    if qty_kg >= KG_PER_TONNE:
        return f"{qty_kg / KG_PER_TONNE:,.1f} t"
    return f"{qty_kg} kg"
