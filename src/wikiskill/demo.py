"""End-to-end demo run of the WikiSkill loop with the deterministic MockLLM."""
from __future__ import annotations

import argparse
import os

from .datasets import make_demo_dataset, _demo_tools
from .llm import MockLLM
from .orchestrator import EvolutionOrchestrator
from .workspace import Workspace


def run_demo(root: str = "wikiskill_demo_workspace", K: int = 3) -> dict:
    ws = Workspace(root)
    orch = EvolutionOrchestrator(
        llm=MockLLM(), dataset=make_demo_dataset(), ws=ws, tools=_demo_tools(), K=K)
    result = orch.run()
    eval_res = orch.evaluate_test()
    print("\nTest-set evaluation (final skills vs no-skill baseline):")
    print(f"  skilled accuracy : {eval_res['skilled_accuracy']:.4f}")
    print(f"  baseline accuracy: {eval_res['baseline_accuracy']:.4f}")
    print(f"  bootstrap p      : {eval_res['bootstrap_p_value']:.4f} "
          f"({'significant' if eval_res['significant'] else 'not significant'})")
    print("\nWorkspace layout:")
    for dirpath, _, files in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        for fn in sorted(files):
            print(f"  {os.path.join(rel, fn)}")
    return {**result, "evaluation": eval_res}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="WikiSkill demo (mock LLM, offline)")
    p.add_argument("--root", default="wikiskill_demo_workspace")
    p.add_argument("--iterations", type=int, default=3)
    a = p.parse_args()
    run_demo(a.root, a.iterations)
