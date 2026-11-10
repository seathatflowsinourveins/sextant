"""Alpaca venue identity and adapter defaults.

The venue constant and the unsupported-operation message follow
nautilus_trader@d53849b216e20f2c122ca01b4dd0da377638b186
``examples/live/_template/constants.py``. The ALPACA venue string is the one the
paper runners already use (``src/sextant/paper/native.py:108``). The credential
names follow the repo key store's per-account entries
(``scripts/keys.sh:26-31``): a config names the variable, it never holds it.
The ``sip`` feed default follows ``src/sextant/paper/alpaca_feed.py:60``.
"""

from nautilus_trader.model import Venue

VENUE = Venue.from_str("ALPACA")
NOT_IMPLEMENTED = "This operation is not implemented by the Alpaca adapter"

DEFAULT_API_KEY_ENV = "ALPACA_API_KEY"
DEFAULT_API_SECRET_ENV = "ALPACA_SECRET_KEY"  # noqa: S105 - a variable name, not a secret
DEFAULT_FEED = "sip"
DEFAULT_ACCOUNT_ID = "ALPACA-001"
