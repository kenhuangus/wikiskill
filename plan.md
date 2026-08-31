# WikiSkill — Implementation Plan

Source: paper + `prd.md` + `design.md`. Ordered milestones with verification gates.

## Milestone 0 — Project scaffold
- [ ] `wikiskill/pyproject.toml` (no third-party runtime deps; pytest for dev)
- [ ] Package skeleton `src/wikiskill/` + `tests/`
- Verify: `pip install -e .[dev]` works; `pytest` collects.

## Milestone 1 — Data model + LLM abstraction
- [ ] `datasets.py`: `Task`, `ToolSpec`, `Trajectory`, `Dataset`, demo dataset factory
- [ ] `llm.py`: `LLM` protocol, `OpenAICompatLLM` (urllib), `MockLLM`, `extract_json`
- Verify: unit test for `extract_json` + MockLLM routing.

## Milestone 2 — Three-layer workspace (paper §3.1)
- [ ] `workspace.py`: raw traces (immutable), wiki (patterns/index/logs/skill-impact),
      patch engine (`append`/`replace`/`insert_after`), skills (SKILL.md + PURPOSE.md),
      snapshot/restore, scoped `read_file`
- Verify: `test_workspace.py` passes (incl. immutability + path traversal).

## Milestone 3 — Agents (paper §3.2.1–3.2.3)
- [ ] `prompts.py`: three agent system prompts adapted from paper Appendix E
- [ ] `agents.py`: InferenceAgent (tool loop, skill injection, no wiki), WikiMaintainer
      (single call, JSON ops), SkillProposer (ReAct, ≤20 turns, `read_file`, atomic proposal)
- Verify: mock-driven unit tests for each agent's outputs.

## Milestone 4 — Orchestrator: gating & rollback (paper §3.2.4, Algorithm 1)
- [ ] `orchestrator.py`: full loop, stratified sampling (≤5 fail / ≤3 pass, 15k char cap),
      strict-improvement gate, skills-only rollback, programmatic `skill-impact.md` diff
      logging, early stop at R_best = 1.0, run history persistence
- Verify: `test_gating.py` passes (accept/reject math, wiki never rolled back).

## Milestone 5 — Metrics & significance (paper Appendix C)
- [ ] `metrics.py`: accuracy + paired bootstrap (1,000 iterations)
- Verify: unit test with seeded RNG.

## Milestone 6 — End-to-end validation
- [ ] `demo.py` + `cli.py`
- [ ] `test_e2e.py`: K=3 loop with MockLLM; assert layers populated, gating works, artifacts
- [ ] Live run: `python -m wikiskill.demo`
- Verify: all tests green; demo produces workspace with accepted skill or logged rejections.

## Milestone 7 — Documentation & wrap-up
- [ ] `README.md` (usage, mapping to paper)
- Final review of all docs vs. implementation.
