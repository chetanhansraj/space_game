"""The Transfer value type.

Deliberately its own module with no dependencies beyond the standard library.

Invariant 4 says a request handler must never solve a Lambert problem. The
read path -- ``table.store`` and the API above it -- needs to hand back
transfers, so it needs this type. If the type lived alongside the solving
code, importing it would drag the solver into the read path, and a future
request handler would be one function call away from melting the server.

Keeping it here means ``tests/test_determinism.py`` can assert that importing
the read path does not import a solver at all, which turns the invariant from
a rule people have to remember into a property of the import graph.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Transfer:
    """A costed transfer between two anchors."""

    tof: float                   # seconds
    dv_depart: float             # m/s, hyperbolic excess at departure
    dv_arrive: float             # m/s, hyperbolic excess at arrival
    dv_fixed: float              # m/s, surface and gravity-well budgets
    revolutions: int

    @property
    def dv_total(self) -> float:
        return self.dv_depart + self.dv_arrive + self.dv_fixed

    @property
    def c3_depart(self) -> float:
        """Characteristic energy at departure, m^2/s^2.

        Published for real missions, so this is the quantity the validation
        tests compare against.
        """
        return self.dv_depart**2
