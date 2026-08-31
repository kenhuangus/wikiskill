# WikiSkill — Web UI Design Document

Companion to `design.md`. Describes the interactive web application that lets users
run the WikiSkill evolution loop, watch it live, inspect every produced artifact, and
evaluate the evolved skills — a visual, testable harness for the paper's Algorithm 1.

## 1. Goals

- **Run**: configure a WikiSkill evolution run (dataset, iterations, LLM backend) and
  start/stop it from the browser.
- **Watch**: stream the evolution live (logs, ReAct proposer steps, gating decisions).
- **Inspect**: browse the complete three-layer workspace (`raw/`, `wiki/`, `skills/`)
  produced by the run.
- **Evaluate**: compare final evolved skills vs. no-skill baseline on the test split
  with paired-bootstrap significance.
- **Understand**: an "How it works" view that maps the UI to the paper's architecture
  (Figure 2 / Algorithm 1).

Non-goals: skill editing, wiki pruning, multi-user auth. This is a local study tool.

## 2. User workflows

1. **Explore** — open `http://127.0.0.1:5000`, read How-it-works, browse an existing
   workspace from disk.
2. **Run** — Configure → Start → watch live events → switch to Dashboard/Workspace.
3. **Analyze** — inspect the evolution curve, accepted/rejected proposals, wiki
   patterns, raw traces, then Evaluate on the test split.
4. **Repeat** — tweak parameters (iterations, ReAct turns), start a new run in a fresh
   workspace, compare.

## 3. Information architecture (single page, six tabs)

| Tab | Purpose |
|-----|---------|
| **Run** | Configuration form + live console + status pill; start/cancel |
| **Dashboard** | R_best curve, per-iteration acceptance bars, history table |
| **Evaluation** | Test-split comparison (skilled vs baseline), bootstrap p-value |
| **Workspace** | File tree + viewer for raw/wiki/skills/run_state.json |
| **Knowledge** | Wiki index, pattern pages, evolution log, skill-impact tracker, skills |
| **How it works** | Layer diagram + Algorithm 1 pseudocode + glossary |

## 4. Screen details

### 4.1 Run tab
- **Config form**: LLM backend (`mock`|`openai`), model, base URL, API key (password
  field), temperature, max iterations (K), max ReAct turns, workspace root (empty =
  auto `runs/run_<timestamp>`).
### 4.3 Evaluation tab
- Big-number cards: Skilled accuracy, Baseline accuracy, Δ, bootstrap p-value.
- Horizontal bar comparison + verdict ("Skilled is significantly better", etc.).
- Re-evaluate button (re-runs `evaluate_test()` for the current workspace).

### 4.4 Workspace tab
- Left: collapsible file tree starting at the workspace root.
- Right: content viewer — JSON pretty-printed, markdown shown in raw + rendered form,
  diffs monospace.

### 4.5 Knowledge tab
- Sub-tabs: Skills (cards with SKILL.md + PURPOSE.md), Wiki patterns (list + pages),
  Evolution log, Skill-impact history.

### 4.6 How-it-works tab
- Static annotated pipeline of the three layers and four components, Algorithm 1
  pseudocode, and definitions table (S_k, W_k, P_k, T_train, R_best…).

## 5. Design system

- Dark-on-light ("paper" feel): background `#f7f7f5`, panels white `#fff`, ink `#1a1a1a`.
- Accent: indigo `#3b5bdb` (brand), success `#099268`, danger `#e03131`, warn `#f59f00`.
- Type: system stack; headings 600, mono stack for code/traces.
- Badges/pills for Accept/Reject and status; cards with 1px border, 10px radius.
- Charts rendered as inline SVG (zero JS chart libraries → works offline).

## 6. Backend contract

| Method/Path | Body/Query | Returns |
|---|---|---|
| `GET /` | — | SPA HTML |
| `GET /api/health` | — | `{ok, version}` |
| `POST /api/run` | config JSON | `202 {run_id}`; `400` validation; `409` busy |
| `GET /api/status` | — | `{active, state:{status, events[], result, error}}` |
| `GET /api/stream` | — | Server-Sent Events (`log`/`status`/`react`/`done`/`error`) |
| `POST /api/cancel` | — | `200 {cancelled}` |
| `GET /api/workspace?root=` | query | `{root, tree, files}` (text files) |
| `POST /api/evaluate` | `{workspace_root, llm_backend, …}` | evaluation report JSON |

Validation rules: workspace_root must be a *relative* path (no abs, no `..`); run
rejected with 409 if another run is active; run rejected if root already contains
evolution history (choose a fresh root to avoid clobbering the immutable raw layer).

### SSE protocol
Events: `{type:"log", message}`, `{type:"react", turn, kind, path?, found?}`,
`{type:"status", phase}`, `{type:"done", result}`, `{type:"error", error}`.
Heartbeat comments every 15 s; stream closes after `done`/`error`.

## 7. State model

Server (single flask app):
- `RunManager` — one active run; holds `RunState {run_id, status, events, result, error}`
  and an SSE queue; background daemon thread executes the `EvolutionOrchestrator`
  (MockLLM or OpenAICompatLLM) and wires `log` + proposer `on_step` to the queue;
  `cancel_event` lets the orchestrator stop between iterations.

Client (vanilla JS):
- `state = {config, status, events[], result, evaluation}`; tab rendering is
  pure functions over `state`; `EventSource('/api/stream')` drives updates.

## 8. Error handling & resilience

- JSON payloads only; unknown/invalid fields → 400 with message.
- Proposal failures / malformed LLM JSON are absorbed by the orchestrator (logged).
- Run exceptions → `type:"error"` event + status `error` (traceback stored, exposed
  via status).
- EventSource auto-reconnect on transient drops.
- All file reads limited to 200 kB per file and whitelisted extension set.

## 9. Accessibility & usability

- Semantic HTML (tabs as buttons with aria), keyboard navigation for tree, focus
  states, sufficient contrast, no motion-only information.

## 10. Testing strategy

- Backend: Flask test client (mock backend) — run lifecycle, status, workspace tree,
  evaluation, single-flight 409, validation 400s, cancel.
- Runner: unit test RunManager concurrency (double-start raises).
- E2E smoke: boot `wikiskill serve` on a port; fetch `/`, `/api/health`, run
  `/api/run` with mock, poll status to completion, verify workspace artifacts.
- Regression: full `pytest` suite (core + UI) must stay green.

## 11. Non-functional targets

- Zero CDN dependencies (offline usable).
- Startup < 1 s; mock run completes in seconds; UI remains responsive during runs
  (threaded Flask).
- Flask is the single new runtime dependency, grouped under `[project.optional-dependencies] ui`.
- **Actions**: Start, Cancel (appears while running). Status pill: idle | starting |
  running | evaluating | done | error.
- **Live console**: appended log lines; SSE-driven; auto-scrolls; monospace.
- **ReAct event log**: marks `read_file` calls (path + found/not-found) and final
  proposal, rendered inline in the console with icons.

### 4.2 Dashboard tab
- **R_best curve**: SVG polyline (x = iteration incl. baseline, y = R_best value).
- **Validation bars**: one bar per evaluated proposal, colored green=Accepted /
  red=Rejected; dashed baseline marker.
- **History table**: iteration, action, target skill, validation score, outcome.