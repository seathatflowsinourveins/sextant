# Carried from seathatflowsinourveins/northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa:
# tests/data/test_sharadar.py, its fixtures and every test that exercises only dated_intervals or
# interval_coverage, verbatim but for the import path. Bridge, snapshot and CLI tests stay upstream.
"""Offline Sharadar interval fixtures; no key or network."""

import json
from datetime import date

import pytest

START = date(2020, 1, 1)


END = date(2026, 10, 24)


TICKER_FIELDS = (
    "table",
    "permaticker",
    "ticker",
    "exchange",
    "category",
    "relatedtickers",
    "firstpricedate",
    "lastpricedate",
    "isdelisted",
)


ACTION_FIELDS = ("date", "action", "ticker", "name", "value", "contraticker", "contraname")


def ticker(symbol: str, identity: str, first: str, last: str, **extra: str) -> dict[str, str]:
    return dict(
        table="stocks",
        permaticker=identity,
        ticker=symbol,
        exchange="NYSE",
        category="Domestic Common Stock",
        relatedtickers="",
        firstpricedate=first,
        lastpricedate=last,
        isdelisted="Y",
        **extra,
    )


def population_counts(
    inputs: int, included: int, outside: int, excluded: int, intervals: int
) -> dict[str, int]:
    return {
        "input_security_count": inputs,
        "included_security_count": included,
        "outside_window_security_count": outside,
        "excluded_security_count": excluded,
        "dated_interval_count": intervals,
    }


def action(
    day: str, kind: str, symbol: str, contra: str = "N/A", venue: str = "N/A"
) -> dict[str, str]:
    return dict(
        date=day,
        action=kind,
        ticker=symbol,
        name="SYNTHETIC",
        value="",
        contraticker=contra,
        contraname=venue,
    )


def fixtures() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    tickers = [
        ticker("SIVBQ", "100", "2020-01-02", "2023-09-29"),
        ticker("RPT1", "200", "2020-01-02", "2024-01-02"),
        ticker("RPT", "201", "2024-01-03", "2026-10-24"),
        ticker("CASH", "300", "2020-01-02", "2022-10-27"),
        ticker("FAILQ", "400", "2020-01-02", "2023-05-02"),
    ]
    tickers[0].update(exchange="NASDAQ", relatedtickers="SIVB SIVBO SIVBP SIVPQ")
    tickers[1]["relatedtickers"] = "RPT"
    tickers[2]["isdelisted"] = "N"
    actions = [
        action("2023-03-28", "tickerchangefrom", "SIVBQ", "SIVB"),
        action("2023-03-28", "tickerchangeto", "SIVBQ", "SIVBQ"),
        action("2023-03-28", "exchangefrom", "SIVBQ", venue="NASDAQ"),
        action("2023-03-28", "exchangeto", "SIVBQ", venue="OTC"),
        action("2023-09-29", "bankruptcyliquidation", "SIVBQ"),
        action("2024-01-02", "mergerto", "RPT1", "KIM"),
        action("2022-10-27", "acquisitioncash", "CASH", "BUYER"),
        action("2022-10-27", "delisted", "CASH"),
        action("2023-05-02", "bankruptcyliquidation", "FAILQ"),
        action("2023-05-02", "delisted", "FAILQ"),
    ]
    actions[6]["value"] = "54.20"
    actions.extend(action(row["firstpricedate"], "listed", row["ticker"]) for row in tickers)
    return tickers, actions


def test_unpaired_changes_and_unproven_suffix_fail_closed_per_security() -> None:
    from sextant.data.sharadar_master import interval_coverage

    tickers, actions = fixtures()
    for broken, reason in (
        (actions[1:], "ambiguous_tickerchange_pair"),
        ([a for a in actions if a["action"] != "exchangeto"], "ambiguous_exchange_pair"),
    ):
        coverage = interval_coverage(tickers, broken, start=START, end=END)
        assert coverage.exclusions == {"SIVBQ": reason}
        assert {row.dataset_ticker for row in coverage.intervals} == {
            "RPT1",
            "RPT",
            "CASH",
            "FAILQ",
        }
    coverage = interval_coverage(
        [tickers[1]], [row for row in actions if row["ticker"] == "RPT1"], start=START, end=END
    )
    assert coverage.intervals == ()
    assert coverage.exclusions == {"RPT1": "unproven_ticker_reuse"}


@pytest.mark.parametrize("last_price", ["2022-12-01", "2024-01-01"])
def test_delisting_action_not_price_end_closes_membership(last_price: str) -> None:
    from sextant.data.sharadar_master import dated_intervals
    from sextant.data.universe import DatedUniverse

    rows = dated_intervals(
        [ticker("EXIT", "902", "2021-01-02", last_price)],
        [action("2020-01-02", "listed", "EXIT"), action("2023-03-09", "delisted", "EXIT")],
        start=START,
        end=END,
    )
    historic = DatedUniverse(rows, source="sharadar", start=START, end=END)
    assert historic.universe_for_date(date(2023, 3, 9)).symbols == ("EXIT",)
    assert historic.universe_for_date(date(2023, 3, 10)).symbols == ()
    assert rows[0].last_date == date(2023, 3, 9)
    assert rows[0].exit_reason == "delisted"


def test_ticker_changes_outside_price_coverage_preserve_only_the_dated_share_class() -> None:
    from sextant.data.sharadar_master import dated_intervals
    from sextant.data.universe import DatedUniverse

    row = ticker("NEW", "903", "2021-01-02", "2022-12-01")
    row.update(isdelisted="N", relatedtickers="OLD PREFERRED OTHER")
    rows = dated_intervals(
        [row],
        [
            action("2020-01-02", "listed", "NEW"),
            action("2023-03-09", "tickerchangefrom", "NEW", "OLD"),
            action("2023-03-09", "tickerchangeto", "NEW", "NEW"),
        ],
        start=START,
        end=END,
    )
    historic = DatedUniverse(rows, source="sharadar", start=START, end=END)
    assert historic.universe_for_date(date(2020, 1, 2)).symbols == ("OLD",)
    assert historic.universe_for_date(date(2023, 3, 8)).symbols == ("OLD",)
    assert historic.universe_for_date(date(2023, 3, 9)).symbols == ("NEW",)
    assert {member.security_id for member in rows} == {"sharadar:903"}
    assert {member.symbol for member in rows} == {"OLD", "NEW"}


def test_missing_boundary_proof_excludes_rather_than_unconditionally_infer_from_prices() -> None:
    from sextant.data.sharadar_master import dated_intervals, interval_coverage

    row = ticker("UNSUPPORTED", "904", "2021-01-02", "2023-03-09")
    row["isdelisted"] = "N"
    assert dated_intervals([row], [], start=START, end=END) == ()
    assert interval_coverage([row], [], start=START, end=END).exclusions == {
        "UNSUPPORTED": "missing_listing_action"
    }
    row.update(isdelisted="Y", lastpricedate="")
    coverage = interval_coverage(
        [row], [action("2020-01-02", "listed", "UNSUPPORTED")], start=START, end=END
    )
    assert coverage.intervals == ()
    assert coverage.exclusions == {"UNSUPPORTED": "missing_exit_action"}


@pytest.mark.parametrize("exit_action", ["bankruptcyliquidation", "acquisitionby", "mergerto"])
def test_terminal_exit_action_can_follow_the_last_price(exit_action: str) -> None:
    from sextant.data.sharadar_master import dated_intervals

    row = ticker("TERMINAL", "905", "2021-01-02", "2022-01-01")
    rows = dated_intervals(
        [row],
        [action("2020-01-02", "listed", "TERMINAL"), action("2023-03-09", exit_action, "TERMINAL")],
        start=START,
        end=END,
    )
    assert rows[0].last_date == date(2023, 3, 9)
    assert rows[0].exit_reason == exit_action


def test_acquisition_consideration_alone_is_not_membership_evidence() -> None:
    from sextant.data.sharadar_master import interval_coverage

    coverage = interval_coverage(
        [ticker("CONSIDERATION", "906", "2021-01-02", "")],
        [
            action("2020-01-02", "listed", "CONSIDERATION"),
            action("2023-03-09", "acquisitioncash", "CONSIDERATION", "BUYER"),
        ],
        start=START,
        end=END,
    )
    assert coverage.intervals == ()
    assert coverage.exclusions == {"CONSIDERATION": "missing_exit_action"}


def test_reused_ticker_requires_nonoverlapping_action_dates_not_price_dates() -> None:
    from sextant.data.sharadar_master import dated_intervals

    tickers, actions = fixtures()
    # Prices do not overlap, but explicit membership of the new holder does.
    actions = [
        {**row, "date": "2023-12-01"}
        if row["action"] == "listed" and row["ticker"] == "RPT"
        else row
        for row in actions
    ]
    rows = dated_intervals(tickers, actions, start=START, end=END)
    assert "RPT1" not in {row.dataset_ticker for row in rows}
    assert next(row for row in rows if row.dataset_ticker == "RPT").security_id == "sharadar:201"


def test_relisting_is_excluded_without_a_documented_unambiguous_pairing_contract() -> None:
    from sextant.data.sharadar_master import interval_coverage

    tickers, actions = fixtures()
    relisted = ticker("RELIST", "912", "2021-01-01", "2026-10-24")
    relisted["isdelisted"] = "N"
    tickers.append(relisted)
    actions.extend(
        [
            action("2020-01-02", "listed", "RELIST"),
            action("2022-01-02", "delisted", "RELIST"),
            action("2023-01-02", "listed", "RELIST"),
        ]
    )
    coverage = interval_coverage(tickers, actions, start=START, end=END)
    assert coverage.exclusions == {"RELIST": "ambiguous_listing_actions"}
    assert coverage.summary["exclusion_counts"] == {"ambiguous_listing_actions": 1}
    assert "RELIST" not in {row.symbol for row in coverage.intervals}
    assert len(coverage.intervals) == 6


def test_suffix_owner_without_listing_evidence_excludes_only_the_unproven_identities() -> None:
    from sextant.data.sharadar_master import interval_coverage

    tickers, actions = fixtures()
    actions = [row for row in actions if not (row["ticker"] == "RPT" and row["action"] == "listed")]
    coverage = interval_coverage(tickers, actions, start=START, end=END)
    assert coverage.exclusions == {"RPT": "missing_listing_action", "RPT1": "unproven_ticker_reuse"}
    assert {row.dataset_ticker for row in coverage.intervals} == {"SIVBQ", "CASH", "FAILQ"}


def test_conflicting_symbols_exclude_both_securities_instead_of_picking_a_winner() -> None:
    from sextant.data.sharadar_master import interval_coverage

    tickers, actions = fixtures()
    rows = [
        ticker("CURRENT", "913", "2020-01-02", "2026-10-24"),
        ticker("OLDER", "914", "2020-01-02", "2026-10-24"),
    ]
    for row in rows:
        row["isdelisted"] = "N"
        actions.extend(
            [
                action("2020-01-02", "listed", row["ticker"]),
                action("2024-01-01", "tickerchangefrom", row["ticker"], "COLLIDE"),
                action("2024-01-01", "tickerchangeto", row["ticker"], row["ticker"]),
            ]
        )
    coverage = interval_coverage([*tickers, *rows], actions, start=START, end=END)
    assert coverage.exclusions == {
        "CURRENT": "overlapping_dated_identity",
        "OLDER": "overlapping_dated_identity",
    }
    assert len(coverage.intervals) == 6


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("bad_listing_date", "invalid_action_date"),
        ("invalid_market_symbol", "invalid_market_symbol"),
        ("missing_class", "missing_share_class_identity"),
        ("unknown_exchange", "unknown_exchange"),
        ("unknown_status", "unknown_listing_status"),
        ("conflicting_terminal", "conflicting_terminal_exit_actions"),
        ("exit_before_listing", "conflicting_listing_exit_actions"),
        ("broken_rename", "discontinuous_tickerchange_chain"),
        ("wrong_rename_target", "tickerchange_target_mismatch"),
        ("broken_exchange_chain", "discontinuous_exchange_chain"),
        ("wrong_exchange_target", "exchange_history_mismatch"),
    ],
)
def test_bad_security_evidence_has_a_named_exclusion_without_losing_healthy_rows(
    case: str, reason: str
) -> None:
    from sextant.data.sharadar_master import interval_coverage

    tickers, actions = fixtures()
    if case == "bad_listing_date":
        next(row for row in actions if row["ticker"] == "SIVBQ" and row["action"] == "listed")[
            "date"
        ] = ""
    elif case == "invalid_market_symbol":
        actions[0]["contraticker"] = "BAD/SYMBOL"
    elif case == "missing_class":
        tickers[0]["category"] = ""
    elif case == "unknown_exchange":
        tickers[0]["exchange"] = "UNKNOWN"
    elif case == "unknown_status":
        tickers[0]["isdelisted"] = ""
    elif case == "conflicting_terminal":
        actions.append(action("2023-09-28", "acquisitionby", "SIVBQ", "BUYER"))
    elif case == "exit_before_listing":
        actions.append(action("2019-01-01", "delisted", "SIVBQ"))
    elif case == "broken_rename":
        actions[0]["date"] = actions[1]["date"] = "2019-01-01"
    elif case == "wrong_rename_target":
        actions[1]["contraticker"] = "WRONG"
    elif case == "broken_exchange_chain":
        actions[2]["date"] = actions[3]["date"] = "2019-01-01"
    elif case == "wrong_exchange_target":
        tickers[0]["exchange"] = "NYSE"
    coverage = interval_coverage(tickers, actions, start=START, end=END)
    assert coverage.exclusions == {"SIVBQ": reason}
    assert coverage.summary["exclusion_counts"] == {reason: 1}
    assert {row.dataset_ticker for row in coverage.intervals} == {"RPT1", "RPT", "CASH", "FAILQ"}


COVERAGE_BOUNDARY = date(2017, 1, 3)  # Synthetic, not the licensed capture's cutoff.


def test_scope_provenance_keeps_sep_stocks_and_does_not_silently_add_funds() -> None:
    from sextant.data.sharadar_master import interval_coverage

    stock = ticker("COMMON", "1015", "2000-01-01", "2026-10-24")
    preferred = ticker("PREF", "1016", "2000-01-01", "2026-10-24")
    fund = ticker("ETF", "1017", "2000-01-01", "2026-10-24")
    stock.update(table="SEP", isdelisted="N")
    preferred.update(category="Domestic Preferred Stock", isdelisted="N")
    fund.update(table="SFP", category="ETF", isdelisted="N")
    coverage = interval_coverage(
        [stock, preferred, fund], [], start=START, end=END, actions_start=COVERAGE_BOUNDARY
    )
    assert (
        coverage.summary["security_scope"]
        == "stocks/SEP only (common and preferred); funds/SFP excluded"
    )
    assert coverage.input_security_count == 2
    assert {row.symbol for row in coverage.intervals} == {"COMMON", "PREF"}


def test_pre_coverage_trading_starts_at_capture_boundary_never_first_price() -> None:
    from sextant.data.sharadar_master import interval_coverage

    row = ticker("OLDER", "1001", "2001-02-03", "2026-10-24")
    row.update(isdelisted="N", firstadded="2024-01-01")
    coverage = interval_coverage(
        [row], [], start=date(2000, 1, 1), end=END, actions_start=COVERAGE_BOUNDARY
    )
    assert coverage.exclusions == {}
    member = coverage.intervals[0]
    assert member.first_date == COVERAGE_BOUNDARY
    assert member.evidence_class == member.start_evidence == "pre_coverage_listing"
    assert member.end_evidence == "open_status"
    assert member.actions_coverage_start == COVERAGE_BOUNDARY
    assert coverage.summary["evidence_class_counts"] == {
        "explicit_action": 0,
        "pre_coverage_listing": 1,
        "tickers_field": 0,
    }
    assert coverage.summary["actions_coverage_start"] == COVERAGE_BOUNDARY.isoformat()


@pytest.mark.parametrize(
    ("first_price", "reason"),
    [
        ("", "missing_pre_coverage_price"),
        ("bad-date", "invalid_first_price_date"),
        ("2017-01-03", "missing_listing_action"),
        ("2018-01-01", "missing_listing_action"),
    ],
)
def test_pre_coverage_fallback_requires_valid_strictly_older_trading(
    first_price: str, reason: str
) -> None:
    from sextant.data.sharadar_master import interval_coverage

    row = ticker("UNKNOWN", "1002", first_price, "2026-10-24")
    row["isdelisted"] = "N"
    coverage = interval_coverage([row], [], start=START, end=END, actions_start=COVERAGE_BOUNDARY)
    assert coverage.intervals == ()
    assert coverage.exclusions == {"UNKNOWN": reason}


@pytest.mark.parametrize("price", ["bad-date", "2001-01-01", "2024-01-01"])
def test_explicit_boundaries_win_even_when_tickers_fields_conflict(price: str) -> None:
    from sextant.data.sharadar_master import interval_coverage

    coverage = interval_coverage(
        [ticker("EXPLICIT", "1003", price, price)],
        [action("2020-02-03", "listed", "EXPLICIT"), action("2023-04-05", "delisted", "EXPLICIT")],
        start=START,
        end=END,
        actions_start=COVERAGE_BOUNDARY,
    )
    assert coverage.exclusions == {}
    row = coverage.intervals[0]
    assert (row.first_date, row.last_date) == (date(2020, 2, 3), date(2023, 4, 5))
    assert row.evidence_class == row.start_evidence == row.end_evidence == "explicit_action"


@pytest.mark.parametrize("explicit_listing", [True, False])
def test_delisted_tickers_end_is_weaker_only_without_explicit_exit(explicit_listing: bool) -> None:
    from sextant.data.sharadar_master import interval_coverage

    row = ticker("WEAKEND", "1004", "2001-01-01", "2023-04-05")
    actions = [action("2020-02-03", "listed", "WEAKEND")] if explicit_listing else []
    coverage = interval_coverage(
        [row], actions, start=START, end=END, actions_start=COVERAGE_BOUNDARY
    )
    assert coverage.exclusions == {}
    member = coverage.intervals[0]
    assert member.last_date == date(2023, 4, 5)
    assert member.evidence_class == member.end_evidence == "tickers_field"
    assert member.exit_reason == "tickers_lastpricedate"
    assert member.start_evidence == (
        "explicit_action" if explicit_listing else "pre_coverage_listing"
    )
    assert coverage.summary["evidence_class_counts"] == {
        "explicit_action": 0,
        "pre_coverage_listing": 0,
        "tickers_field": 1,
    }


@pytest.mark.parametrize(
    ("last_price", "reason"),
    [
        ("", "missing_exit_action"),
        ("bad-date", "invalid_last_price_date"),
        ("2001-01-01", "ended_before_actions_coverage"),
    ],
)
def test_weaker_exit_still_requires_valid_ordered_evidence(last_price: str, reason: str) -> None:
    from sextant.data.sharadar_master import interval_coverage

    coverage = interval_coverage(
        [ticker("NOEND", "1005", "2000-01-01", last_price)],
        [],
        start=START,
        end=END,
        actions_start=COVERAGE_BOUNDARY,
    )
    assert coverage.intervals == ()
    assert coverage.exclusions == {"NOEND": reason}


@pytest.mark.parametrize("exit_kind", ["delisted", "bankruptcyliquidation"])
def test_pre_coverage_sivb_like_and_bbby_like_exits_keep_full_action_chain(exit_kind: str) -> None:
    from sextant.data.sharadar_master import interval_coverage
    from sextant.data.universe import DatedUniverse

    row = ticker("OLDQ", "1006", "2001-01-01", "2024-12-31")
    row.update(exchange="NASDAQ", relatedtickers="OLD OTHERCLASS")
    actions = [
        action("2023-02-03", "tickerchangefrom", "OLDQ", "OLD"),
        action("2023-02-03", "tickerchangeto", "OLDQ", "OLDQ"),
        action("2023-02-03", exit_kind, "OLDQ"),
        action("2023-02-03", "delisted", "OLDQ"),
        action("2023-02-06", "exchangefrom", "OLDQ", venue="NASDAQ"),
        action("2023-02-06", "exchangeto", "OLDQ", venue="OTC"),
    ]
    if exit_kind == "delisted":
        actions.pop(3)  # No duplicate synthetic action identity.
    coverage = interval_coverage(
        [row], actions, start=START, end=END, actions_start=COVERAGE_BOUNDARY
    )
    assert coverage.exclusions == {}
    assert len(coverage.intervals) == 1
    member = coverage.intervals[0]
    assert (member.symbol, member.last_date, member.exchange) == ("OLD", date(2023, 2, 3), "NASDAQ")
    assert member.evidence_class == "pre_coverage_listing"
    assert member.end_evidence == "explicit_action"
    historic = DatedUniverse(coverage.intervals, source="sharadar", start=START, end=END)
    assert historic.universe_for_date(date(2023, 2, 3)).symbols == ("OLD",)
    assert historic.universe_for_date(date(2023, 2, 4)).symbols == ()


def test_post_terminal_chains_are_validated_not_ignored() -> None:
    from sextant.data.sharadar_master import interval_coverage

    row = ticker("POST", "1007", "2000-01-01", "2023-01-01")
    coverage = interval_coverage(
        [row],
        [
            action("2023-01-01", "delisted", "POST"),
            action("2023-01-02", "exchangefrom", "POST", venue="NYSE"),
        ],
        start=START,
        end=END,
        actions_start=COVERAGE_BOUNDARY,
    )
    assert coverage.exclusions == {"POST": "ambiguous_exchange_pair"}


def test_weaker_start_never_overrides_explicit_relisting_or_exit() -> None:
    from sextant.data.sharadar_master import interval_coverage

    row = ticker("RELIST", "1008", "2000-01-01", "2026-10-24")
    coverage = interval_coverage(
        [row],
        [
            action("2020-01-01", "listed", "RELIST"),
            action("2021-01-01", "delisted", "RELIST"),
            action("2022-01-01", "listed", "RELIST"),
        ],
        start=START,
        end=END,
        actions_start=COVERAGE_BOUNDARY,
    )
    assert coverage.exclusions == {"RELIST": "ambiguous_listing_actions"}
    assert coverage.intervals == ()


def test_explicit_listing_with_bad_price_exit_still_reports_a_conflict() -> None:
    from sextant.data.sharadar_master import interval_coverage

    coverage = interval_coverage(
        [ticker("BADEND", "1012", "2000-01-01", "2018-01-01")],
        [action("2020-01-01", "listed", "BADEND")],
        start=START,
        end=END,
        actions_start=COVERAGE_BOUNDARY,
    )
    assert coverage.exclusions == {"BADEND": "conflicting_listing_exit_actions"}


def test_last_trade_symbol_adjustment_does_not_override_an_earlier_listed_rename() -> None:
    from sextant.data.sharadar_master import interval_coverage
    from sextant.data.universe import DatedUniverse

    row = ticker("RENAMED", "1013", "2000-01-01", "2023-02-03")
    actions = [
        action("2023-02-02", "tickerchangefrom", "RENAMED", "BEFORE"),
        action("2023-02-02", "tickerchangeto", "RENAMED", "RENAMED"),
        action("2023-02-03", "delisted", "RENAMED"),
        action("2023-02-06", "exchangefrom", "RENAMED", venue="NYSE"),
        action("2023-02-06", "exchangeto", "RENAMED", venue="OTC"),
    ]
    coverage = interval_coverage(
        [row], actions, start=START, end=END, actions_start=COVERAGE_BOUNDARY
    )
    assert coverage.exclusions == {}
    historic = DatedUniverse(coverage.intervals, source="sharadar", start=START, end=END)
    assert historic.universe_for_date(date(2023, 2, 1)).symbols == ("BEFORE",)
    assert historic.universe_for_date(date(2023, 2, 2)).symbols == ("RENAMED",)
    assert historic.universe_for_date(date(2023, 2, 3)).symbols == ("RENAMED",)


@pytest.mark.parametrize("explicit_listing", [True, False])
def test_weaker_start_and_exit_never_fill_explicit_delisting_halt(explicit_listing: bool) -> None:
    from sextant.data.sharadar_master import interval_coverage
    from sextant.data.universe import DatedUniverse

    row = ticker("HALTQ", "1014", "2000-01-01", "2026-10-24")
    row["isdelisted"] = "N"  # Snapshot status cannot erase a dated removal.
    actions = [
        action("2023-02-03", "delisted", "HALTQ"),
        action("2023-02-06", "exchangefrom", "HALTQ", venue="NYSE"),
        action("2023-02-06", "exchangeto", "HALTQ", venue="OTC"),
    ]
    if explicit_listing:
        actions.append(action("2020-01-01", "listed", "HALTQ"))
    coverage = interval_coverage(
        [row], actions, start=START, end=END, actions_start=COVERAGE_BOUNDARY
    )
    assert coverage.exclusions == {}
    historic = DatedUniverse(coverage.intervals, source="sharadar", start=START, end=END)
    assert historic.universe_for_date(date(2023, 2, 3)).symbols == ("HALTQ",)
    assert historic.universe_for_date(date(2023, 2, 4)).symbols == ()
    assert historic.universe_for_date(date(2023, 2, 5)).symbols == ()
    assert (
        next(row for row in coverage.intervals if row.first_date == date(2023, 2, 6)).exchange
        == "OTC"
    )
    assert coverage.intervals[0].exit_reason == "delisted"


def sfp_ticker(symbol: str = "SYNF", category: str = "ETF", table: str = "SFP") -> dict[str, str]:
    row = ticker(symbol, "2000", "2001-01-01", "2026-10-24")
    row.update(table=table, category=category, isdelisted="N")
    return row


@pytest.mark.parametrize("table", ["SFP", "funds"])
def test_sfp_requires_explicit_scope_and_preserves_r3_sep_interval_bytes(table: str) -> None:
    from dataclasses import asdict
    from hashlib import sha256

    from sextant.data.sharadar_master import dated_intervals, interval_coverage

    tickers, actions = fixtures()
    boundary = date(2016, 9, 30)
    baseline = dated_intervals(tickers, actions, start=START, end=END, actions_start=boundary)
    serialized = json.dumps(
        [asdict(row) for row in baseline], default=str, sort_keys=True, separators=(",", ":")
    )
    # Computed on approved r3 (04d466a), solely from the synthetic fixtures above.
    assert (
        sha256(serialized.encode()).hexdigest()
        == "f3de7946a207c1ef68d4aa490739b7d8c3c49815ea7044e6777a7f8835aff705"
    )
    mixed = [*tickers, sfp_ticker(table=table)]
    assert dated_intervals(mixed, actions, start=START, end=END, actions_start=boundary) == baseline
    assert (
        dated_intervals(mixed, actions, start=START, end=END, actions_start=boundary, scope="SEP")
        == baseline
    )
    extended = interval_coverage(
        mixed, actions, start=START, end=END, actions_start=boundary, scope="SEP+SFP"
    )
    assert tuple(row for row in extended.intervals if row.dataset_ticker != "SYNF") == baseline
    fund = next(row for row in extended.intervals if row.dataset_ticker == "SYNF")
    assert fund.instrument_type == "etf"
    assert fund.first_date == START
    assert fund.start_evidence == fund.evidence_class == "pre_coverage_listing"
    assert fund.actions_coverage_start == boundary
    assert extended.summary["scope"] == "SEP+SFP"
    assert extended.summary["table_counts"]["SEP"] == population_counts(5, 5, 0, 0, 6)
    assert extended.summary["table_counts"]["SFP"] == population_counts(1, 1, 0, 0, 1)
    assert extended.summary["instrument_type_counts"]["etf"] == population_counts(1, 1, 0, 0, 1)


@pytest.mark.parametrize(
    ("table", "category", "kind"),
    [
        ("SEP", "Domestic Common Stock", "common"),
        ("stocks", "ADR Common Stock Primary Class", "common"),
        ("SEP", "Canadian Common Stock Secondary Class", "common"),
        ("SEP", "Domestic Preferred Stock", "preferred"),
        ("SEP", "ADR Preferred Stock", "preferred"),
        ("SEP", "Canadian Preferred Stock", "preferred"),
        ("SFP", "ETF", "etf"),
        ("funds", "ETN", "etn"),
        ("SFP", "CEF", "fund"),
        ("SFP", "CEF Preferred", "preferred"),
        ("SFP", "ETMF", "fund"),
        ("SFP", "MF", "fund"),
    ],
)
def test_dated_interval_types_follow_documented_categories(
    table: str, category: str, kind: str
) -> None:
    from sextant.data.sharadar_master import interval_coverage

    coverage = interval_coverage(
        [sfp_ticker(table=table, category=category)],
        [],
        start=START,
        end=END,
        actions_start=COVERAGE_BOUNDARY,
        scope="SEP+SFP",
    )
    assert coverage.exclusions == {}
    assert coverage.intervals[0].instrument_type == kind
    assert coverage.intervals[0].security_class == category
    assert coverage.summary["instrument_type_counts"][kind] == population_counts(1, 1, 0, 0, 1)


@pytest.mark.parametrize("category", ["ETD", "IDX", "UNIT", "NEWTYPE"])
def test_unsupported_sfp_types_are_named_exclusions_not_funds(category: str) -> None:
    from sextant.data.sharadar_master import interval_coverage

    coverage = interval_coverage(
        [sfp_ticker(category=category)],
        [],
        start=START,
        end=END,
        actions_start=COVERAGE_BOUNDARY,
        scope="SEP+SFP",
    )
    assert coverage.intervals == ()
    assert coverage.exclusions == {"SYNF": "unsupported_instrument_type"}
    assert coverage.summary["unsupported_category_counts"] == {category: 1}
    assert coverage.summary["instrument_type_counts"]["unsupported"] == population_counts(
        1, 0, 0, 1, 0
    )
    assert coverage.summary["table_counts"]["SFP"] == population_counts(1, 0, 0, 1, 0)


@pytest.mark.parametrize("price", ["bad-date", "2001-01-01", "2025-01-01"])
def test_explicit_fund_actions_win_over_precoverage_and_price_exit(price: str) -> None:
    from sextant.data.sharadar_master import interval_coverage

    row = sfp_ticker(category="CEF")
    row.update(firstpricedate=price, lastpricedate=price, isdelisted="Y")
    coverage = interval_coverage(
        [row],
        [action("2020-02-03", "listed", "SYNF"), action("2023-04-05", "delisted", "SYNF")],
        start=START,
        end=END,
        actions_start=COVERAGE_BOUNDARY,
        scope="SEP+SFP",
    )
    member = coverage.intervals[0]
    assert (member.first_date, member.last_date) == (date(2020, 2, 3), date(2023, 4, 5))
    assert (
        member.evidence_class == member.start_evidence == member.end_evidence == "explicit_action"
    )
    assert member.instrument_type == "fund"


def test_fund_precoverage_boundary_is_not_a_listing_or_relatedticker_alias() -> None:
    from sextant.data.sharadar_master import interval_coverage

    row = sfp_ticker()
    row["relatedtickers"] = "UNPROVEN OTHERCLASS"
    coverage = interval_coverage(
        [row],
        [],
        start=date(2000, 1, 1),
        end=END,
        actions_start=COVERAGE_BOUNDARY,
        scope="SEP+SFP",
    )
    assert len(coverage.intervals) == 1
    assert coverage.intervals[0].first_date == COVERAGE_BOUNDARY
    assert coverage.intervals[0].symbol == "SYNF"
    row["firstpricedate"] = COVERAGE_BOUNDARY.isoformat()
    excluded = interval_coverage(
        [row],
        [],
        start=START,
        end=END,
        actions_start=COVERAGE_BOUNDARY,
        scope="SEP+SFP",
    )
    assert excluded.exclusions == {"SYNF": "missing_listing_action"}


def test_fund_relisting_stays_ambiguous_despite_precoverage_price() -> None:
    from sextant.data.sharadar_master import interval_coverage

    coverage = interval_coverage(
        [sfp_ticker()],
        [action("2020-01-01", "listed", "SYNF"), action("2022-01-01", "listed", "SYNF")],
        start=START,
        end=END,
        actions_start=COVERAGE_BOUNDARY,
        scope="SEP+SFP",
    )
    assert coverage.intervals == ()
    assert coverage.exclusions == {"SYNF": "ambiguous_listing_actions"}


def test_scope_and_type_counts_account_for_included_excluded_and_outside_securities() -> None:
    from sextant.data.sharadar_master import interval_coverage

    rows = []
    for symbol, identity, category in [
        ("INSIDE", "2001", "ETF"),
        ("OUTSIDE", "2002", "ETF"),
        ("NOBOUND", "2003", "ETN"),
    ]:
        row = sfp_ticker(symbol, category)
        row["permaticker"] = identity
        rows.append(row)
    rows[1].update(isdelisted="Y", lastpricedate="2018-01-02")
    rows[2]["firstpricedate"] = "2020-01-02"
    coverage = interval_coverage(
        rows,
        [],
        start=START,
        end=END,
        actions_start=COVERAGE_BOUNDARY,
        scope="SEP+SFP",
    )
    assert coverage.summary["table_counts"]["SFP"] == population_counts(3, 1, 1, 1, 1)
    assert coverage.summary["instrument_type_counts"]["etf"] == population_counts(2, 1, 1, 0, 1)
    assert coverage.summary["instrument_type_counts"]["etn"] == population_counts(1, 0, 0, 1, 0)
    for group in ("table_counts", "instrument_type_counts"):
        for field in population_counts(0, 0, 0, 0, 0):
            assert (
                sum(counts[field] for counts in coverage.summary[group].values())
                == coverage.summary[field]
            )


def test_cross_table_share_class_duplicates_are_not_hidden_by_scope() -> None:
    from sextant.data.sharadar_master import interval_coverage

    rows, actions = fixtures()
    duplicate = sfp_ticker()
    duplicate["permaticker"] = rows[0]["permaticker"]
    assert len(interval_coverage([*rows, duplicate], actions, start=START, end=END).intervals) == 6
    with pytest.raises(ValueError, match="Duplicate"):
        interval_coverage([*rows, duplicate], actions, start=START, end=END, scope="SEP+SFP")
