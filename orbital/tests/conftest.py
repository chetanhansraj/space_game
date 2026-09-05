import datetime as dt
from pathlib import Path

import pytest

from orbital.anchors import AnchorRegistry
from orbital.ephemeris import get_backend

DATA = Path(__file__).resolve().parents[1] / "data"
UTC = dt.timezone.utc


@pytest.fixture(scope="session")
def de421():
    return get_backend("legacy")


@pytest.fixture(scope="session")
def analytic():
    return get_backend("analytic")


@pytest.fixture(scope="session")
def registry(de421):
    return AnchorRegistry.load(
        de421, DATA / "anchors.toml", DATA / "smallbody_elements.json"
    )
