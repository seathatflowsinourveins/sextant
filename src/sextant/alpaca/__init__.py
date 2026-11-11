"""Alpaca adapter: instrument provider, configs, factories and client shells.

The layout mirrors nautilus_trader@d53849b216e20f2c122ca01b4dd0da377638b186
``nautilus_trader/adapters/<venue>/`` (constants, config, providers, factories,
data, execution) so the same Strategy objects can run replay, sandbox and Alpaca
broker paper. alpaca-py imports in this package stay absolute
(``from alpaca.trading ...``): this package must never shadow the vendor
package, and a proof in ``tests/proofs/test_alpaca_adapter.py`` holds that line.

Source read 2026-11-10: NautilusTrader@d53849b examples/live/_template/__init__.py.
"""
