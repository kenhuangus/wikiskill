"""RunManager: executes the WikiSkill evolution loop in a background thread and
streams progress to the browser via Server-Sent Events (ui_design.md §6–§7)."""
from __future__ import annotations

import datetime as _dt
import json
import os
import queue
import threading
import traceback as _tb
import uuid
from typing import Optional

from ..datasets import _demo_tools, make_demo_dataset
from ..llm import MockLLM, OpenAICompatLLM
from ..orchestrator import EvolutionOrchestrator
from ..workspace import Workspace


def _is_fresh_root(path: str) -> bool:
    """True if the workspace root has no prior evolution history (raw/iter_*)."""
    raw = os.path.join(path, "raw")
    if not os.path.isdir(raw):
        return True
    return not any(d.startswith("iter_") for d in os.listdir(raw))


class RunManager:
    """Single-flight run manager. `start` spawns a daemon thread; `stream` yields SSE."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state: Optional[dict] = None
        self._events: "queue.Queue[dict]" = queue.Queue()
        self._cancel_event = threading.Event()

    # ---- public API ----------------------------------------------------
    @property
    def active(self) -> bool:
        with self._lock:
            return bool(self._state and self._state.get("status")
                        in ("starting", "running", "evaluating"))

    def status(self) -> dict:
        # Read without holding the lock while computing `active` — the property
        # also acquires the (non-reentrant) lock, which would deadlock.
        state = self._state
        return {"active": bool(state and state.get("status")
                               in ("starting", "running", "evaluating")),
                "state": state}

    def start(self, config: dict) -> dict:
        with self._lock:
            if self._state and self._state.get("status") in (
                    "starting", "running", "evaluating"):
                raise PermissionError("another evolution run is already active")
            run_id = uuid.uuid4().hex[:12]
            self._state = {"run_id": run_id, "config": dict(config), "status":
                           "starting", "events": [], "result": None, "error": None}
            self._cancel_event = threading.Event()
        threading.Thread(target=self._execute, args=(run_id, dict(config)),
                         daemon=True).start()
        return {"run_id": run_id, "active": True}

    def cancel(self) -> bool:
        self._cancel_event.set()
        return True

    def _reset_for_tests(self) -> None:
        """Test-only: drop state and queue so a fresh run can start."""
        with self._lock:
            self._state = None
            self._cancel_event = threading.Event()
            while True:
                try:
                    self._events.get_nowait()
                except queue.Empty:
                    break

    # ---- streaming -----------------------------------------------------
    def _emit(self, **payload) -> None:
        self._events.put(dict(payload))
        with self._lock:
            if self._state is not None:
                self._state["events"].append(dict(payload))
                self._state["events"] = self._state["events"][-500:]

    def stream(self):
        """SSE generator: emits events; closes after done/error."""
        while True:
            try:
                payload = self._events.get(timeout=15)
            except queue.Empty:
                yield ":\n\n"                 # heartbeat
                continue
            data = json.dumps(payload)
            yield f"data: {data}\n\n"
            if payload.get("type") in ("done", "error"):
                break

    # ---- execution -----------------------------------------------------
    def _build_llm(self, config: dict):
        backend = config.get("llm_backend", "mock")
        if backend == "openai":
            return OpenAICompatLLM(
                model=config.get("model", ""),
                base_url=config.get("base_url") or None,
                api_key=config.get("api_key") or None,
                temperature=float(config.get("temperature", 0.7)))
        return MockLLM()

    def _root_for(self, config: dict) -> str:
        root = config.get("workspace_root") or ""
        if root:
            return str(root).strip().strip("/").replace("\\", "/").strip("/")
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"runs/run_{stamp}"

    def _execute(self, run_id: str, config: dict) -> None:
        try:
            self._emit(type="status", phase="starting",
                       message="Preparing run...")
            root = self._root_for(config)
            if not _is_fresh_root(root):
                raise ValueError(
                    f"workspace root '{root}' already contains evolution history; "
                    "choose a fresh root (the raw layer is immutable)")
            llm = self._build_llm(config)
            ws = Workspace(root)
            orch = EvolutionOrchestrator(
                llm=llm, dataset=make_demo_dataset(), ws=ws, tools=_demo_tools(),
                K=int(config.get("iterations", 8)),
                max_react_turns=int(config.get("max_react_turns", 20)),
                cancel_event=self._cancel_event,
                log=lambda msg: self._emit(type="log", message=msg),
                proposer_on_step=lambda ev: self._emit(type="react", **ev))
            self._emit(type="status", phase="running", message=f"root={root}")
            result = orch.run()
            self._emit(type="status", phase="evaluating",
                       message="Evaluating evolved skills on the test split...")
            evaluation = orch.evaluate_test()
            with self._lock:
                if self._state is not None:
                    self._state["status"] = "done"
                    self._state["result"] = {"evolution": result,
                                             "evaluation": evaluation,
                                             "workspace_root": root}
            self._emit(type="done", result=self._state["result"] if self._state else
                       {"evolution": result, "evaluation": evaluation,
                        "workspace_root": root})
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            err = f"{type(exc).__name__}: {exc}"
            print(err, flush=True)
            print(_tb.format_exc(), flush=True)
            with self._lock:
                if self._state is not None:
                    self._state["status"] = "error"
                    self._state["error"] = err + "\n" + _tb.format_exc()
            self._emit(type="error", error=str(exc))
            self._state = None
            self._cancel_event = threading.Event()
            while True:
                try:
                    self._events.get_nowait()
                except queue.Empty:
                    break