"""dangerfile.js, run with only a mocked Danger API: the first rule, as `review` applies it."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
MANIFEST = (
    "| Practice or pick | Source, pinned | How it is applied | Proof |\n"
    "|---|---|---|---|\n"
    "| Real row | source | applied | proof |\n"
)
PLUGIN_MANIFEST = (
    MANIFEST + "\n## Third-party plugins\n\n"
    "| Practice or pick | Source, pinned | How it is applied | Proof |\n"
    "|---|---|---|---|\n"
    "| Plugin X | owner/repo@v1 " + "d" * 40 + " | one lane | proof |\n"
)
HARNESS = """
const fs = require("fs");
const vm = require("vm");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const fails = [];
const pending = [];
const danger = {
  github: {
    pr: { body: input.body, user: { login: input.login }, created_at: input.created_at },
    utils: { fileContents: async () => input.manifest },
  },
  git: {
    created_files: input.created, modified_files: input.modified, deleted_files: input.deleted,
    structuredDiffForFile: async (filename) => input.structured_diffs[filename] ?? null,
  },
};
const api = { danger, fail: (m) => fails.push(m), schedule: (p) => pending.push(p()) };
vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), { require: () => api });
Promise.all(pending).then(() => console.log(JSON.stringify(fails)));
"""


def _body(*, row: str = '"Real row"', sources: str = "a/b@v1 " + "c" * 40) -> str:
    return (
        "## What changed\nx\n"
        f"## Manifest row\n{row}\n"
        f"## Upstream references\n{sources}\n"
        "## How verified\ny\n"
        "## How to revert\nz\n"
    )


def _failures(
    body: str,
    login: str = "someone",
    created: tuple[str, ...] = (),
    manifest: str = MANIFEST,
    *,
    created_at: str | None = "2026-11-11T15:35:10Z",
    modified: tuple[str, ...] = (),
    deleted: tuple[str, ...] = (),
    structured_diffs: dict[str, dict[str, object]] | None = None,
    omit_created_at: bool = False,
) -> list[str]:
    done = subprocess.run(
        ["node", "-e", HARNESS, str(ROOT / "dangerfile.js")],
        input=json.dumps(
            {
                "body": body,
                "login": login,
                "created": list(created),
                "modified": list(modified),
                "deleted": list(deleted),
                "manifest": manifest,
                **({} if omit_created_at else {"created_at": created_at}),
                "structured_diffs": structured_diffs or {},
            }
        ),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(done.stdout)


def test_an_honest_body_passes_even_when_its_last_section_ends_the_body() -> None:
    assert _failures(_body()) == []


def test_the_strategy_rule_also_binds_dependabot() -> None:
    found = _failures("", login="dependabot[bot]", created=("src/sextant/strategies/x.py",))
    assert any("strategy" in f for f in found)


def test_a_docs_page_with_a_read_date_is_a_source() -> None:
    assert _failures(_body(sources="https://x.dev/page, read 2026-11-05")) == []


def test_a_paper_is_a_source() -> None:
    assert _failures(_body(sources="doi:10.1234/abc")) == []


def test_no_source_is_refused_as_self_invention() -> None:
    assert any("self-invent" in f for f in _failures(_body(sources="my own idea")))


def test_a_url_without_a_read_date_is_refused() -> None:
    assert any("self-invent" in f for f in _failures(_body(sources="https://x.dev/page")))


def test_a_commit_shorter_than_full_is_refused() -> None:
    assert any("self-invent" in f for f in _failures(_body(sources="a/b@v1 abc1234")))


def test_a_markdown_linked_repo_at_a_tag_with_its_full_sha_is_a_source() -> None:
    # The form docs/manifest.md itself uses: the link's ")" sits between the repo and its "@".
    sources = "[a/b](https://github.com/a/b)@v1 `" + "c" * 40 + "`:`docs/x.md`"
    assert _failures(_body(sources=sources)) == []


def test_a_markdown_linked_repo_still_needs_its_full_sha() -> None:
    sources = "[a/b](https://github.com/a/b)@v1 `abc1234`"
    assert any("self-invent" in f for f in _failures(_body(sources=sources)))


def test_an_empty_section_is_refused() -> None:
    assert any("How verified" in f for f in _failures(_body().replace("\ny\n", "\n\n")))


def test_a_template_comment_is_not_content() -> None:
    body = _body().replace("\ny\n", "\n<!-- fill me in -->\n")
    assert any("How verified" in f for f in _failures(body))


def test_a_manifest_row_that_does_not_exist_is_refused() -> None:
    assert any("Manifest row" in f for f in _failures(_body(row='"Not a row"')))


def test_the_table_header_is_not_a_row() -> None:
    assert any("Manifest row" in f for f in _failures(_body(row='"Practice or pick"')))


def test_a_quoted_word_from_another_cell_is_not_a_row() -> None:
    assert any("Manifest row" in f for f in _failures(_body(row='"source"')))


def test_a_manifest_row_must_be_named_in_quotes() -> None:
    assert any("Manifest row" in f for f in _failures(_body(row="Real row")))


def test_a_strategy_needs_a_pinned_repo_or_a_paper() -> None:
    body = _body(sources="https://x.dev/page, read 2026-11-05")
    found = _failures(body, created=("src/sextant/strategies/x.py",))
    assert any("strategy" in f for f in found)


def test_dependabot_generated_bodies_pass() -> None:
    assert _failures("Bumps a from 1 to 2.", login="dependabot[bot]") == []


def test_dependabot_on_a_governed_path_keeps_its_exemption() -> None:
    assert (
        _failures(
            "Bumps a from 1 to 2.",
            login="dependabot[bot]",
            created=("src/sextant/exits/engine.py",),
        )
        == []
    )


def test_a_sourced_gate_edit_needs_no_owner_label() -> None:
    assert _failures(_body(), created=(".github/workflows/gate.yml",)) == []


def test_a_third_party_plugin_row_must_record_its_disclosure() -> None:
    found = _failures(_body(row='"Plugin X"'), manifest=PLUGIN_MANIFEST)
    assert any("capability" in failure for failure in found)


def test_a_third_party_plugin_row_with_its_disclosure_passes() -> None:
    manifest = PLUGIN_MANIFEST.replace(
        "| one lane | proof |", "| capabilities: fs-read; red lines: none; one lane | proof |"
    )
    assert _failures(_body(row='"Plugin X"'), manifest=manifest) == []


def test_a_governed_path_must_name_its_authority() -> None:
    found = _failures(
        _body(sources="example/fork@v1 " + "c" * 40),
        created=("src/sextant/exits/engine.py",),
    )
    assert any("engine" in failure and "authority" in failure.lower() for failure in found)


def test_a_governed_path_with_its_authority_passes() -> None:
    body = _body(sources="nautechsystems/nautilus_trader@v1 " + "c" * 40)
    assert _failures(body, created=("src/sextant/exits/engine.py",)) == []


def test_a_docs_only_change_needs_no_authority() -> None:
    body = _body(sources="example/fork@v1 " + "c" * 40)
    assert _failures(body, created=("docs/handbook/sources.md",)) == []


def test_a_lookalike_owner_does_not_pass_for_its_prefix() -> None:
    body = _body(sources="not-nautechsystems/nautilus_trader@v1 " + "c" * 40)
    found = _failures(body, created=("src/sextant/exits/engine.py",))
    assert any("engine" in failure and "authority" in failure.lower() for failure in found)


@pytest.mark.parametrize(
    ("sources", "missing"),
    [
        ("a/b@v1 " + "c" * 40 + " BUILD ON", "path:line"),
        ("a/b@v1 " + "c" * 40 + " src/client.py:12", "verdict"),
        ("doi:10.1234/abc src/client.py:12 BUILD ON", "pinned source"),
        ("a/b@v1 abc1234 src/client.py:12 BUILD ON", "pinned source"),
        ("https://x.dev/page src/client.py:12 BUILD ON", "pinned source"),
        ("a/b@v1 " + "c" * 40 + " https://x.dev:443 BUILD ON", "path:line"),
        ("a/b@v1 " + "c" * 40 + " src/client.py:0 BUILD ON", "path:line"),
        ("a/b@v1 " + "c" * 40 + " src/client.py:12 REBUILD", "verdict"),
        ("a/b@v1 " + "c" * 40 + " src/client.py:12 KEEP OURS", "Where searched"),
        (
            "a/b@v1 " + "c" * 40 + " src/client.py:12 KEEP OURS\n- Where searched: ",
            "Where searched",
        ),
        (
            "a/b@v1 " + "c" * 40 + " <!-- src/client.py:12 BUILD ON -->",
            "path:line",
        ),
    ],
)
def test_post_cutover_src_pr_names_missing_upstream_evidence(sources: str, missing: str) -> None:
    found = _failures(
        _body(sources=sources),
        created=("src/sextant/ranking/client.py",),
        created_at="2026-11-11T15:35:12Z",
    )
    assert any("Never self-invent" in failure and missing in failure for failure in found)


@pytest.mark.parametrize(
    "created_at", ["2026-11-11T15:35:10Z", "2026-11-11T15:35:11Z", "2026-11-11T10:35:11-05:00"]
)
def test_src_pr_created_no_later_than_cutover_keeps_the_old_rule(created_at: str) -> None:
    assert (
        _failures(_body(), created=("src/sextant/ranking/client.py",), created_at=created_at) == []
    )


@pytest.mark.parametrize("created_at", ["2026-11-11T15:35:11.001Z", "2026-11-11T10:35:12-05:00"])
def test_cutover_uses_the_creation_instant(created_at: str) -> None:
    found = _failures(_body(), created=("src/sextant/ranking/client.py",), created_at=created_at)
    assert any("path:line" in failure for failure in found)


@pytest.mark.parametrize(
    "path", ["docs/design.md", "tests/proofs/test_client.py", "dangerfile.js", "src/other.py"]
)
def test_post_cutover_pr_without_sextant_src_keeps_the_old_rule(path: str) -> None:
    assert _failures(_body(), created=(path,), created_at="2026-11-11T15:35:12Z") == []


@pytest.mark.parametrize(
    "sources",
    [
        "a/b@v1 " + "c" * 40 + " src/client.py:12 USE AS IS",
        "[a/b](https://github.com/a/b)@v1 `" + "c" * 40 + "` `src/client.py:12` BUILD ON",
        "https://x.dev/page, read 2026-11-11 `src/client.py:12` build on",
        "a/b@v1 " + "c" * 40 + " README.md:1 KEEP OURS\n- Where searched: src/; client",
    ],
)
def test_conforming_post_cutover_src_pr_passes(sources: str) -> None:
    assert (
        _failures(
            _body(sources=sources),
            created=("src/sextant/ranking/client.py",),
            created_at="2026-11-11T15:35:12Z",
        )
        == []
    )


@pytest.mark.parametrize("file_list", ["modified", "deleted"])
def test_post_cutover_rule_also_reads_modified_and_deleted_src(file_list: str) -> None:
    found = _failures(
        _body(),
        created_at="2026-11-11T15:35:12Z",
        **{file_list: ("src/sextant/ranking/client.py",)},
    )
    assert any("path:line" in failure for failure in found)


def test_post_cutover_dependabot_generated_body_keeps_its_exemption() -> None:
    assert (
        _failures(
            "Bumps a from 1 to 2.",
            login="dependabot[bot]",
            created=("src/sextant/exits/engine.py",),
            created_at="2026-11-11T15:35:12Z",
        )
        == []
    )


@pytest.mark.parametrize("separator", ["\n\n", "\n- ", "\n* ", "\n1. ", "\n| "])
@pytest.mark.parametrize(
    ("second", "missing"),
    [
        ("d/e@v2 " + "d" * 40 + " BUILD ON", "path:line"),
        ("d/e@v2 " + "d" * 40 + " src/clock.py:45", "verdict"),
        ("doi:10.1234/abc src/clock.py:45 BUILD ON", "pinned source"),
        ("d/e@v2 " + "d" * 40 + " src/clock.py:45 KEEP OURS", "Where searched"),
    ],
)
def test_each_mechanism_entry_needs_its_own_evidence(
    separator: str, second: str, missing: str
) -> None:
    first = "a/b@v1 " + "c" * 40 + " src/client.py:12 BUILD ON"
    found = _failures(
        _body(sources=first + separator + second),
        created=("src/sextant/ranking/client.py",),
        created_at="2026-11-11T15:35:12Z",
    )
    assert any(missing in failure for failure in found)


@pytest.mark.parametrize(
    "sources",
    [
        "- Client: a/b@v1 " + "c" * 40 + " src/client.py:12 BUILD ON\n"
        "- Clock: d/e@v2 " + "d" * 40 + " src/clock.py:45 USE AS IS",
        "| Mechanism | Upstream | Verdict |\n|---|---|---|\n"
        "| Client | a/b@v1 " + "c" * 40 + " src/client.py:12 | BUILD ON |\n"
        "| Clock | d/e@v2 " + "d" * 40 + " src/clock.py:45 | USE AS IS |",
        "- Shipped piece: a/b@v1 " + "c" * 40 + " src/client.py:12\n"
        "- Verdict: KEEP OURS\n- Where searched: src/ and docs/; client",
    ],
)
def test_complete_mechanism_entries_pass(sources: str) -> None:
    assert (
        _failures(
            _body(sources=sources),
            created=("src/sextant/ranking/client.py",),
            created_at="2026-11-11T15:35:12Z",
        )
        == []
    )


# Codex max review at e494a848: witnesses.py and rename-upstream.json.
PIN = "a/b@v1 " + "c" * 40
OTHER_PIN = "d/e@v2 " + "d" * 40
AFTER = "2026-11-11T15:35:12Z"


@pytest.mark.parametrize(
    "markers", [("-", "-"), ("+", "+"), ("*", "*"), ("1.", "2."), ("1)", "2)")]
)
@pytest.mark.parametrize(
    ("clock", "missing"),
    [
        (OTHER_PIN + " BUILD ON", "path:line"),
        ("src/clock.py:45 USE AS IS", "pinned source"),
        (OTHER_PIN + " src/clock.py:45", "verdict"),
    ],
)
def test_all_commonmark_markers_separate_mechanism_evidence(
    markers: tuple[str, str], clock: str, missing: str
) -> None:
    sources = f"{markers[0]} Client: {PIN} src/client.py:12 BUILD ON\n{markers[1]} Clock: {clock}"
    found = _failures(
        _body(sources=sources), created=("src/sextant/ranking/client.py",), created_at=AFTER
    )
    assert any(missing in failure for failure in found)


@pytest.mark.parametrize("created_at", [None, "", "not-a-date"])
def test_unusable_creation_time_applies_the_source_rule(created_at: str | None) -> None:
    found = _failures(_body(), created=("src/sextant/ranking/client.py",), created_at=created_at)
    assert any("path:line" in failure for failure in found)


def test_missing_creation_time_applies_the_source_rule() -> None:
    found = _failures(_body(), created=("src/sextant/ranking/client.py",), omit_created_at=True)
    assert any("path:line" in failure for failure in found)


@pytest.mark.parametrize(
    ("original", "destination", "sources", "blocked"),
    [
        ("src/sextant/ranking/client.py", "tools/renamed.py", PIN, True),
        ("tools/client.py", "src/sextant/ranking/renamed.py", PIN, True),
        ("docs/old.md", "docs/renamed.md", PIN, False),
        (
            "src/sextant/ranking/client.py",
            "tools/renamed.py",
            PIN + " src/client.py:12 BUILD ON",
            False,
        ),
    ],
)
def test_rename_scope_reads_the_native_from_path(
    original: str, destination: str, sources: str, blocked: bool
) -> None:
    # Danger 14.1.0 diffToGitJSONDSL.ts:22 retains only the destination.
    # GitDSL.ts:24-27 / gitJSONToGitDSL.ts:194-213 expose the original in fromPath.
    found = _failures(
        _body(sources=sources),
        modified=(destination,),
        structured_diffs={destination: {"fromPath": original, "chunks": []}},
        created_at=AFTER,
    )
    assert bool(found) is blocked
    if blocked:
        assert any("path:line" in failure for failure in found)


@pytest.mark.parametrize("marker", ["-", "+", "*", "1.", "1)"])
@pytest.mark.parametrize("gap", ["\n", "\n\n"])
def test_nested_citation_fields_belong_to_the_parent_mechanism(marker: str, gap: str) -> None:
    indent = " " * (len(marker) + 1)
    sources = (
        f"{marker} Client: {PIN}{gap}"
        f"{indent}- Shipped piece: `src/client.py:12-40`\n"
        f"{indent}- Verdict: BUILD ON"
    )
    assert (
        _failures(
            _body(sources=sources), created=("src/sextant/ranking/client.py",), created_at=AFTER
        )
        == []
    )


@pytest.mark.parametrize(
    "location",
    ["`src/client.py`:12", "`src/vendor:client.py:12`", "`src/client.py:12-40`"],
)
def test_source_locations_accept_code_spans_and_colons_in_filenames(location: str) -> None:
    assert (
        _failures(
            _body(sources=f"{PIN} {location} BUILD ON"),
            created=("src/sextant/ranking/client.py",),
            created_at=AFTER,
        )
        == []
    )


@pytest.mark.parametrize("location", ["https://x.dev:443", "src/client.py:0", "src/vendor:12:0"])
def test_source_locations_require_a_positive_last_line_group(location: str) -> None:
    found = _failures(
        _body(sources=f"{PIN} {location} BUILD ON"),
        created=("src/sextant/ranking/client.py",),
        created_at=AFTER,
    )
    assert any("path:line" in failure for failure in found)


# Conforming post-cutover fixtures derived from the nested source blocks in
# https://github.com/seathatflowsinourveins/sextant/pull/594 and /598 (read 2026-11-11).
# Those legacy bodies lack verdicts; add them and an explicit broker docs URL,
# keeping their upstream paths and nesting. Policy notes are context for the mechanism.
PR_594_SOURCES = """\
- Native cancel/resubmit: BUILD ON nautechsystems/nautilus_trader@v2.0.0rc8
  `d53849b216e20f2c122ca01b4dd0da377638b186`:
  - `crates/model/src/orders/mod.rs:1313-1320`;
  - `crates/trading/src/examples/strategies/grid_mm/strategy.rs:249-258` (the official example cancels and resubmits).
  - ADR-0007:17, :25, :50; LEAD-2201 B3(a); UPSTREAM-PORT-PLAN-PROTECT.md P1 and P6.
- Broker orders: USE AS IS https://docs.alpaca.markets/docs/orders, read 2026-11-11:
  - `docs-saved/alpaca-orders.md:165`.
"""
PR_598_SOURCES = """\
- Native cancel policy: BUILD ON nautechsystems/nautilus_trader@v2.0.0rc8
  `d53849b216e20f2c122ca01b4dd0da377638b186`:
  - `crates/model/src/events/order/denied.rs:36-39`, `rejected.rs:36`;
  - `crates/adapters/interactive_brokers/src/execution/core.rs:1032-1043`, `:2191-2196`;
  - `crates/adapters/interactive_brokers/src/execution/transform/policy.rs:91-126`;
  - `crates/adapters/interactive_brokers/src/execution/transform/tags.rs:30-51`;
  - `docs/integrations/interactive_brokers.md:418-428`.
  - Sextant main `src/sextant/exits/engine.py:303-330`; ADR-0007:17, :27; ADR-0005:34.
  - seathatflowsinourveins/northstar-trading@8256c16c31dcb8e53fc726e0c1c77dc2c8d0d4fa `strategies/base.py:2186-2189`.
"""


@pytest.mark.parametrize("sources", [PR_594_SOURCES, PR_598_SOURCES], ids=["pr-594", "pr-598"])
def test_conforming_paper_pr_nested_citations_pass(sources: str) -> None:
    assert (
        _failures(_body(sources=sources), modified=("src/sextant/paper/x.py",), created_at=AFTER)
        == []
    )
