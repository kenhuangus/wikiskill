import json

from wikiskill.datasets import make_demo_dataset, _demo_tools
from wikiskill.llm import MockLLM
from wikiskill.skills import SkillsLayer
from wikiskill.workspace import Workspace


def test_gating_math():
    """Strict improvement: accept iff score > R_best (paper eq. 4)."""
    def gate(score, r_best):
        return score > r_best
    assert gate(0.5, 0.5) is False   # ties are rejected
    assert gate(0.6, 0.5) is True
    assert gate(0.4, 0.5) is False


def test_e2e_evolution_loop(tmp_path, capsys):
    from wikiskill.orchestrator import EvolutionOrchestrator
    root = tmp_path / "ws"
    ws = Workspace(str(root))
    orch = EvolutionOrchestrator(llm=MockLLM(), dataset=make_demo_dataset(), ws=ws,
                                 tools=_demo_tools(), K=3)
    result = orch.run()

    # Baseline (no skill) fails on val; after skill creation, val should improve.
    assert result["r_best"] > 0.0
    assert "unit-conversion" in result["final_skills"]

    # Three-layer artifacts exist
    assert (root / "raw" / "iter_000").is_dir()       # baseline val rollouts
    assert (root / "raw" / "iter_001" / "train").exists() or \
        list((root / "raw" / "iter_001").glob("*.json"))
    assert (root / "wiki" / "patterns" / "rounding-errors.md").is_file()
    assert (root / "wiki" / "index.md").is_file()
    assert (root / "wiki" / "logs.md").is_file()
    assert (root / "wiki" / "skill-impact.md").is_file()
    assert (root / "skills" / "unit-conversion" / "SKILL.md").is_file()
    assert (root / "skills" / "unit-conversion" / "PURPOSE.md").is_file()

    # Harness wrote the audit trail with outcome + diff
    impact = (root / "wiki" / "skill-impact.md").read_text(encoding="utf-8")
    assert "Accepted" in impact

    # run_state.json persisted
    state = json.loads((root / "run_state.json").read_text(encoding="utf-8"))
    assert state["final_skills"] == ["unit-conversion"]


def test_e2e_early_stop_at_perfect_val(tmp_path):
    from wikiskill.orchestrator import EvolutionOrchestrator
    ws = Workspace(str(tmp_path / "ws"))
    orch = EvolutionOrchestrator(llm=MockLLM(), dataset=make_demo_dataset(), ws=ws,
                                 tools=_demo_tools(), K=5)
    result = orch.run()
    # With the skill accepted, val = 1.0 -> the loop must early-stop.
    assert result["r_best"] == 1.0
    assert len(result["history"]) <= 2
