import pytest


@pytest.fixture(autouse=True)
def _fresh_yahoo_guard():
    """The Yahoo earnings guard is run-level state (stock_screen.YAHOO_EARN_GUARD): start every test closed."""
    try:
        import stock_screen as ss
    except Exception:
        yield
        return
    ss.YAHOO_EARN_GUARD.reset()
    yield
    ss.YAHOO_EARN_GUARD.reset()
