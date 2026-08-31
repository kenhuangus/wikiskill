# WikiSkill — Implementation

[![CI](https://github.com/kenhuangus/wikiskill/actions/workflows/ci.yml/badge.svg)](https://github.com/kenhuangus/wikiskill/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)

Python implementation of **"WikiSkill: Compiling Agent Experience into Persistent
Knowledge for Skill Evolution"** (arXiv:2608.27454v1, Tang et al., Google Research).

Docs: see [`prd.md`](prd.md) (requirements), [`design.md`](design.md) (architecture),
[`plan.md`](plan.md) (build plan).

## Credits & Attribution

This project is an independent, open-source reimplementation of the research paper:

> **WikiSkill: Compiling Agent Experience into Persistent Knowledge for Skill Evolution**
> Liyan Tang, Cyrus Rashtchian, Chun-Sung Ferng, Andrew Tomkins, Da-Cheng Juan, Tu Vu —
> **Google Research** (and Virginia Tech).
> arXiv:2608.27454v1 [cs.AI], 27 Aug 2026. License: CC BY 4.0.
> Paper: https://arxiv.org/abs/2608.27454

All credit for the WikiSkill **method, algorithm (Algorithm 1), three-layer knowledge
architecture, agent designs, experimental findings, and agent prompts (Appendix E)**
belongs to the Google Research authors. This repository reimplements the framework in
code for study/experimentation purposes and is **not** an official Google product.
Agent system prompts in [`src/wikiskill/prompts.py`](src/wikiskill/prompts.py) are
condensed adaptations of those published in the paper (CC BY 4.0); adaptations in this
repo are released under the same spirit — please cite the original paper if you use
this work:

```bibtex
@article{tang2026wikiskill,
  title   = {WikiSkill: Compiling Agent Experience into Persistent Knowledge
             for Skill Evolution},
  author  = {Tang, Liyan and Rashtchian, Cyrus and Ferng, Chun-Sung and
             Tomkins, Andrew and Juan, Da-Cheng and Vu, Tu},
  journal = {arXiv preprint arXiv:2608.27454},
  year    = {2026},
  note    = {Google Research}
}
```


## What it implements

- **Three-layer workspace** (paper §3.1): immutable `raw/` traces, persistent `wiki/`
  (patterns + index + logs + skill-impact tracker), active `skills/` (SKILL.md + PURPOSE.md).
- **Evolutionary loop** (paper Algorithm 1, §3.2): Inference Agent rollouts with skill
  injection but **no wiki access**; Wiki Maintainer consolidation (create/update pattern
  pages via `append`/`replace`/`insert_after` patches); a **ReAct Skill Proposer** that
  reads the wiki and raw traces on demand and emits one atomic skill proposal.
- **Gating & rollback** (§3.2.4): accept iff validation score strictly improves `R_best`;
  otherwise roll back **skills only** — the wiki is never rolled back. The harness
  programmatically appends proposal + unified diff + outcome to `wiki/skill-impact.md`.
- **Stratified trace sampling** (App. C): ≤5 failing + ≤3 passing traces, 15,000-char cap.
- **Paired bootstrap significance testing** (App. C) in `metrics.py`.
- Early stop when `R_best == 1.0`.

## Web UI

An interactive workbench for running and inspecting the evolution loop:

```bash
pip install -e ".[ui]"        # installs Flask
wikiskill serve               # http://127.0.0.1:5000
# or: python -m wikiskill.cli serve --port 5000
```

Tabs (see `ui_design.md` for the full design):
- **Run** — configure backend (offline Mock or any OpenAI-compatible endpoint),
  iterations, ReAct turns; start/cancel; live SSE console including the Skill
  Proposer's ReAct `read_file` steps.
- **Dashboard** — R_best curve, accepted/rejected validation-gating bars, history table.
- **Evaluation** — final skills vs no-skill baseline on the test split with paired
  bootstrap p-value (paper §4 + App. C); re-evaluate any workspace.
- **Workspace** — browse the three-layer workspace (`raw/`, `wiki/`, `skills/`) and
  view any artifact (JSON pretty-printed, traces, diffs).
- **Knowledge** — evolved skills (SKILL.md + PURPOSE.md), wiki pattern pages, index,
  evolution log, skill-impact audit trail.
- **How it works** — the pipeline, Algorithm 1 pseudocode, and glossary mapped to the
  paper.

## Quickstart (CLI)

```bash
pip install -e ".[dev]"
pytest                                  # 29 tests: unit + end-to-end + UI
python -m wikiskill.demo                # offline demo with the deterministic MockLLM
python -m wikiskill serve               # same as `wikiskill serve`
```

Demo output: a `wikiskill_demo_workspace/` with `raw/`, `wiki/`, `skills/` populated,
accepted/rejected proposals logged in `wiki/skill-impact.md`, and `run_state.json`.

## Using a real LLM

```bash
wikiskill evolve --tasks tasks.jsonl \
  --train-ids train.txt --val-ids val.txt --test-ids test.txt \
  --model <model-name> --base-url https://your-endpoint/v1
```

API key is read from `--api-key`, `WIKISKILL_API_KEY`, or `OPENAI_API_KEY`.
Any OpenAI-compatible `/chat/completions` endpoint works (including local vLLM, as in
the paper). `tasks.jsonl` lines: `{"id", "x", "y", "meta?"}`.

Layout
```
src/wikiskill/
├── workspace.py    # three layers + patch engine + scoped read_file
├── skills.py       # skills layer, apply_proposal, skills-only snapshot/rollback
├── agents.py       # InferenceAgent, WikiMaintainer, ReAct SkillProposer, stratified_sample
├── orchestrator.py # Algorithm 1 with gating/rollback + audit trail + test evaluation
├── prompts.py      # agent system prompts (adapted from paper Appendix E)
├── llm.py          # LLM protocol, OpenAI-compatible client, MockLLM, extract_json
├── metrics.py      # accuracy + paired bootstrap (1,000 iterations)
├── datasets.py     # dataclasses + synthetic demo dataset
├── webapp/         # Flask UI (runner + api + SPA: see ui_design.md)
├── demo.py / cli.py  # `wikiskill demo | evolve | serve`
└── tests/…         # unit + end-to-end + UI tests
```

## Notes & limitations (mirroring the paper)

- Skills are injected directly into the prompt (no retrieval), matching the paper's setup.
- Gating requires strict improvement; neutral proposals are rejected (paper Limitations).
- The wiki accumulates without pruning (paper Limitations).
