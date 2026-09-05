import pytest

from market.authority import ArkAuthority
from market.book import OrderBook
from market.db import connect, transaction
from market.ledger import Ledger
from market.seed import seed_assets

T0 = "2190-01-01T00:00:00Z"
NODE = "shackleton_depot"


@pytest.fixture
def db():
    connection = connect(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def ledger(db):
    book = Ledger(db)
    with transaction(db):
        book.bootstrap(T0)
        seed_assets(book)
    return book


@pytest.fixture
def book(db, ledger):
    return OrderBook(db, ledger, NODE)


@pytest.fixture
def trader(db, ledger):
    """Open a funded account. Credits come from genesis, goods from the ground."""
    def _make(name: str, credits: int = 0, **holdings: int) -> str:
        with transaction(db):
            ledger.open_account(name, "player", T0, label=name)
            if credits:
                ledger.mint(name, credits, T0, memo=f"test funding for {name}")
            for symbol, qty in holdings.items():
                ledger.extract(name, symbol, qty, T0, memo="test endowment")
        return name
    return _make


@pytest.fixture
def authority(db, ledger, book):
    ark = ArkAuthority(db, ledger, book)
    with transaction(db):
        ark.establish(T0, treasury=500_000_000)
    return ark
