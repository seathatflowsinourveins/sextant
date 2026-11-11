"""Alpaca venue identity and adapter defaults.

The venue constant and the unsupported-operation message follow
nautilus_trader@d53849b216e20f2c122ca01b4dd0da377638b186
``examples/live/_template/constants.py``. The ALPACA venue string is the one the
paper runners already use (``src/sextant/paper/native.py:108``). A config names
the credential environment variable, it never holds it
(``scripts/keys.sh:26-31``); the name has no adapter default, the caller names
it explicitly. The ``sip`` feed default follows
``src/sextant/paper/alpaca_feed.py:60``.
"""

from nautilus_trader.model import Venue

VENUE = Venue.from_str("ALPACA")
NOT_IMPLEMENTED = "This operation is not implemented by the Alpaca adapter"

DEFAULT_FEED = "sip"
