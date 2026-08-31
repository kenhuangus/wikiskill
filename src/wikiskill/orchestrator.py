"""Evolution orchestrator — paper Algorithm 1 (Appendix A.1) with §3.2.4 gating."""
from __future__ import annotations

import json
import os
from typing import Callable, List, Optional

from .agents import InferenceAgent, SkillProposer, WikiMaintainer, stratified_sample
from .datasets import Dataset, Trajectory
from .llm import LLM
from .skills import SkillsLayer
from .workspace import Workspace


class EvolutionOrchestrator:
    """Co-evolves (S_k, W_k) per Algorithm 1:

    S0 = W0 = ∅; R_best = R(T_val,0)
    for k = 1..K:
        if R_best == 1.0: break
        T_train,k = {τ ~ π(x; S_{k-1})} on D_train         # inference, no wiki
        T_sample,k ⊂ T_train,k                             # stratified (App. C)
        W'_k = M_WM(W_{k-1}, T_sample,k)                   # wiki maintenance
        P_k  = M_P(W'_k, S_{k-1}, T_train,k)               # ReAct proposer
        S'_k = Apply(S_{k-1}, P_k)
        validate S'_k on D_val
        accept iff R(T_val,k) > R_best else roll back skills (wiki retained)
        W_k = Update(W'_k, P_k, R(T_val,k), a_k)           # harness writes skill-impact.md
    return S_K, W_K
    """

    def __init__(self, llm: LLM, dataset: Dataset, ws: Workspace, tools: list,
                 metric: Callable[[List[bool]], float] = None, K: int = 8,
                 max_react_turns: int = 20, log: Optional[Callable[[str], None]] = None):
        from .metrics import accuracy
        self.llm = llm
        self.dataset = dataset
        self.ws = ws
        self.metric = metric or accuracy
        self.K = K
        self.skills = SkillsLayer(ws)
        self.inference = InferenceAgent(llm, tools, ws, self.skills)
        self.maintainer = WikiMaintainer(llm, ws)
        self.proposer = SkillProposer(llm, ws, self.skills, max_turns=max_react_turns)
        self.log = log or (lambda s: print(s, flush=True))
        self.history: List[dict] = []
        self.r_best = -1.0

    # ------------------------------------------------------------------
    def _rollout(self, tasks, iteration: int, split: str) -> List[Trajectory]:
        trajs = [self.inference.run(t) for t in tasks]
        for t in trajs:
            self.ws.add_raw_trace(iteration, t.task_id,
                                  {**t.to_dict(), "split": split, "iteration": iteration})
        return trajs

    def _score(self, trajs: List[Trajectory]) -> float:
        return self.metric([t.correct for t in trajs])

    def _outcome_summary(self, trajs: List[Trajectory], tasks) -> str:
        by_id = {t.id: t for t in tasks}
        return "\n".join(
            f"{tr.task_id}: {'PASS' if tr.correct else 'FAIL'} | "
            f"predicted={tr.prediction!r} ground_truth={by_id[tr.task_id].y!r} "
            f"| trace: raw/iter_*/{tr.task_id}.json" for tr in trajs)

    def _baseline_validation(self) -> None:
        self.log("Baseline validation (S0 = empty) ...")
        trajs = self._rollout(self.dataset.val, 0, "val")
        self.r_best = self._score(trajs)
        self.log(f"R_best = {self.r_best:.4f}")

    # ------------------------------------------------------------------
    def run(self) -> dict:
        self._baseline_validation()
        for k in range(1, self.K + 1):
            if self.r_best >= 1.0:
                self.log("R_best reached 1.0; early stop.")
                break
            self.log(f"\n=== Iteration {k}/{self.K} ===")
            # lines 8-9: training rollouts + stratified sample
            train_trajs = self._rollout(self.dataset.train, k, "train")
            sampled = stratified_sample(train_trajs)
            # line 10: wiki maintenance
            update = self.maintainer.consolidate(sampled, k)
            report = self.ws.apply_maintainer_update(update) if update else {}
            self.log(f"Wiki: created={report.get('created')} updated={report.get('updated')} "
                     f"errors={report.get('errors')}")
            # line 11: skill proposal
            proposal = self.proposer.propose(
                self._outcome_summary(train_trajs, self.dataset.train), k)
            entry = {"iteration": k, "proposal": None, "val_score": None,
                     "accepted": False}
            if proposal:
                snap = self.skills.snapshot()
                try:
                    applied = self.skills.apply_proposal(proposal)
                except Exception as e:  # invalid proposal → skip iteration gracefully
                    self.log(f"Proposal invalid, skipped: {e}")
                    applied = None
                if applied is not None:
                    # lines 13-14: validate + gate
                    val_trajs = self._rollout(self.dataset.val, k, "val")
                    score = self._score(val_trajs)
                    accepted = score > self.r_best
                    if accepted:
                        self.r_best = score            # line 15
                    else:
                        self.skills.restore(snap)      # line 17: skills-only rollback
                    self.log(f"Proposal {applied['action']} '{applied['skill']}' -> "
                             f"val={score:.4f} ({'ACCEPTED' if accepted else 'REJECTED'})")
                    # line 19: harness records audit trail in skill-impact.md
                    diff = applied.get("diff", "(new skill)")
                    self.ws.record_skill_impact(
                        f"\n## Iteration {k} — {applied['action']} "
                        f"'{applied['skill']}'\n"
                        f"- validation score: {score:.4f}\n"
                        f"- outcome: {'Accepted' if accepted else 'Rejected'}\n"
                        f"- purpose: {proposal.get('purpose', '')}\n"
                        f"- diff:\n```diff\n{diff}\n```\n")
                    entry.update({"proposal": applied.get("skill"),
                                  "action": applied["action"], "val_score": score,
                                  "accepted": accepted})
            else:
                self.log("No proposal produced this iteration.")
            self.history.append(entry)
        final_skills = self.skills.list_skills()
        result = {"r_best": self.r_best, "history": self.history,
                  "final_skills": final_skills}
        with open(os.path.join(self.ws.root, "run_state.json"), "w",
                  encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        self.log(f"\nEvolution complete. R_best={self.r_best:.4f}, skills={final_skills}")
        return result

