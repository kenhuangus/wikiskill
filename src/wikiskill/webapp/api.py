"""Flask application factory + REST/SSE endpoints for the WikiSkill UI."""
from __future__ import annotations

import json
import os

from flask import Blueprint, Flask, Response, jsonify, render_template, request

from .. import __version__
from .runner import RunManager

bp = Blueprint("wikiskill_ui", __name__)

_manager: RunManager = None  # module-level singleton


def get_manager() -> RunManager:
    global _manager
    if _manager is None:
        _manager = RunManager()
    return _manager


def create_app(test_config=None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(SECRET_KEY="wikiskill-local-dev")
    if test_config:
        app.config.update(test_config)
    app.register_blueprint(bp)
    return app


def _safe_root(root: str) -> str:
    """Reject absolute paths and path traversal; normalize to a relative name."""
    root = (root or "").strip().replace("\\", "/").strip("/")
    if not root:
        raise ValueError("workspace root must not be empty")
    if os.path.isabs(root):
        raise ValueError("workspace root must be a relative path")
    if any(part == ".." for part in root.split("/")):
        raise ValueError("workspace root must not contain '..'")
    return root


# ---------------------------------------------------------------------------
@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/api/health")
def health():
    return jsonify({"ok": True, "version": __version__})


@bp.post("/api/run")
def start_run():
    config = request.get_json(silent=True) or {}
    backend = config.get("llm_backend", "mock")
    if backend not in ("mock", "openai"):
        return jsonify({"error": "llm_backend must be 'mock' or 'openai'"}), 400
    if backend == "openai" and not config.get("model"):
        return jsonify({"error": "'model' is required when llm_backend=openai"}), 400
    root = config.get("workspace_root")
    if root:
        try:
            _safe_root(root)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    try:
        info = get_manager().start(config)
    except PermissionError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify(info), 202


@bp.get("/api/status")
def status():
    return jsonify(get_manager().status())


@bp.get("/api/stream")
def stream():
    def gen():
        yield from get_manager().stream()
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


@bp.post("/api/cancel")
def cancel():
    return jsonify({"cancelled": get_manager().cancel()})


# ---------------------------------------------------------------------------
_TREE_SKIP = {".pytest_cache", "__pycache__", ".git"}
_TEXT_EXT = {".md", ".json", ".txt", ".py", ".toml", ".diff", ".log"}


@bp.get("/api/workspace")
def workspace():
    try:
        root = _safe_root(request.args.get("root", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not os.path.isdir(root):
        return jsonify({"error": f"workspace '{root}' does not exist",
                        "root": root}), 404
    return jsonify({"root": root, "tree": _build_tree(root),
                    "files": _read_text_files(root)})


def _build_tree(root: str) -> dict:
    def build(path: str) -> dict:
        name = os.path.basename(path) or root
        rel = os.path.relpath(path, root).replace("\\", "/")
        node = {"name": name, "path": rel, "type": "dir", "children": []}
        for entry in sorted(os.listdir(path)):
            if entry in _TREE_SKIP:
                continue
            full = os.path.join(path, entry)
            if os.path.isdir(full):
                node["children"].append(build(full))
            else:
                node["children"].append({
                    "name": entry,
                    "path": os.path.relpath(full, root).replace("\\", "/"),
                    "type": "file"})
        return node
    return build(root)


def _read_text_files(root: str) -> dict:
    """Collect text-file contents (bounded) for the UI viewer."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _TREE_SKIP]
        for fn in filenames:
            if os.path.splitext(fn)[1] not in _TEXT_EXT:
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace("\\", "/")
            try:
                with open(full, "r", encoding="utf-8") as f:
                    out[rel] = f.read(200_000)
            except (OSError, UnicodeDecodeError):
                out[rel] = "(unreadable/binary)"
    return out


# ---------------------------------------------------------------------------
@bp.post("/api/evaluate")
def evaluate():
    """Re-evaluate final skills vs baseline on the test split (paper §4)."""
    config = request.get_json(silent=True) or {}
    backend = config.get("llm_backend", "mock")
    if backend not in ("mock", "openai"):
        return jsonify({"error": "llm_backend must be 'mock' or 'openai'"}), 400
    try:
        root = _safe_root(config.get("workspace_root", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not os.path.isdir(root):
        return jsonify({"error": f"workspace '{root}' does not exist"}), 404

    from ..datasets import _demo_tools, make_demo_dataset
    from ..llm import MockLLM, OpenAICompatLLM
    from ..orchestrator import EvolutionOrchestrator
    from ..workspace import Workspace

    if backend == "openai":
        llm = OpenAICompatLLM(model=config.get("model", ""),
                              base_url=config.get("base_url") or None,
                              api_key=config.get("api_key") or None)
    else:
        llm = MockLLM()
    orch = EvolutionOrchestrator(llm=llm, dataset=make_demo_dataset(),
                                 ws=Workspace(root), tools=_demo_tools(),
                                 K=int(config.get("iterations", 8)),
                                 log=lambda msg: None)
    res = orch.evaluate_test()
    return jsonify({"evaluation": res, "workspace_root": root})