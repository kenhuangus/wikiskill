"""Evolutionary agents (paper §3.2): InferenceAgent, WikiMaintainer, SkillProposer."""
from __future__ import annotations

import json
import re
from typing import Callable, Dict, List, Optional

from .llm import LLM, extract_json
from .prompts import INFERENCE_SYSTEM, SKILL_PROPOSER_SYSTEM, WIKI_MAINTAINER_SYSTEM
from .skills import SkillsLayer
from .workspace import Workspace

ANSWER_RE = re.compile(r"ANSWER:\s*(.+)", re.IGNORECASE)


def _parse_answer(text: str) -> Optional[str]:
    m = ANSWER_RE.search(text or "")
    return m.group(1).strip() if m else None


class InferenceAgent:
    """§3.2.1: π(x_i; S). Active skills are injected; wiki access is NOT given."""

    def __init__(self, llm: LLM, tools: list, ws: Workspace, skills: SkillsLayer,
                 max_turns: int = 6):
        self.llm, self.ws, self.skills = llm, ws, skills
        self.tools = {t.name: t for t in tools}
        self.max_turns = max_turns

    def run(self, task) -> "object":
        from .datasets import Trajectory
        system = INFERENCE_SYSTEM.replace("{active_skills}",
                                          self.skills.active_skills_context())
        messages: List[dict] = [{"role": "system", "content": system},
                                {"role": "user", "content": task.x}]
        tool_calls: List[dict] = []
        final: Optional[str] = None
        for _ in range(self.max_turns):
            text = self.llm.chat(messages, temperature=0.0)
            messages.append({"role": "assistant", "content": text})
            parsed = _parse_answer(text)
            if parsed is not None:
                final = parsed
                break
            tm = re.search(r'TOOL:\s*(\S+)\s*(\{.*\})?', text, re.DOTALL)
            if not tm or tm.group(1) not in self.tools:
                messages.append({"role": "user", "content":
                                 "Please reply with TOOL: <name> {json args} or a final "
                                 "'ANSWER: ...' line."})
                continue
            tool = self.tools[tm.group(1)]
            try:
                args = json.loads(tm.group(2) or "{}")
            except json.JSONDecodeError:
                args = {}
            obs = tool.fn(**args)
            tool_calls.append({"tool": tool.name, "args": args, "observation": obs})
            messages.append({"role": "user", "content": f"Observation: {obs}"})
        traj = Trajectory(task_id=task.id, messages=messages, tool_calls=tool_calls,
                          final_answer=final, correct=False, prediction=final)
        traj.correct = (final is not None and str(final).strip() == str(task.y).strip())
        return traj


def stratified_sample(traces: List, max_fail: int = 5, max_pass: int = 3,
                      max_chars: int = 15000) -> List:
    """Paper Appendix C: <=5 failing + <=3 passing traces. Each individual execution
    log is capped at max_chars (15,000 in the paper) prior to prompt injection."""
    fails = [t for t in traces if not t.correct][:max_fail]
    passes = [t for t in traces if t.correct][:max_pass]
    sampled = fails + passes
    for t in sampled:
        # Cap the WHOLE execution log, not just one message: greedily truncate
        # message contents (longest first) until the serialized trace fits.
        def total_len(msgs):
            return sum(len(str(m.get("content", ""))) for m in msgs)
        msgs = t.messages
        while total_len(msgs) > max_chars:
            longest = max(range(len(msgs)),
                          key=lambda i: len(str(msgs[i].get("content", ""))))
            content = str(msgs[longest].get("content", ""))
            keep = max(0, len(content) - (total_len(msgs) - max_chars) - 30)
            msgs[longest] = dict(msgs[longest],
                                 content=content[:keep] + "\n...[truncated]")
            if len(content) <= 40:  # cannot shrink further; avoid infinite loop
                break
    return sampled


class WikiMaintainer:
    """§3.2.2: W'_k = M_WM(W_{k-1}, T_sample,k). One LLM call per iteration."""

    def __init__(self, llm: LLM, ws: Workspace):
        self.llm, self.ws = llm, ws

    def consolidate(self, sampled_traces: List[dict], iteration: int) -> dict:
        trace_dump = json.dumps([t.to_dict() for t in sampled_traces],
                                indent=1, ensure_ascii=False)
        user = (f"## Iteration {iteration}\n\n## Current wiki context\n"
                f"{self.ws.wiki_context()}\n\n## Latest execution traces\n{trace_dump}\n\n"
                "Produce the wiki update JSON now.")
        messages = [{"role": "system", "content": WIKI_MAINTAINER_SYSTEM},
                    {"role": "user", "content": user}]
        parsed = extract_json(self.llm.chat(messages, temperature=0.2))
        if parsed is None:  # one retry, then graceful no-op
            parsed = extract_json(self.llm.chat(messages + [{"role": "user", "content":
                                   "Your previous reply was not valid JSON. Return ONLY the JSON object."}],
                                   temperature=0.0))
        return parsed or {}

class SkillProposer:
    """§3.2.3: P_k = M_P(W'_k, S_{k-1}, T_train,k). Multi-turn ReAct agent that
    reads the wiki index, skill-impact tracker, and traces on demand via read_file."""

    def __init__(self, llm: LLM, ws: Workspace, skills: SkillsLayer, max_turns: int = 20):
        self.llm, self.ws, self.skills = llm, ws, skills
        self.max_turns = max_turns

    def propose(self, outcome_summary: str, iteration: int) -> Optional[dict]:
        index = self.ws.wiki_index() or "(empty wiki)"
        impact = self.ws.skill_impact() or "(no proposals yet)"
        user = (f"## Iteration {iteration}\n\n## Wiki index\n{index}\n\n"
                f"## Skill impact history\n{impact}\n\n"
                f"## Training task outcomes (pass/fail summary)\n{outcome_summary}\n\n"
                "Use read_file to inspect pattern pages (wiki/patterns/...) and raw traces "
                "(raw/iter_.../...) as needed, then finish with your atomic proposal JSON.")
        messages = [{"role": "system", "content": SKILL_PROPOSER_SYSTEM},
                    {"role": "user", "content": user}]
        for _ in range(self.max_turns):
            text = self.llm.chat(messages, temperature=0.2)
            parsed = extract_json(text)
            if parsed and parsed.get("action") in ("create", "patch"):
                return parsed
            fm = re.search(r'"path"\s*:\s*"([^"]+)"', text)
            if fm:
                obs = self.ws.read_file(fm.group(1))
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user",
                                 "content": f"read_file observation:\n{obs}"})
                continue
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content":
                             "Reply with a read_file tool call or the finish JSON."})
        return None

