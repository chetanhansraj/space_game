"""Reproducibility.

CLAUDE.md: "Simulation runs must be reproducible from a seed. A bug report
should be replayable."
"""

from sim.rng import Streams


def test_same_seed_gives_same_numbers():
    a, b = Streams(42), Streams(42)
    for tick in range(200):
        assert a.unit("flare", tick) == b.unit("flare", tick)


def test_different_seeds_diverge():
    a, b = Streams(42), Streams(43)
    assert any(a.unit("flare", t) != b.unit("flare", t) for t in range(50))


def test_streams_are_independent():
    """The property that makes replays survive the code changing.

    Adding a new source of randomness must not shift the numbers every
    existing source draws. If streams shared state, inserting one draw would
    move every subsequent value and yesterday's bug report would replay into
    a different world.
    """
    s = Streams(42)
    before = [s.unit("flare", t) for t in range(100)]
    _ = [s.unit("a_new_feature", t) for t in range(500)]
    assert [s.unit("flare", t) for t in range(100)] == before


def test_draws_do_not_depend_on_order():
    """Any draw is recomputable without replaying the ticks before it."""
    s = Streams(7)
    forwards = [s.unit("x", t) for t in range(50)]
    backwards = [s.unit("x", t) for t in reversed(range(50))][::-1]
    assert forwards == backwards


def test_ranges_are_respected():
    s = Streams(1)
    for tick in range(300):
        assert 0.0 <= s.unit("u", tick) < 1.0
        assert 3 <= s.integer("i", tick, 3, 9) <= 9
        assert 0.9 <= s.spread("s", tick, 0.1) <= 1.1
