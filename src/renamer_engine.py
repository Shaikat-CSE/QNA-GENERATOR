from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .minimax_client import MiniMaxClient


@dataclass
class SubjectRule:
    subject: str
    code: str
    syllabus: str
    board: str = ""
    patterns: list[str] = None
    sample_names: list[str] = None
    confidence: float = 0.0

    def __post_init__(self):
        if self.patterns is None:
            self.patterns = []
        if self.sample_names is None:
            self.sample_names = []


@dataclass
class RenamingSuggestion:
    original_path: Path
    suggested_name: str
    confidence: float
    reason: str
    matched_rule: Optional[str] = None


class RuleGenerator:
    def __init__(self, minimax_client: MiniMaxClient):
        self.client = minimax_client

    def generate_rules_for_pdf(
        self, pdf_path: Path, subject: str, syllabus: str = "IGCSE"
    ) -> SubjectRule:
        text = self._extract_first_pages(pdf_path, pages=2)
        prompt = self._build_rule_prompt(text, subject, syllabus)
        max_tokens = 1000
        last_error = None
        for attempt in range(3):
            try:
                response = self.client.create_text(
                    system_prompt="You are a JSON generator. Respond ONLY with valid JSON.",
                    user_prompt=prompt,
                    max_tokens=max_tokens,
                )
                return self._parse_rule_response(response, subject, syllabus)
            except ValueError as e:
                if "truncated" in str(e):
                    last_error = e
                    max_tokens *= 2
                    continue
                raise
        raise ValueError(f"Max retries exceeded: {last_error}")

    def _extract_first_pages(self, pdf_path: Path, pages: int = 2) -> str:
        import pymupdf
        doc = pymupdf.open(pdf_path)
        text_parts = []
        for i in range(min(pages, len(doc))):
            text_parts.append(doc[i].get_text())
        doc.close()
        return "\n---\n".join(text_parts)

    def _build_rule_prompt(self, text: str, subject: str, syllabus: str) -> str:
        return f"""Extract exam naming rules from this PDF.

Syllabus: {syllabus} | Subject: {subject}

PDF text (first 2 pages, 1500 char limit):
{text[:1500]}

Target: {{year}}-{{session}}-{{level}}-{{subject}}-{{board}}-{{code}}-{{paper}}-{{variant}}-{{type}}.pdf

Examples:
- 2024-s-igcse-geography-cie-0460-4-3-qp.pdf
- 2018-jun-alevel-french-edexcel-9fr0-p2-n-qp.pdf

Return JSON only:
{{"code":"syllabus code","board":"cie/edexcel/aqa","patterns":["regex"],"sample_names":["example.pdf"],"confidence":0.0-1.0}}"""

    def _parse_rule_response(
        self, response: str, subject: str, syllabus: str
    ) -> SubjectRule:
        try:
            data = json.loads(response)
            return SubjectRule(
                subject=subject,
                code=data.get("code", "unknown"),
                board=data.get("board", ""),
                syllabus=syllabus,
                patterns=data.get("patterns", []),
                sample_names=data.get("sample_names", []),
                confidence=data.get("confidence", 0.0),
            )
        except json.JSONDecodeError:
            return SubjectRule(
                subject=subject,
                code="unknown",
                board="",
                syllabus=syllabus,
                patterns=[],
                sample_names=[],
                confidence=0.0,
            )


class PDFRenamer:
    def __init__(self, minimax_client: MiniMaxClient):
        self.client = minimax_client

    def suggest_rename(
        self, pdf_path: Path, rules: dict[str, SubjectRule]
    ) -> RenamingSuggestion:
        stem = pdf_path.stem

        if self._is_well_named(stem):
            return RenamingSuggestion(
                original_path=pdf_path,
                suggested_name=stem,
                confidence=1.0,
                reason="Already follows naming convention",
                matched_rule=None,
            )

        for code, rule in rules.items():
            for pattern in rule.patterns:
                try:
                    if re.search(pattern, stem, re.IGNORECASE):
                        return RenamingSuggestion(
                            original_path=pdf_path,
                            suggested_name=stem,
                            confidence=rule.confidence,
                            reason=f"Pattern matched for {code} - filename accepted",
                            matched_rule=code,
                        )
                except re.error:
                    continue

        text = self._extract_first_pages(pdf_path, pages=2)
        return self._llm_suggest(pdf_path, text)

    def _is_well_named(self, stem: str) -> bool:
        stem = re.sub(r"-\d+,\d+bytes$", "", stem, flags=re.IGNORECASE)
        stem = re.sub(r"\(to-be-fixed\)$", "", stem, flags=re.IGNORECASE)
        stem = re.sub(r"-\d+bytes$", "", stem, flags=re.IGNORECASE)

        # Detect syllabus from stem
        syllabus = self._detect_syllabus(stem)

        if syllabus == "ib":
            return self._is_well_named_ib(stem)
        else:
            return self._is_well_named_igcse(stem)

    def _detect_syllabus(self, stem: str) -> str:
        """Detect syllabus type from filename."""
        lower = stem.lower()
        if "-ib-" in lower or lower.startswith("ib-"):
            return "ib"
        elif "-igcse-" in lower:
            return "igcse"
        elif "-alevel-" in lower or "-a-level-" in lower:
            return "alevel"
        return "igcse"  # default

    def _is_well_named_ib(self, stem: str) -> bool:
        """Validate IB naming: year-session-ib-subject-level-code-paperN-tzN-type"""
        parts = stem.split("-")
        if len(parts) < 7:
            return False

        year = parts[0]
        if not re.match(r"^\d{4}$", year):
            return False

        # IB uses may/nov sessions
        if not any(s in stem.lower() for s in ["may", "nov", "m", "s", "w"]):
            return False

        # Must have ib marker
        if "ib" not in stem.lower():
            return False

        # Must have paper marker (paper1, paper2, paper3)
        if not re.search(r"paper\d+", stem.lower()):
            return False

        # Must have type (qp, ms, er, in, transcript)
        if not re.search(r"(qp|ms|er|in|transcript)$", stem.lower()):
            return False

        return True

    def _is_well_named_igcse(self, stem: str) -> bool:
        """Validate IGCSE/A-Level naming: year-session-level-subject-board-code-paper-variant-type"""
        parts = stem.split("-")
        if len(parts) == 8:
            year, session, level, subject, board, code, paper, type_ = parts
            variant = ""
        elif len(parts) == 9:
            year, session, level, subject, board, code, paper, variant, type_ = parts
        else:
            return False

        if not re.match(r"^\d{4}$", year):
            return False
        if not re.match(r"^(s|jun|nov|m|w|mar|may|feb)$", session, re.IGNORECASE):
            return False
        if not re.match(r"^(alevel|igcse|ib)$", level, re.IGNORECASE):
            return False
        if not re.match(r"^[a-z]+$", subject, re.IGNORECASE):
            return False
        if not re.match(r"^[a-z]+$", board, re.IGNORECASE):
            return False
        if not re.match(r"^[a-z0-9]+$", code, re.IGNORECASE):
            return False
        if not re.match(r"^(p?\d+|\d+p|paper\d+)$", paper, re.IGNORECASE):
            return False
        if variant and not re.match(r"^[a-z0-9]+$", variant, re.IGNORECASE):
            return False
        if not re.match(r"^(qp|ms|in|er|transcript)$", type_, re.IGNORECASE):
            return False
        return True

    def _build_name(self, stem: str, rule: SubjectRule, code: str) -> str:
        base = re.sub(r"[\(\)]", "", stem).strip()
        base = re.sub(r"\s+", "-", base)
        return f"{rule.subject}-{rule.syllabus}-{code}-{base}"

    def _llm_suggest(self, pdf_path: Path, text: str) -> RenamingSuggestion:
        try:
            prompt = self._build_suggestion_prompt(pdf_path.name, text)
            data = self.client.create_json(
                system_prompt="Extract exam metadata and return JSON only. No explanations.",
                user_prompt=prompt,
                max_tokens=200,
            )
            raw_name = data.get("suggested_name", pdf_path.name)
            normalized = self._normalize_name(raw_name)
            return RenamingSuggestion(
                original_path=pdf_path,
                suggested_name=normalized,
                confidence=data.get("confidence", 0.5),
                reason=data.get("reason", "LLM suggestion"),
            )
        except Exception as e:
            return RenamingSuggestion(
                original_path=pdf_path,
                suggested_name=pdf_path.stem.replace(".pdf", "").replace(".PDF", ""),
                confidence=0.0,
                reason=f"LLM failed: {str(e)[:100]}",
            )

    def _build_suggestion_prompt(self, filename: str, text: str) -> str:
        return f"""Example input:
Filename: old_exam.pdf
Content: A-level MATHEMATICS June 2023 Paper 1 Mark Scheme Edexcel 9MA0

Example output:
{{"suggested_name": "2023-jun-alevel-mathematics-edexcel-9ma0-1-n-ms.pdf", "confidence": 0.9, "reason": "Extracted from header"}}

Now process this:
Filename: {filename}
Content: {text[:800]}

Output:"""

    def _normalize_name(self, name: str) -> str:
        name = re.sub(r"[\(\)]", "", name)
        name = re.sub(r",\d+bytes", "", name)
        name = re.sub(r"\(to-be-fixed\)", "", name)
        name = re.sub(r"-(\d+)-\1-", r"-\1-", name)
        name = re.sub(r"\s+", "-", name.strip())
        name = re.sub(r"-+", "-", name)
        if name.lower().endswith(".pdf"):
            name = name[:-4]
        return name

    def _parse_suggestion(
        self, original_path: Path, response: str
    ) -> RenamingSuggestion:
        try:
            data = json.loads(response)
            raw_name = data.get("suggested_name", original_path.name)
            normalized = self._normalize_name(raw_name)
            return RenamingSuggestion(
                original_path=original_path,
                suggested_name=normalized,
                confidence=data.get("confidence", 0.5),
                reason=data.get("reason", "LLM suggestion"),
            )
        except json.JSONDecodeError:
            return RenamingSuggestion(
                original_path=original_path,
                suggested_name=original_path.name,
                confidence=0.0,
                reason="Parse failed",
            )

    def _extract_first_pages(self, pdf_path: Path, pages: int = 2) -> str:
        import pymupdf
        doc = pymupdf.open(pdf_path)
        text_parts = []
        for i in range(min(pages, len(doc))):
            text_parts.append(doc[i].get_text())
        doc.close()
        return "\n---\n".join(text_parts)
