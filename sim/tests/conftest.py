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
    patch.setattr(towngame, "plot_for", lambda player_id: {})
    yield
    patch.undo()


@pytest.fixture
def real_ground(monkeypatch):
    """The Moon as it is: each company on its own plot."""
    from sim import towngame
    monkeypatch.setattr(towngame, "plot_for", towngame._plot_for_real)
