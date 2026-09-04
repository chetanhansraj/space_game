"""orbital -- transfer costs between anchors.

A standalone service. Given two anchors and a departure time, it returns what
it costs to get from one to the other, as a Pareto curve of delta-v against
time of flight.

It knows nothing about the game. No commodities, no nodes, no docking fees,
no players, no database. Pure computation over ephemerides, plus a
precomputed lookup table.

See ``docs/DECISIONS.md`` for why it is shaped this way.
"""

__version__ = "0.1.0"
