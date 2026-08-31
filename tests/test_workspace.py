import pytest

from wikiskill.workspace import PatchError, Workspace, apply_edits


def test_patch_ops():
    c = "alpha\nbeta\n"
    assert apply_edits(c, [{"op": "append", "content": "gamma"}]) == "alpha\nbeta\ngamma"
    assert apply_edits(c, [{"op": "replace", "target": "beta", "content": "BETA"}]) \
        == "alpha\nBETA\n"
    assert apply_edits(c, [{"op": "insert_after", "target": "alpha", "content": " mid"}]) \
        == "alpha mid\nbeta\n"
    with pytest.raises(PatchError):
        apply_edits(c, [{"op": "replace", "target": "nope", "content": "x"}])
    with pytest.raises(PatchError):
        apply_edits(c, [{"op": "bogus", "content": "x"}])


def test_raw_layer_immutable(tmp_path):
    ws = Workspace(str(tmp_path / "ws"))
    ws.add_raw_trace(1, "t1", {"a": 1})
    with pytest.raises(FileExistsError):
        ws.add_raw_trace(1, "t1", {"a": 2})


def test_read_file_scoped(tmp_path):
    ws = Workspace(str(tmp_path / "ws"))
    assert "ERROR" in ws.read_file("missing.md")
    with pytest.raises(ValueError):
        ws.read_file("../outside.txt")


def test_maintainer_update(tmp_path):
    ws = Workspace(str(tmp_path / "ws"))
    report = ws.apply_maintainer_update({
        "create_patterns": [{"name": "p.md", "content": "# P\nbody\n"}],
        "update_patterns": [{"name": "p.md",
                             "edits": [{"op": "append", "content": "more\n"}]}],
        "update_index": "- [p](wiki/patterns/p.md): x\n",
        "append_log": "iter 1 findings",
    })
    assert report["created"] == ["p.md"] and report["updated"] == ["p.md"]
    assert ws.pattern_page("p.md").endswith("more\n")
    assert "[p]" in ws.wiki_index() and "iter 1" in ws.wiki_logs()
    ws.record_skill_impact("## entry\n- outcome: Accepted\n")
    assert "Accepted" in ws.skill_impact()
