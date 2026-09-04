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
