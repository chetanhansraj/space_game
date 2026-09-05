"""The precomputed transfer table.

Invariant 4: transfers are read from precomputed tables, never solved on
request. A Lambert sweep costs tens of milliseconds; a few hundred players
checking routes would melt the server. So the sweep happens on a schedule
and every route query becomes an indexed lookup.
"""
