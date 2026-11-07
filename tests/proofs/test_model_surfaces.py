"""ADR-0030's owner model-pins manifest row: superseded DeepSeek models are unavailable."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
MODEL = re.compile(r"\bdeepseek-[\w.-]+\b", re.IGNORECASE)
SUFFIXES = {".md", ".yml", ".yaml", ".json", ".toml", ".sh", ".py", ".js", ".mjs"}
# Live surfaces: every configured runtime, workflow, deploy and policy document. Only historical
# research records keep the names that ran (ADR-0030's 2026-11-07 amendment).
LIVE = (".github", "deploy", "lanes", "config", ".dsh", ".claude", ".codex")
LIVE += (".devcontainer", "src", "docs", "scripts")
ROOT_FILES = ("AGENTS.md", "CLAUDE.md", "README.md", "justfile", "pyproject.toml", "uv.lock")
SERVED = {"deepseek-flash"}
# The dated id names the pin only in ADR-0030's canonical row; elsewhere it would freeze a snapshot.
DATED = ("docs/adr/0030-latest-sota-models.md", "deepseek-v4.1-flash-1017")
# Exact identifiers of the pinned harness, its npm scope and its files, never served models.
NOT_MODELS = {
    "deepseek-ai",
    "deepseek-harness",
    "deepseek-harness-tui",
    "deepseek-harness.md",
    "deepseek-harness_harness.cjs",
}


def _superseded(root: Path) -> list[str]:
    found = []
    paths = [root / name for name in ROOT_FILES]
    paths += [path for directory in LIVE for path in (root / directory).rglob("*")]
    for path in paths:
        relative = path.relative_to(root)
        if (
            not path.is_file()
            or (path.suffix not in SUFFIXES | {""} and path.parent != root)
            or relative.parts[:2] == ("docs", "research")
            or any(p in {"node_modules", ".venv", "__pycache__"} for p in path.parts)
            or path.name == "package-lock.json"
        ):
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:  # binaries hold no model selection
            continue
        for model in MODEL.findall(text):
            if model.lower() in SERVED | NOT_MODELS or (str(relative), model.lower()) == DATED:
                continue
            found.append(f"{relative}: {model}")
    return found


def test_no_live_surface_pins_a_superseded_deepseek_model() -> None:
    assert _superseded(ROOT) == []


@pytest.mark.parametrize(
    "model",
    [
        "deepseek-v4-pro",
        "deepseek-v3.2",
        "deepseek-r1",
        "deepseek-coder",
        "deepseek-math",
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-ai-v4-pro",
        "deepseek-harness-v4-pro",
        "deepseek-v4.1-flash-1017",
    ],
)
def test_superseded_versions_and_legacy_aliases_are_unavailable(tmp_path: Path, model: str) -> None:
    patch = tmp_path / "config/dsh/profile.json"
    patch.parent.mkdir(parents=True)
    patch.write_text('{"model": "' + model + '"}')
    assert _superseded(tmp_path) == [f"config/dsh/profile.json: {model}"]


def test_each_review_surface_requests_its_highest_supported_effort() -> None:
    workflows = ROOT / ".github/workflows"
    # dsh 0.2.2-rc.1's documented keys, compiled into the lock that actually runs.
    for path in (workflows / "shared/deepseek-harness.md", workflows / "review.lock.yml"):
        text = path.read_text()
        assert 'const effort = isAnthropic ? "max" : undefined;' in text, path
        for key in (
            "reasoningEffort: effort",
            "reasoning: effort",
            "reasoningEfforts: { [effort]: effort }",
            "forceAdaptiveThinking: true",
        ):
            assert key in text, (path, key)
    # Claude Code's documented effort variable; gh-aw's ?effort= applies only in routed mode
    # (claude_harness.cjs:421-428) and otherwise becomes part of the model id.
    source = (workflows / "review-claude.md").read_text()
    assert "    CLAUDE_CODE_EFFORT_LEVEL: max\n" in source and "\nmodel: opus\n" in source
    lock = (workflows / "review-claude.lock.yml").read_text()
    assert "ANTHROPIC_MODEL: opus\n" in lock and "CLAUDE_CODE_EFFORT_LEVEL: max\n" in lock
    assert not [
        p for p in workflows.glob("*.md") if re.search(r"^model: .*\?", p.read_text(), re.M)
    ]


def test_dependency_package_names_are_not_model_selections(tmp_path: Path) -> None:
    lock = tmp_path / ".devcontainer/agents/package-lock.json"
    lock.parent.mkdir(parents=True)
    lock.write_text('{"dependencies": {"deepseek-account": "0.2.2-rc.1"}}')
    assert _superseded(tmp_path) == []


@pytest.mark.parametrize(
    ("relative", "text"),
    [
        (".github/workflows/review.md", "---\nmodel: anthropic/deepseek-flash\n---\nUse {}.\n"),
        (".github/workflows/review.md", "---\nmodel: anthropic/{}\n---\n"),
        (".github/workflows/review.lock.yml", 'model = "{}"\n'),
        ("deploy/wsl/profile.patch.yml", 'model = "{}"\n'),
        ("lanes/research/lane.toml", 'model = "{}"\n'),
        ("config/dsh/profile.json", 'model = "{}"\n'),
        ("docs/adr/0099-pins.md", "| DeepSeek | {} |\n"),
        ("docs/handbook/models.md", "Run {} for review.\n"),
        ("AGENTS.md", "Review with {}.\n"),
        ("justfile", "review:\n    dsh --model {}\n"),
        ("scripts/launch.sh", 'model="{}"\n'),
        ("deploy/review/launcher", 'model="{}"\n'),
        (".github/review-prompt.md", "Use {}.\n"),
    ],
)
def test_the_ban_covers_each_live_surface_and_preserves_historical_research(
    tmp_path: Path,
    relative: str,
    text: str,
) -> None:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.format("deepseek-v4-pro"))
    historical = tmp_path / "docs/research/record.md"
    historical.parent.mkdir(parents=True, exist_ok=True)
    historical.write_text("The historical run used deepseek-v4-pro.\n")
    assert _superseded(tmp_path) == [f"{relative}: deepseek-v4-pro"]
    path.write_text(text.format("deepseek-flash"))
    assert _superseded(tmp_path) == []


def test_the_dsh_reviewers_model_has_ai_credits_pricing() -> None:
    """AWF v0.29.0's API proxy rejects an unpriced model with HTTP 400 (review-proof run 4)."""
    source = (ROOT / ".github" / "workflows" / "review.md").read_text()
    assert "\nmodel: anthropic/deepseek-flash\n" in source
    # DeepSeek's published peak rates for deepseek-flash, $/1M tokens, read 2026-11-07.
    assert (
        "models:\n  default-ai-credits-pricing:\n    input: 0.3\n    output: 1.2\n"
        "    cache_read: 0.006\n"
    ) in source
    lock = (ROOT / ".github" / "workflows" / "review.lock.yml").read_text()
    pricing = '"defaultAiCreditsPricing":{"input":0.3,"output":1.2,"cachedInput":0.006}'
    assert pricing.replace('"', '\\"') in lock
    # The Claude reviewer's opus alias resolves to claude-opus-5-5, which AWF prices itself.
    assert "\nmodel: opus\n" in (ROOT / ".github" / "workflows" / "review-claude.md").read_text()
