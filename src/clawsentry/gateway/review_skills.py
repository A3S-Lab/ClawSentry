"""YAML-backed review skills for Phase 5.2 L3 Agent."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import CanonicalEvent

logger = logging.getLogger("ahp.review-skills")


_VALID_SEVERITIES = {"low", "medium", "high", "critical"}


@dataclass(frozen=True)
class ReviewSkill:
    name: str
    description: str
    triggers: dict[str, list[str]]
    system_prompt: str
    evaluation_criteria: list[dict[str, str]]
    enabled: bool = True
    priority: int = 0


class SkillRegistry:
    """Load review skills from YAML files and select the best deterministic match."""

    def __init__(self, skills_dir: Path) -> None:
        self._skills: dict[str, ReviewSkill] = {}
        self._load_directory(skills_dir)
        if "general-review" not in self._skills:
            raise ValueError("general-review skill is required")

    @property
    def skills(self) -> dict[str, ReviewSkill]:
        return dict(self._skills)

    def _load_directory(self, skills_dir: Path) -> None:
        if not skills_dir.exists() or not skills_dir.is_dir():
            raise ValueError(f"skills_dir does not exist or is not a directory: {skills_dir}")
        for path in sorted(skills_dir.glob("*.yaml")):
            skill = self._load_skill(path)
            if skill.name in self._skills:
                raise ValueError(f"duplicate skill name: {skill.name}")
            self._skills[skill.name] = skill

    def load_additional(self, skills_dir: Path) -> int:
        """Load additional skills from an external directory. Returns count loaded."""
        count = 0
        for path in sorted(skills_dir.glob("*.yaml")):
            skill = self._load_skill(path)
            if skill.name in self._skills:
                logger.warning("Skipping duplicate skill: %s (from %s)", skill.name, path)
                continue
            self._skills[skill.name] = skill
            count += 1
        return count

    def _load_skill(self, path: Path) -> ReviewSkill:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return self._validate_skill(data, path)

    def _validate_skill(self, data: dict[str, Any], path: Path) -> ReviewSkill:
        name = str(data.get("name") or "").strip()
        description = str(data.get("description") or "").strip()
        system_prompt = str(data.get("system_prompt") or "").strip()
        triggers = data.get("triggers") or {}
        evaluation_criteria = data.get("evaluation_criteria") or []

        if not name:
            raise ValueError(f"skill missing name: {path}")
        if not description:
            raise ValueError(f"skill missing description: {path}")
        if not system_prompt:
            raise ValueError(f"skill missing system_prompt: {path}")
        if not isinstance(triggers, dict):
            raise ValueError(f"skill triggers must be a dict: {path}")
        if not isinstance(evaluation_criteria, list):
            raise ValueError(f"skill evaluation_criteria must be a list: {path}")

        normalized_triggers = {
            "risk_hints": [str(v).lower() for v in triggers.get("risk_hints", [])],
            "tool_names": [str(v).lower() for v in triggers.get("tool_names", [])],
            "payload_patterns": [str(v).lower() for v in triggers.get("payload_patterns", [])],
        }

        normalized_criteria: list[dict[str, str]] = []
        for idx, item in enumerate(evaluation_criteria):
            if not isinstance(item, dict):
                raise ValueError(f"skill evaluation_criteria[{idx}] must be a dict: {path}")
            crit_name = str(item.get("name") or "").strip()
            severity = str(item.get("severity") or "").strip().lower()
            description = str(item.get("description") or "").strip()
            if not crit_name or not description or severity not in _VALID_SEVERITIES:
                raise ValueError(f"invalid evaluation_criteria[{idx}] in {path}")
            normalized_criteria.append(
                {"name": crit_name, "severity": severity, "description": description}
            )

        enabled = data.get("enabled", True)
        if not isinstance(enabled, bool):
            enabled = True
        priority = data.get("priority", 0)
        if not isinstance(priority, int):
            priority = 0

        return ReviewSkill(
            name=name,
            description=description,
            triggers=normalized_triggers,
            system_prompt=system_prompt,
            evaluation_criteria=normalized_criteria,
            enabled=enabled,
            priority=priority,
        )

    def select_skill(self, event: CanonicalEvent, risk_hints: list[str]) -> ReviewSkill:
        event_tool = str(event.tool_name or "").lower()
        payload_text = str(event.payload or {}).lower()
        normalized_hints = {str(h).lower() for h in (risk_hints or [])}

        best_name = "general-review"
        best_score = -1
        best_priority = -1
        for name, skill in self._skills.items():
            if name == "general-review":
                continue
            if not skill.enabled:
                continue
            score = 0
            score += len(normalized_hints.intersection(skill.triggers.get("risk_hints", []))) * 10
            if event_tool and event_tool in skill.triggers.get("tool_names", []):
                score += 5
            score += sum(
                1 for pattern in skill.triggers.get("payload_patterns", [])
                if pattern and pattern in payload_text
            )
            if score > best_score or (score == best_score and skill.priority > best_priority):
                best_score = score
                best_priority = skill.priority
                best_name = name

        if best_score <= 0:
            return self._skills["general-review"]
        return self._skills[best_name]
