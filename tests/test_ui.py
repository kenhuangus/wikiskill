import os
import time
import types

import pytest

from wikiskill import __version__
from wikiskill.webapp import create_app
from wikiskill.webapp.api import get_manager
from wikiskill.webapp.runner import RunManager, _is_fresh_root


def _wait_status(client, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get("/api/status")
        assert r.status_code == 200
        st = r.get_json()
        if st["state"] and st["state"]["status"] in ("done", "error"):
            return st
        time.sleep(0.05)
    raise AssertionError("run did not finish in time")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)   # relative workspace roots land under tmp_path
    app = create_app({"TESTING": True})
    get_manager()._reset_for_tests()
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------- basics
def test_index_serves_spa(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "WikiSkill" in html
    assert 'id="run-form"' in html
    assert 'id="console"' in html
    assert 'id="chart-rbest"' in html


def test_health(client):
    r = client.get("/api/health")
# ---------------------------------------------------------------- lifecycle
def test_full_run_lifecycle(client, tmp_path):
    root = "ui_test_run"
    r = client.post("/api/run", json={"llm_backend": "mock", "iterations": 3,
                                     "workspace_root": root})
    assert r.status_code == 202
    assert r.get_json()["active"] is True

    # single-flight: second start while active must be rejected
    r2 = client.post("/api/run", json={"llm_backend": "mock", "iterations": 3,
                                      "workspace_root": root + "_2"})
    assert r2.status_code == 409

    st = _wait_status(client)
    assert st["state"]["status"] == "done"
    result = st["state"]["result"]
    assert "unit-conversion" in result["evolution"]["final_skills"]
    assert result["evaluation"]["significant"] is True

    # workspace artifacts exist on disk
    assert (tmp_path / root / "wiki" / "index.md").is_file()
    assert (tmp_path / root / "skills" / "unit-conversion" / "SKILL.md").is_file()
    # string-tag subdirs for post-hoc test evaluation
    assert (tmp_path / root / "raw" / "eval_skilled").is_dir()


def test_status_empty(client):
    st = client.get("/api/status").get_json()
    assert st["active"] is False
    assert st["state"] is None
# ---------------------------------------------------------------- workspace & eval
def test_workspace_endpoint(client, tmp_path):
    root = "ui_ws_test"
    client.post("/api/run", json={"llm_backend": "mock", "iterations": 2,
                                 "workspace_root": root})
    _wait_status(client)

    r = client.get(f"/api/workspace?root={root}")
    assert r.status_code == 200
    data = r.get_json()
    assert data["root"] == root
    names = {c["name"] for c in data["tree"]["children"]}
    assert {"raw", "wiki", "skills"} <= names
    assert "wiki/index.md" in data["files"]
    assert "wiki/skill-impact.md" in data["files"]
    assert any(k.endswith("SKILL.md") for k in data["files"])

    assert client.get("/api/workspace?root=ui_does_not_exist").status_code == 404
    assert client.get("/api/workspace?root=../x").status_code == 400


def test_evaluate_endpoint(client, tmp_path):
    root = "ui_eval_test"
    client.post("/api/run", json={"llm_backend": "mock", "iterations": 2,
                                 "workspace_root": root})
    _wait_status(client)

    r = client.post("/api/evaluate", json={"llm_backend": "mock",
                                           "workspace_root": root})
    assert r.status_code == 200
    ev = r.get_json()["evaluation"]
    assert ev["skilled_accuracy"] == 1.0
    assert ev["baseline_accuracy"] == 0.0
    assert ev["significant"] is True
    assert client.post("/api/evaluate", json={"llm_backend": "mock",
                                              "workspace_root": "missing"}).status_code == 404


# ---------------------------------------------------------------- SSE
def test_sse_stream(client):
    r = client.post("/api/run", json={"llm_backend": "mock", "iterations": 1,
                                     "workspace_root": "ui_sse_test"})
    assert r.status_code == 202
    stream = client.get("/api/stream")
    body = b""
    for chunk in stream.response:
        body += chunk
        if b'"type": "done"' in body:
            break
    assert b"data:" in body
    assert b'"done"' in body


# ---------------------------------------------------------------- RunManager units
def test_runmanager_double_start_rejected():
    mgr = RunManager()
    mgr._reset_for_tests()
    mgr._execute = types.MethodType(lambda self, rid, cfg: time.sleep(2), mgr)
    a = mgr.start({"llm_backend": "mock"})
    assert a["active"] is True
    with pytest.raises(PermissionError):
        mgr.start({"llm_backend": "mock"})
    mgr.cancel()
    mgr._reset_for_tests()


def test_runmanager_fresh_root_guard(tmp_path):
    assert _is_fresh_root(str(tmp_path / "new")) is True
    raw = tmp_path / "used" / "raw"
    raw.mkdir(parents=True)
    (raw / "iter_000").mkdir()
    assert _is_fresh_root(str(tmp_path / "used")) is False


def test_cancel(client, tmp_path, monkeypatch):
    # Slow the orchestrator so cancel lands mid-run (cooperative stop).
    import wikiskill.orchestrator as orch_mod
    original_run = orch_mod.EvolutionOrchestrator.run

    def slow_run(self):
        time.sleep(1.5)
        return original_run(self)

    monkeypatch.setattr(orch_mod.EvolutionOrchestrator, "run", slow_run)
    client.post("/api/run", json={"llm_backend": "mock", "iterations": 4,
                                 "workspace_root": "ui_cancel_run"})
    assert client.post("/api/cancel", json={}).status_code == 200
    st = _wait_status(client, timeout=20)
    assert st["state"]["status"] in ("done", "error")


def test_run_validation_400s(client):
    assert client.post("/api/run", json={"llm_backend": "bogus"}).status_code == 400
    assert client.post("/api/run", json={"llm_backend": "openai"}).status_code == 400  # no model
    assert client.post("/api/run", json={"llm_backend": "mock",
                                         "workspace_root": "../escape"}).status_code == 400
    assert client.post("/api/run", json={"llm_backend": "mock",
                                         "workspace_root": "C:\\abs"}).status_code == 400