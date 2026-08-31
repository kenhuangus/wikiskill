"""Skills Layer (paper §3.1): skills/<name>/SKILL.md + PURPOSE.md, with
snapshot/restore for skills-only rollback during validation gating (§3.2.4)."""
from __future__ import annotations

import difflib
import os
import re
from typing import Dict, List, Optional

from .workspace import PatchError, Workspace, apply_edits

SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class SkillsLayer:
    def __init__(self, ws: Workspace):
        self.ws = ws

    # ---------- state ----------
    def list_skills(self) -> List[str]:
        root = os.path.join(self.ws.root, "skills")
        if not os.path.isdir(root):
            return []
        return sorted(d for d in os.listdir(root)
                      if os.path.isfile(os.path.join(root, d, "SKILL.md")))

    def skill_content(self, name: str) -> Optional[str]:
        if name not in self.list_skills():
            return None
        return self.ws.read_file(os.path.join("skills", name, "SKILL.md"))

    def purpose(self, name: str) -> Optional[str]:
        if name not in self.list_skills():
            return None
        return self.ws.read_file(os.path.join("skills", name, "PURPOSE.md"))

    def active_skills_context(self) -> str:
        """Full SKILL.md contents injected into the Inference Agent prompt (§3.2.1)."""
        parts = []
        for name in self.list_skills():
            parts.append(f"## Skill: {name}\n\n{self.skill_content(name)}")
        return ("\n\n---\n\n".join(parts) if parts
                else "(No active skills.)")

    # ---------- proposals (§3.2.3: atomic, single-skill) ----------
    def apply_proposal(self, proposal: dict) -> dict:
        """Apply P_k: create a new skill or patch an existing SKILL.md."""
        action = proposal.get("action")
        name = str(proposal.get("skill", "")).strip()
        if not SKILL_NAME_RE.match(name):
            raise ValueError(f"invalid skill name: {name!r}")
        rel_skill = os.path.join("skills", name, "SKILL.md")
        rel_purpose = os.path.join("skills", name, "PURPOSE.md")
        purpose = str(proposal.get("purpose", "")).rstrip() + "\n"

        if action == "create":
            if self.skill_content(name) is not None:
                raise ValueError(f"skill already exists: {name}")
            self.ws.write_file(rel_skill, str(proposal.get("content", "")))
            self.ws.write_file(rel_purpose, purpose)
            return {"skill": name, "action": "create"}
        if action == "patch":
            old = self.skill_content(name)
            if old is None:
                raise ValueError(f"cannot patch missing skill: {name}")
            new = apply_edits(old, proposal.get("edits", []))
            self.ws.write_file(rel_skill, new)
            prev = self.purpose(name) or ""
            self.ws.write_file(rel_purpose,
                               prev.rstrip() + "\n" + purpose if prev.strip() else purpose)
            return {"skill": name, "action": "patch",
                    "diff": "\n".join(difflib.unified_diff(
                        old.splitlines(), new.splitlines(),
                        fromfile=f"{name}/SKILL.md (old)",
                        tofile=f"{name}/SKILL.md (new)", lineterm=""))}
        raise ValueError(f"unknown proposal action: {action!r}")

    # ---------- gating rollback (§3.2.4): skills only, wiki untouched ----------
    def snapshot(self) -> Dict[str, dict]:
        """Snapshot the active skill state (SKILL.md + PURPOSE.md) so a rejected
        proposal can be rolled back exactly to S_{k-1}. The wiki is never included."""
        return {
            name: {"SKILL.md": self.skill_content(name) or "",
                   "PURPOSE.md": self.purpose(name) or ""}
            for name in self.list_skills()
        }

    def restore(self, snap: Dict[str, dict]) -> None:
        for name in self.list_skills():
            if name not in snap:
                d = os.path.join(self.ws.root, "skills", name)
                for fn in os.listdir(d):
                    os.remove(os.path.join(d, fn))
                os.rmdir(d)
        for name, files in snap.items():
            self.ws.write_file(os.path.join("skills", name, "SKILL.md"),
                               files["SKILL.md"])
            self.ws.write_file(os.path.join("skills", name, "PURPOSE.md"),
                               files["PURPOSE.md"])
