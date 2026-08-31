"""Three-layer workspace (paper §3.1): raw/ (immutable traces), wiki/ (persistent
knowledge), skills/ (active skill set), plus the patch engine used by agents."""
from __future__ import annotations

import difflib
import json
import os
import re
from typing import Dict, List, Optional

PATTERN_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.md$")


class PatchError(Exception):
    pass


def apply_edits(content: str, edits: List[dict]) -> str:
    """Patch engine (paper Wiki Maintainer prompt): append / replace / insert_after.

    `replace` and `insert_after` targets must be EXACT substrings. Invalid targets
    raise PatchError; callers may catch and skip individual ops.
    """
    for e in edits or []:
        op = e.get("op")
        if op == "append":
            content = content + e.get("content", "")
        elif op == "replace":
            target = e.get("target", "")
            if target not in content:
                raise PatchError(f"replace target not found: {target[:60]!r}")
            content = content.replace(target, e.get("content", ""), 1)
        elif op == "insert_after":
            target = e.get("target", "")
            if target not in content:
                raise PatchError(f"insert_after target not found: {target[:60]!r}")
            idx = content.index(target) + len(target)
            content = content[:idx] + e.get("content", "") + content[idx:]
        else:
            raise PatchError(f"unknown op: {op}")
    return content


class Workspace:
    """Manages the three layers of the WikiSkill agent workspace."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        for d in ("raw", os.path.join("wiki", "patterns"), "skills"):
            os.makedirs(os.path.join(self.root, d), exist_ok=True)

    # ---------- generic helpers ----------
    def _abs(self, rel: str) -> str:
        p = os.path.abspath(os.path.join(self.root, rel))
        if not p.startswith(self.root + os.sep) and p != self.root:
            raise ValueError(f"path escapes workspace: {rel}")
        return p

    def read_file(self, rel: str) -> str:
        """Workspace-scoped read (used by the ReAct Skill Proposer)."""
        p = self._abs(rel)
        if not os.path.isfile(p):
            return f"ERROR: file not found: {rel}"
        with open(p, "r", encoding="utf-8") as f:
            return f.read()

    def write_file(self, rel: str, content: str, overwrite: bool = True) -> None:
        p = self._abs(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if os.path.exists(p) and not overwrite:
            raise FileExistsError(rel)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)

    # ---------- Raw layer: immutable ----------
    def add_raw_trace(self, iteration: int, task_id: str, trace: dict) -> str:
        rel = os.path.join("raw", f"iter_{iteration:03d}", f"{task_id}.json")
        p = self._abs(rel)
        if os.path.exists(p):
            raise FileExistsError(f"raw layer is immutable: {rel}")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(trace, f, indent=2, ensure_ascii=False)
        return rel

    # ---------- Wiki layer ----------
    def wiki_index(self) -> str:
        return self.read_file("wiki/index.md") if os.path.isfile(
            self._abs("wiki/index.md")) else ""

    def wiki_logs(self) -> str:
        return self.read_file("wiki/logs.md") if os.path.isfile(
            self._abs("wiki/logs.md")) else ""

    def skill_impact(self) -> str:
        return self.read_file("wiki/skill-impact.md") if os.path.isfile(
            self._abs("wiki/skill-impact.md")) else ""

    def list_patterns(self) -> List[str]:
        d = self._abs(os.path.join("wiki", "patterns"))
        return sorted(f for f in os.listdir(d) if f.endswith(".md"))

    def pattern_page(self, name: str) -> str:
        if not PATTERN_NAME_RE.match(name):
            raise ValueError(f"bad pattern name: {name}")
        return self.read_file(os.path.join("wiki", "patterns", name))

    def wiki_context(self) -> str:
        """Full wiki context handed to the Wiki Maintainer (index + pages + logs)."""
        parts = ["# WIKI INDEX", self.wiki_index() or "(empty)"]
        for name in self.list_patterns():
            parts += [f"\n# PATTERN: {name}", self.pattern_page(name)]
        parts += ["\n# EVOLUTION LOG", self.wiki_logs() or "(empty)"]
        return "\n".join(parts)

    def apply_maintainer_update(self, update: dict) -> dict:
        """Apply M_WM's JSON ops (create/update patterns, index, log). Returns report."""
        report = {"created": [], "updated": [], "errors": []}
        for pat in update.get("create_patterns", []) or []:
            name = pat.get("name", "")
            if not PATTERN_NAME_RE.match(name):
                report["errors"].append(f"bad pattern name {name!r}")
                continue
            rel = os.path.join("wiki", "patterns", name)
            if os.path.exists(self._abs(rel)):
                report["errors"].append(f"pattern exists, use update: {name}")
                continue
            self.write_file(rel, pat.get("content", ""))
            report["created"].append(name)
        for pat in update.get("update_patterns", []) or []:
            name = pat.get("name", "")
            rel = os.path.join("wiki", "patterns", name)
            try:
                if not PATTERN_NAME_RE.match(name) or not os.path.exists(self._abs(rel)):
                    raise PatchError(f"unknown pattern {name!r}")
                content = self.pattern_page(name)
                self.write_file(rel, apply_edits(content, pat.get("edits", [])))
                report["updated"].append(name)
            except PatchError as e:
                report["errors"].append(f"{name}: {e}")
        if update.get("update_index") is not None:
            self.write_file("wiki/index.md", str(update["update_index"]))
        if update.get("append_log"):
            with open(self._abs("wiki/logs.md"), "a", encoding="utf-8") as f:
                f.write(update["append_log"].rstrip() + "\n")
        return report

    def record_skill_impact(self, entry: str) -> None:
        """Programmatic skill-impact.md append — done ONLY by the harness after gating."""
        with open(self._abs("wiki/skill-impact.md"), "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n")

