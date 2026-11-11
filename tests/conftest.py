import pytest

from app.engine import Engine
from app.lexicon import Lexicon
from app.settings import Settings
from app.store import Store

DAY = 86400.0


class FakeClock:
    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, days: float) -> None:
        self.now += days * DAY


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


@pytest.fixture
def lexicon(store, settings, clock):
    return Lexicon(store, settings, clock=clock)


@pytest.fixture
def engine(lexicon, settings):
    return Engine(lexicon, settings)


def texts(suggestions):
    return [s.text for s in suggestions]
