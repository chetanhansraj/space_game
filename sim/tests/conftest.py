import pytest

from market.db import connect
from sim.seed_world import build

T0 = "2190-01-01T00:00:00Z"


@pytest.fixture
def db():
    connection = connect(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def world(db):
    return build(db, seed=20260904, game_time=T0)


@pytest.fixture(scope="session", autouse=True)
def reference_ground():
    """Every town in the tests stands on the ground the rules were tuned on.

    A company's plot is drawn from its id, and a person's id is random, so
    without this a test about yards or caretakers would be played on
    different ground each run. Tests that are about plots themselves ask
    for ``real_ground`` and get the Moon as it is.
    """
    from sim import towngame
    patch = pytest.MonkeyPatch()
    patch.setattr(towngame, "_plot_for_real", towngame.plot_for,
                  raising=False)
    patch.setattr(towngame, "plot_for", lambda player_id, choice=0, *a, **k: {})
    # And every town in the tests keeps a day of its own, from a sunrise at
    # its founding, which is what the rules were tuned on: a test about
    # yards or caretakers should not pass or fail by where the Sun happened
    # to stand. Tests about the Sun itself ask for ``one_sun``.
    patch.setattr(towngame.TownOps, "_world_hour_real",
                  towngame.TownOps._world_hour, raising=False)
    patch.setattr(towngame.TownOps, "_morning_real",
                  towngame.TownOps._morning, raising=False)
    patch.setattr(towngame.TownOps, "_world_hour",
                  lambda self, plot: {"pace": towngame.PACE})
    patch.setattr(towngame.TownOps, "_morning", lambda self, plot: True)
    yield
    patch.undo()


@pytest.fixture
def real_ground(monkeypatch):
    """The Moon as it is: each company on its own plot."""
    from sim import towngame
    monkeypatch.setattr(towngame, "plot_for", towngame._plot_for_real)


@pytest.fixture
def one_sun(monkeypatch):
    """The Sun as it is: every town keeps time by where it stands (D93)."""
    from sim import towngame
    monkeypatch.setattr(towngame.TownOps, "_world_hour",
                        towngame.TownOps._world_hour_real)
    monkeypatch.setattr(towngame.TownOps, "_morning",
                        towngame.TownOps._morning_real)
