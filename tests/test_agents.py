from wikiskill.datasets import make_demo_dataset, _demo_tools
from wikiskill.llm import MockLLM, extract_json
from wikiskill.skills import SkillsLayer
from wikiskill.workspace import Workspace


def _ws(tmp_path):
    return Workspace(str(tmp_path / "ws"))


def test_extract_json():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('noise {"a": {"b": 2}} tail') == {"a": {"b": 2}}
    assert extract_json("no json") is None


def test_skills_create_snapshot_restore(tmp_path):
    skills = SkillsLayer(_ws(tmp_path))
    skills.apply_proposal({"action": "create", "skill": "s1",
                           "content": "# S1\nline1\nline2\n", "purpose": "why"})
    assert skills.list_skills() == ["s1"]
    snap = skills.snapshot()
    skills.apply_proposal({"action": "patch", "skill": "s1",
                           "edits": [{"op": "replace", "target": "line2",
                                      "content": "LINE2"}], "purpose": "why2"})
    assert "LINE2" in skills.skill_content("s1")
    skills.restore(snap)
    assert "LINE2" not in skills.skill_content("s1")
    skills.apply_proposal({"action": "create", "skill": "s2", "content": "x",
                           "purpose": "p"})
    skills.restore(snap)
    assert skills.list_skills() == ["s1"]


def test_skill_injection_context(tmp_path):
    skills = SkillsLayer(_ws(tmp_path))
    assert "(No active skills.)" in skills.active_skills_context()
    skills.apply_proposal({"action": "create", "skill": "s", "content": "BODY",
                           "purpose": "p"})
    assert "BODY" in skills.active_skills_context()


def test_mock_inference_without_and_with_skill(tmp_path):
    from wikiskill.agents import InferenceAgent
    ws = _ws(tmp_path)
    skills = SkillsLayer(ws)
    agent = InferenceAgent(MockLLM(), _demo_tools(), ws, skills)
    ds = make_demo_dataset()
    traj = agent.run(ds.val[0])
    assert traj.correct is False  # truncation error without skill
    skills.apply_proposal({"action": "create", "skill": "unit-conversion",
                           "content": "Round ONLY the final result to 2 decimal places.",
                           "purpose": "p"})
    agent2 = InferenceAgent(MockLLM(), _demo_tools(), ws, skills)
    traj2 = agent2.run(ds.val[0])
    assert traj2.correct is True


def test_stratified_sample():
    from wikiskill.agents import stratified_sample
    from wikiskill.datasets import Trajectory

    def t(i, ok):
        return Trajectory(task_id=i, messages=[{"role": "user", "content": "x"}],
                          tool_calls=[], final_answer="a", correct=ok)
    traces = [t(f"f{i}", False) for i in range(9)] + [t(f"p{i}", True) for i in range(5)]
    s = stratified_sample(traces)
    assert sum(1 for x in s if not x.correct) == 5
    assert sum(1 for x in s if x.correct) == 3
