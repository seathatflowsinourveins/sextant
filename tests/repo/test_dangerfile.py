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
    created_at: str = "2026-11-11T15:35:10Z",
    modified: tuple[str, ...] = (),
    deleted: tuple[str, ...] = (),
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
                "created_at": created_at,
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
