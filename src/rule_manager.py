from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .renamer_engine import SubjectRule


class RuleManager:
    def __init__(self, rules_file: Optional[Path] = None):
        self.rules_file = rules_file or self._default_rules_file()
        self.rules: dict[str, SubjectRule] = {}
        self.load()

    def _default_rules_file(self) -> Path:
        import sys
        from pathlib import Path
        return Path(__file__).resolve().parent.parent / "config" / "subject_rules.json"

    def load(self) -> None:
        if not self.rules_file.exists():
            self.rules = {}
            return
        try:
            data = json.loads(self.rules_file.read_text(encoding="utf-8"))
            self.rules = {
                code.lower(): SubjectRule(
                    subject=rule.get("subject", "unknown"),
                    code=rule.get("code", code),
                    board=rule.get("board", ""),
                    syllabus=rule.get("syllabus", "IGCSE"),
                    patterns=rule.get("patterns", []),
                    sample_names=rule.get("sample_names", []),
                    confidence=rule.get("confidence", 0.0)
                )
                for code, rule in data.items()
            }
        except (json.JSONDecodeError, TypeError):
            self.rules = {}

    def save(self) -> None:
        data = {
            code: {
                "subject": rule.subject,
                "code": rule.code,
                "board": rule.board,
                "syllabus": rule.syllabus,
                "patterns": rule.patterns,
                "sample_names": rule.sample_names,
                "confidence": rule.confidence
            }
            for code, rule in self.rules.items()
        }
        self.rules_file.parent.mkdir(parents=True, exist_ok=True)
        self.rules_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def add_rule(self, rule: SubjectRule) -> None:
        self.rules[rule.code.lower()] = rule
        self.save()

    def get_rule(self, code: str) -> Optional[SubjectRule]:
        return self.rules.get(code.lower())

    def match_filename(self, filename: str) -> Optional[SubjectRule]:
        for code, rule in self.rules.items():
            for pattern in rule.patterns:
                try:
                    if re.search(pattern, filename, re.IGNORECASE):
                        return rule
                except re.error:
                    continue
        return None

    def export_rules(self) -> dict[str, dict]:
        return {
            code: {
                "subject": rule.subject,
                "code": rule.code,
                "board": rule.board,
                "syllabus": rule.syllabus,
                "patterns": rule.patterns,
                "sample_names": rule.sample_names,
                "confidence": rule.confidence
            }
            for code, rule in self.rules.items()
        }
