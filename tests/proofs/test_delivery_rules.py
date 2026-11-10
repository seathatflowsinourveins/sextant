"""The owner's 2026-11-09 standing delegation and Claude's native Review step."""

from pathlib import Path

ROOT = Path(__file__).parents[2]
AGENTS = (ROOT / "AGENTS.md").read_text()
LIFECYCLE = (ROOT / "docs/handbook/lifecycle.md").read_text()
RULE_TWO = AGENTS.split("## Rule 2:", 1)[1].split("## The lanes", 1)[0]
LANDING = AGENTS.split("## Landing", 1)[1].split("Fill the author placeholder", 1)[0]
ROUTING = LIFECYCLE.split("## Review routing", 1)[1].split("## Standing authority", 1)[0]


def test_a_draft_is_a_hold_and_landing_is_the_only_merger() -> None:
    assert "A draft is a hold" in LANDING
    assert "only its drafting session, the lead or the owner runs `gh pr ready`" in LANDING
    assert "only Landing runs `gh pr merge`" in LANDING
    assert "everyone else arms auto-merge through `just pr`" in LANDING


def test_evidence_led_delegation_preserves_owner_only_authority() -> None:
    assert "The lead decides without asking" in RULE_TWO
    assert "pinned upstream source, measurement or converged screen" in RULE_TWO
    assert "records the decision with its sources" in RULE_TWO
    assert "the owner can overrule" in RULE_TWO
    for reserved in (
        "sign-ins and stored keys",
        "live actions",
        "owner-order and Peregrine custody",
        "Rule 1 exceptions",
        "named workhorse pins",
        "TradingView consent",
        "IBKR login",
        "unrequested destructive actions",
    ):
        assert reserved in RULE_TWO
    assert "remain owner-only" in RULE_TWO


def test_native_review_joins_the_claude_row_and_runs_before_pr() -> None:
    review_row = next(row for row in LIFECYCLE.splitlines() if row.startswith("| Review |"))
    claude_row = review_row.split("|")[3]
    assert "same pair" in claude_row and "`ce-code-review`" in claude_row
    assert "`/code-review`" in claude_row and "#180" in claude_row
    assert "Claude-family writer runs it on its branch before `just pr`" in ROUTING
    assert "Claude local cross-family reviewer runs it on the branch or PR under review" in ROUTING
    assert "a diff, PR number or branch" in ROUTING
    assert "`--comment`" in ROUTING
    assert "Default `high`" in ROUTING
    assert "`xhigh`" in ROUTING and "`max` only on the owner's word" in ROUTING
    for risk_path in ("paper", "execution", "exits", "risk"):
        assert f"`src/sextant/{risk_path}/`" in ROUTING
    assert "`.github/`" in ROUTING


def test_native_findings_keep_the_existing_landing_verdict() -> None:
    assert "../../.github/workflows/shared/review-rules.md#report" in ROUTING
    assert "unchanged" in ROUTING and "Always-P0" in ROUTING
    assert "concrete failing witness at the exact head" in ROUTING
    assert "one follow-up issue per PR" in ROUTING
    assert "from the third reviewed head, only P0 blocks" in ROUTING


def test_review_ownership_waits_for_measurement_and_checks_upstream_drift() -> None:
    assert "Once #180 lands" in ROUTING and "same known-defect set" in ROUTING
    assert "`/code-review`, `ce-code-review` and the Superpowers pair" in ROUTING
    assert "Until then they run beside each other" in ROUTING
    assert "The lead's first use is once on #197 at `xhigh`" in ROUTING
    assert "afterward this is the reviewers' step, not the lead's" in ROUTING
    assert "Every local review brief names the pinned upstream path" in ROUTING
    assert "whether upstream has moved since the pin in a way that changes the PR" in ROUTING
    assert "weekly hosted panel remains the landscape check" in ROUTING


def test_delivery_rule_has_a_public_source_record_and_manifest_proof() -> None:
    assert "## Standing authority" in LIFECYCLE
    assert "please proceed wiht the sota decision making" in LIFECYCLE
    assert "4ab39a83c800866c43416c5ea878a8d7ff3aa8adad811df52163a83686d34ecd" in LIFECYCLE
    assert "anthropics/claude-code" in LIFECYCLE and "2.1.321" in LIFECYCLE
    assert "a4fcccc70a89df6607e66cc30682d551269d0680" in LIFECYCLE
    assert "changing-the-stage-of-a-pull-request" in LIFECYCLE
    assert "read 2026-11-09" in LIFECYCLE
    manifest = (ROOT / "docs/manifest.md").read_text()
    row = next(row for row in manifest.splitlines() if row.startswith("| Evidence-led delivery"))
    assert "test_delivery_rules.py" in row
    assert "a4fcccc70a89df6607e66cc30682d551269d0680" in row
