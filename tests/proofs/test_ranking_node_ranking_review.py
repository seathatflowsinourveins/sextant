"""N2b-2b fix round (Codex xhigh r1, P1 + P2): baseline identity and the ranking mode's pager.

The reviewer's witnesses (review-gpt-gates/n2b-7b75642-codex-r1, test_review_witnesses.py:64,
:82 and :239). :82 is unchanged. :64 and :239 also call the ranking-inputs producer and
``file_inputs``, which arrive in N2b-3; here the universe is rewritten directly and the build
takes no inputs. The checks they witness are otherwise the reviewer's.
"""

from __future__ import annotations

import hashlib
import json
from types import MethodType, SimpleNamespace

import pytest
from nautilus_trader.live import LiveNodeConfig
from test_ranking import NS, START, baseline
from test_ranking_node_ranking import argv

from sextant.ranking import node_ranking
from sextant.ranking.baseline import dump_baseline
from sextant.ranking.node_actor import RankingActor


def test_refuse_baselines_with_another_universe_digest(tmp_path):
    arguments = argv(tmp_path)
    path = tmp_path / "baselines" / "manifest.json"
    manifest = json.loads(path.read_text())
    universe = tmp_path / "universe.json"
    manifest["universe"] = {
        "path": str(universe),
        "sha256": hashlib.sha256(universe.read_bytes()).hexdigest(),
    }
    manifest["symbols"] = ["AAPL"]
    path.write_text(json.dumps(manifest))
    universe.write_text(json.dumps({"rows": [{"symbol": "AAPL"}, {"symbol": "IBM"}]}))
    with pytest.raises(node_ranking.RankingRefused, match=r"baseline.*universe"):
        node_ranking.parse(arguments)


def test_refuse_baselines_whose_manifest_names_no_universe(tmp_path):
    arguments = argv(tmp_path)
    path = tmp_path / "baselines" / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["universe"] = None  # the recipe's --symbols run: not tied to the K2 artifact
    path.write_text(json.dumps(manifest))
    with pytest.raises(node_ranking.RankingRefused, match=r"baseline.*universe"):
        node_ranking.parse(arguments)


def test_refuse_a_manifest_verified_baseline_from_the_wrong_feed(tmp_path):
    arguments = argv(tmp_path)
    path = tmp_path / "baselines" / "pre.json"
    text = dump_baseline(baseline(feed="boats"))
    path.write_text(text)
    manifest_path = path.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][path.name]["sha256"] = hashlib.sha256(text.encode()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(node_ranking.RankingRefused, match="baseline"):
        node_ranking.parse(arguments)


def test_cli_build_wires_a_pager_without_starting_a_node(tmp_path, monkeypatch, capsys):
    arguments, _ = node_ranking.parse(argv(tmp_path))
    captured = []

    class InertNode:
        def add_actor(self, actor):
            captured.append(actor)

    class InertBuilder:
        def add_data_client(self, *arguments):
            return self

        def build(self):
            return InertNode()

    monkeypatch.setattr(
        node_ranking.LiveNodeBuilder, "from_config", lambda *arguments: InertBuilder()
    )
    monkeypatch.setattr(node_ranking, "RankingActor", lambda config: config)
    node_ranking.build(arguments, inputs=lambda segment: None, config=LiveNodeConfig())
    actor = SimpleNamespace(
        primed=True,
        clock=SimpleNamespace(timestamp_ns=lambda: START),
        errors={},
        _paged={},
        _page=captured[0].page,
        _window_ns=60 * NS,
        _publish=lambda generation: None,
    )
    actor._fault = MethodType(RankingActor._fault, actor)
    actor._fault("clock", RuntimeError("offline node clock fixture"))
    assert actor.errors == {"clock": 1}
    assert actor._page is not None, "CLI uses page=None; a counted failure has no page transport"
    assert capsys.readouterr().err == "ranking page clock: RuntimeError\n"
