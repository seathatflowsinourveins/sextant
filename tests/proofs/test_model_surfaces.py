"""ADR-0030's owner model-pins manifest row: superseded DeepSeek models are unavailable."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
POLICY = ROOT / "deploy/wsl/lane-runtimes/model-policy.json"
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
    "deepseek-official",  # dsh's provider id (the agent-default-model row), not a served model
    "deepseek-api-key",  # PerryLink/dsh-github's credential input name, not a model selection
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
    import yaml

    gate = yaml.safe_load((ROOT / ".github/workflows/gate.yml").read_text())
    codex = next(s for s in gate["jobs"]["codex"]["steps"] if s.get("id") == "review")["with"]
    claude = next(s for s in gate["jobs"]["claude"]["steps"] if s.get("id") == "review")["with"]
    assert codex["effort"] == "max"
    # The Claude reviewer's pin follows model-policy.json's reviewer entry (ADR-0030).
    reviewer = json.loads(POLICY.read_text())["claude_reviewer"]
    assert reviewer["effort"] == "max"
    assert f"--model {reviewer['model']} --effort max" in claude["claude_args"]
    patch = (ROOT / "config/dsh/mcp/max-effort.cordis.yml").read_text()
    assert "reasoningEffort: max" in patch
    action = (ROOT / ".github/actions/dsh-github/action.yml").read_text()
    assert "max-effort.cordis.yml" in action


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


def test_dsh_uses_the_native_provider_without_a_custom_pricing_proxy() -> None:
    import yaml

    gate = yaml.safe_load((ROOT / ".github/workflows/gate.yml").read_text())
    step = next(s for s in gate["jobs"]["dsh"]["steps"] if s.get("id") == "review")
    assert step["with"]["model"] == "deepseek-flash"
    assert step["with"]["engine"] == "model"
    assert not list((ROOT / ".github/workflows").glob("*.lock.yml"))
