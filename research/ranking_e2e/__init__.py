"""Early-entry ranking e2e harness (research only; never imported by src/).

Part 1 of the early-entry ranking task. The harness reproduces the frozen K2
score and rank on the first sealed intraday cohort, then runs the arms the K3
preregistration froze (gap rule, mean baseline, keep-alive, Page CUSUM) plus
the K2 and hold-flat comparators. Code lives on a research branch because the
K3 protocol keeps evaluation code out of src/ (K3.8 item 6).
"""

__all__ = [
    "arms",
    "bars",
    "baseline",
    "cohort",
    "ledger",
    "metrics",
    "protocol",
    "runner",
    "seal",
]
