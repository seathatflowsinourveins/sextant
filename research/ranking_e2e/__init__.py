"""Early-entry ranking e2e harness (research only; never imported by src/).

Part 1 of the early-entry ranking task. The harness reproduces the frozen K2
score and rank on the first sealed intraday cohort, then runs the K3 arms the
sealed inputs support (mean baseline, keep-alive, and the gap rule's fixed-mode
gap-only sub-arm) beside the K2 and hold-flat comparators; arm (a) as recorded
and Page CUSUM stay NOT_RUN with their reasons. Code lives on a research
branch because the K3 protocol keeps evaluation code out of src/ (K3.12).
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
