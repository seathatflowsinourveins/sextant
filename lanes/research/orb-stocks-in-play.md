# Source card: Stocks in Play opening-range breakout

Registry ID: `orb-stocks-in-play`. Status: **candidate; compute not admitted**.

Source: Zarattini, Barbon and Aziz, *A Profitable Day Trading Strategy for the
U.S. Equity Market*, SFI 24-98, [DOI 10.2139/ssrn.4729284](https://doi.org/10.2139/ssrn.4729284).
The [author-hosted PDF](https://concretumgroup.com/wp-content/uploads/2026/02/A-Profitable-Day-Trading-Strategy-For-The-U.S.-Equity-Market.pdf)
has SHA-256 `9423012e9f0199e3f6925c500725815c236d7ddbdd7500d50d10bac2be745e91`.
Its title page's first-version date is 2024-02-16; that does not verify when
this retrieved version became public. SPDX: **NOASSERTION**, informational.

Source `knowable_at`: `2026-11-06T15:28:06+00:00`, observed in this audit only.
Historical input `knowable_at`: **unknown**. No model generates this card's method;
the cited author method is the reference. Cutoff: this source observation.

Hypothesis for later replication: opening-window relative activity conditions
the subsequent breakout return. The paper uses a completed five-minute opening
range and ranks activity against prior opening windows. Its 2016–2023 sample
and reported Sharpe 2.81 are author results, not independent replication.
Its baseline is weaker; its successful long/short result cannot establish a
long-only result, sub-$1 coverage, premarket entry or first-second detection.

Needs: dated common-stock/ADR membership including delistings, unadjusted
intraday observations, action-aware prior windows, actual availability,
spread/impact/fee models and the canonical cumulative trial ledger. A current
price master or selected gainer list is insufficient. All remain unbound here.

OSAP/JKP mapping and HXZ t-screen: **unverified; no pass asserted**. Replication,
post-publication testing, stressed costs and ADR-0019 remain pending. No paper
threshold, short position, stop order, leverage or sizing is adopted.
