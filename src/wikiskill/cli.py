"""CLI: `wikiskill demo` (offline mock) or `wikiskill evolve` (real LLM endpoint)."""
from __future__ import annotations

import argparse
import json
import os
import sys


def main(argv=None) -> int:
    p = argparse.ArgumentParser("wikiskill")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="run the offline demo with the mock LLM")
    d.add_argument("--root", default="wikiskill_demo_workspace")
    d.add_argument("--iterations", type=int, default=3)

    e = sub.add_parser("evolve", help="evolve skills on a JSONL task file")
    e.add_argument("--tasks", required=True, help="JSONL file with {id,x,y} objects")
    e.add_argument("--train-ids", required=True)
    e.add_argument("--val-ids", required=True)
    e.add_argument("--test-ids", required=True)
    e.add_argument("--root", default="wikiskill_workspace")
    e.add_argument("--model", required=True)
    e.add_argument("--base-url", default=None)
    e.add_argument("--api-key", default=None)
    e.add_argument("--iterations", type=int, default=8)

    s = sub.add_parser("serve", help="run the WikiSkill web UI (Flask)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=5000)
    s.add_argument("--debug", action="store_true")
    args = p.parse_args(argv)

    if args.cmd == "demo":
        from .demo import run_demo
        run_demo(args.root, args.iterations)
        return 0

    if args.cmd == "serve":
        try:
            from .webapp import create_app
        except ImportError as exc:
            print("The UI requires Flask. Install it with: "
                  "pip install -e '.[ui]'  (or: pip install flask)", file=sys.stderr)
            return 2
        app = create_app()
        app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
        return 0

    from .datasets import Dataset, Task, ToolSpec, load_jsonl
    from .llm import OpenAICompatLLM
    from .orchestrator import EvolutionOrchestrator
    from .workspace import Workspace

    rows = {r["id"]: r for r in load_jsonl(args.tasks)}

    def ids(path):
        with open(path, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]

    def to_tasks(id_list):
        return [Task(id=i, x=rows[i]["x"], y=rows[i]["y"], meta=rows[i].get("meta", {}))
                for i in id_list if i in rows]

    dataset = Dataset(train=to_tasks(ids(args.train_ids)),
                      val=to_tasks(ids(args.val_ids)),
                      test=to_tasks(ids(args.test_ids)))

    def calculator(expression: str) -> str:
        try:
            return repr(eval(expression, {"__builtins__": {}}, {}))
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: {exc}"

    tools = [ToolSpec("calculator", "Evaluate a Python arithmetic expression.", calculator)]
    llm = OpenAICompatLLM(model=args.model, base_url=args.base_url, api_key=args.api_key)
    orch = EvolutionOrchestrator(llm=llm, dataset=dataset,
                                 ws=Workspace(args.root), tools=tools,
                                 K=args.iterations)
    result = orch.run()
    # Paper §4: report final skills vs no-skill baseline on the test split with
    # paired bootstrap significance (paper Appendix C).
    evaluation = orch.evaluate_test()
    print(json.dumps({**result, "evaluation": evaluation}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
