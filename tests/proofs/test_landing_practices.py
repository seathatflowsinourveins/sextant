"""The handbook landing line carries the Release Toggle escape from a recurring block.

Source: Pete Hodgson, Release Toggles (martinfowler.com/articles/feature-toggles.html),
read 2026-11-09: "Release Toggles allow incomplete and un-tested codepaths to be shipped
to production as latent code which may never be turned on." The lead's landing ruling of
2026-11-09 applies it to review: a recurring blocking class ships disabled and failing
closed, or the PR splits; there is no third round.
"""

from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_practices_carry_the_release_toggle_landing_rule() -> None:
    practices = (ROOT / "docs" / "handbook" / "practices.md").read_text()
    for required in (
        "At most two reviewed commits",
        "split the PR or ship that path disabled and failing closed",
        "when a bug class recurs, simplify the design instead of patching instances",
        "[Release Toggles](https://martinfowler.com/articles/feature-toggles.html)",
        "read 2026-11-09",
    ):
        assert required in practices
    manifest = (ROOT / "docs" / "manifest.md").read_text()
    assert manifest.count("| Ship a recurring blocking path disabled") == 1
