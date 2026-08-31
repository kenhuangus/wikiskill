# WikiSkill — Design Document

Implements: arXiv:2608.27454v1 (WikiSkill). See `prd.md` for requirements.

## 1. Architecture overview

```
wikiskill/
├── pyproject.toml
├── src/wikiskill/
│   ├── __init__.py
│   ├── llm.py            # LLM provider abstraction: MockLLM, OpenAICompatLLM
│   ├── workspace.py      # Three-layer workspace: raw/, wiki/, skills/ + patch engine
│   ├── skills.py         # Skills layer: SKILL.md + PURPOSE.md, snapshot/rollback
│   ├── prompts.py        # System prompts (Inference / Wiki Maintainer / Skill Proposer)
│   ├── agents.py         # InferenceAgent, WikiMaintainer, SkillProposer (ReAct)
│   ├── orchestrator.py   # Algorithm 1: loop, gating, rollback, test evaluation (§4)
│   ├── metrics.py        # accuracy metric + paired bootstrap significance test
│   ├── datasets.py       # Task/Trace dataclasses + demo dataset
│   ├── webapp/           # Web UI (see ui_design.md): runner + Flask api + SPA
│   ├── demo.py           # End-to-end demo run with mock LLM
│   └── cli.py            # `wikiskill demo | evolve | serve` entry point
└── tests/                # unit, end-to-end, and UI tests
```

## 2. Core data model (`datasets.py`)

- `Task(x, y, meta)` — task instance + ground truth (paper: 𝒟 = {(x_i, y_i)}).
- `ToolCall / Trajectory` — trace `τ = (o1, a1, ..., oT, aT)` captured as messages +
  structured metadata (final answer, correct flag, tool calls and outputs).
- `ToolSpec(name, description, fn)` — environment tools 𝒰 (bash-like demo tools, `read_file`
  for the proposer).

## 3. Workspace (`workspace.py`) — the three layers

`Workspace(root)` manages:

## 4. LLM abstraction (`llm.py`)

```python
class LLM(Protocol):
    def chat(self, messages: list[dict], **kw) -> str: ...
```

- `OpenAICompatLLM`: calls any OpenAI-compatible `/chat/completions` endpoint
  (configurable base_url, api_key via env, model, temperature). Uses `urllib` (no hard deps).
- `MockLLM`: deterministic scripted responder for tests/demo. Routes on content:
  - Maintainer JSON → returns a small valid wiki update JSON.
  - Proposer JSON → returns a valid create-skill proposal.
  - Inference → returns a demo answer (extracted from task text).
- Robust JSON extraction helper (`extract_json`) shared by all agents (strips code fences).

## 5. Agents (`agents.py`)

### 5.1 Inference Agent
Runs one task: system prompt = task-type prompt + **injected active skills**
(full SKILL.md contents, no wiki access — paper §3.2/ablation). Loop:
LLM → tool call → observation → ... → final `ANSWER: ...` line or max turns.
Returns `Trajectory` (messages, tool calls, final answer, correct flag).

### 5.2 Wiki Maintainer (`M_WM`)
One LLM call (full-batch; paper Appendix D: B = N_train). Input: current wiki context
(index + all pattern pages + logs + skill-impact) and the stratified trace sample.
Output JSON parsed into workspace ops:
`create_patterns[]`, `update_patterns[] (edits[])`, `update_index`, `append_log`.
A **stratified sampler** picks ≤5 failing + ≤3 passing traces, each truncated to 15,000 chars.

### 5.3 Wiki-Informed Skill Proposer (`M_P`) — ReAct
Loop of up to `max_react_turns` (default 20, paper: ~10–20):
- Initial context: wiki index, `skill-impact.md`, pass/fail outcome summary (no pre-sampled traces).
- Tools: `read_file(path)` (workspace-scoped) + `finish(...)` to emit the final proposal.
- Final output JSON: `{"action": "create"|"patch", "skill": name, "content"/"edits": [...],
  "purpose": mapping to wiki patterns}` — atomic, single-skill per paper §3.2.3.

## 6. Orchestrator (`orchestrator.py`) — Algorithm 1

```python
EvolutionOrchestrator(llm, tools, dataset, workspace, metric, K, ...).run()
```
Per iteration k (state S_k, W_k exactly as in the paper):
1. early stop if `R_best == 1.0`;
2. roll out training tasks with S_{k-1} → raw traces (skill injection, wiki hidden);
3. stratified sample T_sample,k;
4. `W'_k = M_WM(W_{k-1}, T_sample,k)`;
5. `P_k = M_P(W'_k, S_{k-1}, T_train,k)`;
6. snapshot skills; `S'_k = Apply(S_{k-1}, P_k)`;
7. validate on D_val → `R(T_val,k)`;
8. accept iff `R > R_best` else restore snapshot (skills-only rollback);
9. `W_k = Update(W'_k, P_k, R, a_k)` → append unified diff + outcome to `skill-impact.md`;
10. persist run state (history JSON: per-iteration scores, accept/reject, best).

## 7. Metrics & significance (`metrics.py`)

- `accuracy(traces)` — fraction correct.
- `paired_bootstrap(mine, base, n=1000, seed)` — resample test tasks with replacement,
  return p-value that margins ≤ 0; used for "best method" claims (paper Appendix C).

## 8. Demo dataset (`datasets.py`)

`make_demo_dataset(seed)`: synthetic "unit-conversion" arithmetic tasks. The no-skill agent
often errs (rounding/format pitfalls baked into the mock); a good skill (the mock proposer
writes one) nudges the inference prompt to compute correctly — so validation gating can
genuinely accept/reject. Also pluggable: any `Dataset` of `Task`s with tools + metric.

## 9. Error handling & robustness

- Malformed LLM JSON → retry once, then skip gracefully (maintainer: no-op update with log
  entry; proposer: proposal = None, iteration recorded as "no proposal").
- Missing files, bad patch targets → logged, op skipped (never crashes the loop).
- Path traversal blocked in `read_file`.

## 10. Testing strategy

- Unit: patch ops (exact/insert_after/append, invalid target), snapshot/restore,
  path allowlist, immutable raw layer.
- Integration: gating math (accept on strict improvement, reject on equal/lower),
  skill-impact.md written by harness with unified diff.
- E2E: MockLLM-driven full loop (K=3) — assert artifacts exist, acceptance behavior,
  early-stop at R_best=1.0.


- **Raw layer**: `add_raw_trace(iter_k, task_id, trace_dict)` writes
  `raw/iter_{k}/{task_id}.json`. Immutable: an existing file is never rewritten (enforced).
- **Wiki layer** (`wiki/`):
  - `patterns/` pages: markdown files; updates via a patch engine implementing exactly the
    three ops from the paper's Maintainer prompt: `append`, `replace` (exact-substring
    target), `insert_after` (exact-substring target).
  - `index.md`: full-content rewrite (maintainer always supplies complete index).
  - `logs.md`: append-only evolution log.
  - `skill-impact.md`: append-only; the **orchestrator** (not any agent) writes the
    programmatic entry after gating: iteration, proposal metadata, target skill, unified
    diff (`difflib.unified_diff` of skill content), validation score, accept/reject.
- **Skills layer**: `skills/<name>/SKILL.md` + `PURPOSE.md`.
  - `apply_proposal(P)`: create (new dir with SKILL.md + PURPOSE.md) or patch (patch ops on
    SKILL.md, mirrored to PURPOSE.md updates).
  - `snapshot()` / `restore(snapshot)`: cheap rollback of the Skills layer only (dict of
    name → content; rollback deletes/rewrites files accordingly). Wiki/raw untouched.
- `read_file(rel_path)` with a path-allowlist (agents may only read within the workspace)
  — used by the ReAct Skill Proposer.
