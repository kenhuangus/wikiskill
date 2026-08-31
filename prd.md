# WikiSkill — PRD (Product Requirements Document)

Source paper: **"WikiSkill: Compiling Agent Experience into Persistent Knowledge for Skill Evolution"**
(Tang, Rashtchian, Ferng, Tomkins, Juan, Vu — Google Research / Virginia Tech, arXiv:2608.27454v1)

## 1. Background

Agent skills package specialized procedural knowledge into reusable, filesystem-based
resources. Recent methods (Trace2Skill, EvoSkill, SkillOpt) discover skills from agent
execution traces, but the insights that guide skill development remain scattered across
optimization histories, limiting systematic reuse across iterations.

WikiSkill co-evolves agent skills with a **persistent knowledge base (wiki)**. It separates
raw experience, accumulated knowledge, and executable skills, and continuously consolidates
experience into the wiki so that subsequent skill updates build on it.

## 2. Goals

- G1: Implement the full WikiSkill evolution loop (paper Algorithm 1) as a runnable Python framework.
- G2: Faithfully reproduce the paper's three-layer knowledge architecture (`raw/`, `wiki/`, `skills/`).
- G3: Implement the three evolutionary agents: Inference Agent, Wiki Maintainer, and a
      ReAct-style Wiki-Informed Skill Proposer.
- G4: Implement validation gating with skill-only rollback (the wiki is never rolled back).
- G5: Make the system testable end-to-end without any LLM API key (mock LLM provider),
      while supporting real providers (OpenAI-compatible APIs) for actual use.

## 3. Non-goals

- No skill retrieval/triggering: active skills are injected directly into the Inference
  Agent's prompt (per the paper's setup, which isolates skill quality).
- No re-implementation of baselines (Trace2Skill / EvoSkill / SkillOpt).
- No benchmark harnesses for the paper's exact datasets (LiveMath, SealQA, SpreadsheetBench,
  OfficeQA, ALFWorld); a simple demo dataset with an identical interface is provided instead.

## 4. Functional requirements

### FR1 — Three-layer workspace
- **Raw Layer (`raw/`)**: immutable execution traces per iteration (reasoning, tool calls,
  tool outputs, final answers, pass/fail, prediction vs. ground truth). Never modified.
- **Wiki Layer (`wiki/`)**: persistent, compounding; contains
  - `wiki/patterns/*.md` — pattern pages (failure modes / successful strategies + workarounds),
  - `wiki/index.md` — concise catalog of patterns,
  - `wiki/logs.md` — evolution log appended by the Wiki Maintainer each iteration,
  - `wiki/skill-impact.md` — skill impact tracker updated programmatically by the harness
    after gating (proposal metadata, target skill, unified diff, val score, accept/reject).
- **Skills Layer (`skills/<name>/`)**: each skill contains `SKILL.md` (frontmatter: name,
  description, plus procedural instructions) and `PURPOSE.md` (mapping to motivating wiki patterns).

### FR2 — Evolution loop (paper Algorithm 1)
1. Initialize `S0 = ∅`, `W0 = ∅`; baseline validation `R_best = R(T_val,0)`.
2. For k = 1..K (early-stop if `R_best == 1.0`):
   - Roll out Inference Agent on `D_train` with skills `S_{k-1}` (NO wiki access).
   - Sample `T_sample,k ⊂ T_train,k` (stratified: ≤5 failing, ≤3 passing traces; each trace
     capped at 15,000 characters).
   - Wiki Maintenance: `W'_k ← M_WM(W_{k-1}, T_sample,k)` — create/update pattern pages via
     patch operations, update index, append log.
   - Skill Proposal: `P_k ← M_P(W'_k, S_{k-1}, T_train,k)` — a ReAct agent that reads the wiki
     index, skill-impact tracker, outcome summary, and on-demand reads pattern pages and raw
     traces via a `read_file` tool. Produces ONE atomic proposal targeting a single skill
     (create new skill OR patch-based edit).
   - Apply: `S'_k = Apply(S_{k-1}, P_k)`.
   - Validate on `D_val`.
   - Gate: accept iff `R(T_val,k) > R_best` (strict improvement); otherwise roll back skills
     to `S_{k-1}`. Wiki is never rolled back.
   - Update wiki: append proposal metadata + diff + score + outcome to `skill-impact.md`.
3. Return final skill set `S_K` and wiki `W_K`.

### FR3 — Agents
- **Inference Agent**: LLM agent with environment tools; receives task context + injected
  active skill contents; multi-turn trajectory.
- **Wiki Maintainer**: single LLM call per iteration; outputs JSON with
  `create_patterns`, `update_patterns` (patch ops: append/replace/insert_after),
  `update_index` (full content), `append_log`.
- **Skill Proposer**: multi-turn ReAct agent (paper: ~10–20 turns) with `read_file` and a
  final structured proposal (create/patch one skill).

### FR4 — Gating and persistence
- Strict-improvement acceptance, rollback of skills only, programmatic `skill-impact.md` updates.
- Wiki state persists across all iterations and rollbacks.

### FR5 — Configurability & evaluation
- Pluggable LLM provider (mock / OpenAI-compatible), configurable K, tools, splits.
- Metric per dataset (accuracy); paired bootstrap significance testing helper (1,000 iterations)
  as in paper Appendix C.

## 5. Acceptance criteria

1. `pytest` passes: unit tests for workspace/patches/gating, and an end-to-end test of the
   full evolution loop using a scripted mock LLM.
2. A demo run (`python -m wikiskill.demo`) executes ≥2 evolution iterations, produces a
   workspace with all three layers populated, and accepts/rolls back proposals correctly.
3. Code mirrors paper notation (S_k, W_k, P_k, T_sample, R_best) and cites Algorithm 1 steps
   in docstrings.
