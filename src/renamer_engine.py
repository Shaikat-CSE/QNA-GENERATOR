from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:  # pragma: no cover - optional dependency
    RapidOCR = None

from .minimax_client import MiniMaxClient, extract_json_object


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


class PDFTextExtractor:
    def __init__(self) -> None:
        self._ocr_engine = None
        self._ocr_attempted = False

    def extract_first_pages(self, pdf_path: Path, pages: int = 2) -> str:
        import pymupdf

        try:
            doc = pymupdf.open(pdf_path)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Could not open PDF {pdf_path.name}: {exc}") from exc
        text_parts: list[str] = []
        try:
            for i in range(min(pages, len(doc))):
                page = doc[i]
                try:
                    page_text = page.get_text().strip()
                except Exception as exc:  # noqa: BLE001
                    page_text = ""
                    if i == 0:
                        raise ValueError(f"Could not read page text from {pdf_path.name}: {exc}") from exc
                if self._should_try_ocr(page_text):
                    page_text = self._merge_text_sources(
                        page_text,
                        self._ocr_page(page, pdf_path, i),
                    )
                text_parts.append(page_text)
        finally:
            doc.close()
        return "\n---\n".join(part for part in text_parts if part).strip()

    def _should_try_ocr(self, text: str) -> bool:
        normalized = re.sub(r"\s+", " ", text).strip()
        return len(normalized) < 80

    def _merge_text_sources(self, extracted_text: str, ocr_text: str) -> str:
        extracted = extracted_text.strip()
        ocr = ocr_text.strip()
        if extracted and ocr:
            if len(ocr) > len(extracted):
                return f"{extracted}\n{ocr}"
            return f"{ocr}\n{extracted}"
        return extracted or ocr

    def _get_ocr_engine(self):
        if self._ocr_attempted:
            return self._ocr_engine
        self._ocr_attempted = True
        if RapidOCR is None:
            return None
        try:
            self._ocr_engine = RapidOCR()
        except Exception:  # noqa: BLE001
            self._ocr_engine = None
        return self._ocr_engine

    def _ocr_page(self, page, pdf_path: Path, page_index: int) -> str:
        engine = self._get_ocr_engine()
        if engine is None:
            return ""

        import pymupdf

        temp_dir = Path(tempfile.gettempdir())
        temp_path = temp_dir / f"rename_ocr_{os.getpid()}_{pdf_path.stem}_{page_index + 1}.png"
        try:
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
            temp_path.write_bytes(pixmap.tobytes("png"))
            result = engine(str(temp_path))
        except Exception:  # noqa: BLE001
            return ""
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

        detections = result[0] if isinstance(result, tuple) and result else []
        lines: list[str] = []
        seen: set[str] = set()
        if isinstance(detections, list):
            for item in detections:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                text = re.sub(r"\s+", " ", str(item[1])).strip()
                try:
                    score = float(item[2]) if len(item) >= 3 else 0.0
                except (TypeError, ValueError):
                    score = 0.0
                if not text or score < 0.35:
                    continue
                key = text.lower()
                if key in seen:
                    continue
                seen.add(key)
                lines.append(text)
        return "\n".join(lines).strip()


class RuleGenerator:
    def __init__(self, minimax_client: MiniMaxClient):
        self.client = minimax_client
        self.extractor = PDFTextExtractor()

    def generate_rules_for_pdf(
        self, pdf_path: Path, subject: str, syllabus: str = "IGCSE"
    ) -> SubjectRule:
        text = self.extractor.extract_first_pages(pdf_path, pages=2)
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

    def _build_rule_prompt(self, text: str, subject: str, syllabus: str) -> str:
        return f"""Extract exam naming rules from this PDF.

PDF text (first 2 pages, 1500 char limit):
{text[:1500]}

Target: {{year}}-{{session}}-{{level}}-{{subject}}-{{board}}-{{code}}-{{paper}}-{{variant}}-{{type}}.pdf

Examples:
- 2024-s-igcse-geography-cie-0460-4-3-qp.pdf
- 2018-jun-alevel-french-edexcel-9fr0-p2-n-qp.pdf

Return JSON only with these fields:
- "subject": extracted subject name (e.g., "biology", "chemistry")
- "syllabus": syllabus level (e.g., "alevel", "igcse", "ib")
- "code": syllabus code (e.g., "9700", "0620")
- "board": exam board (e.g., "cie", "edexcel", "aqa")
- "patterns": list of regex patterns matching this subject's filenames
- "confidence": confidence score 0.0-1.0

Example response:
{{"subject":"biology","syllabus":"alevel","code":"9700","board":"cie","patterns":["9700_\\\\w+_\\\\w+_\\\\d+"],"confidence":0.95}}"""

    def _parse_rule_response(
        self, response: str, subject: str, syllabus: str
    ) -> SubjectRule:
        try:
            data = json.loads(response)
            extracted_subject = data.get("subject", "")
            extracted_syllabus = data.get("syllabus", "")
            return SubjectRule(
                subject=extracted_subject if extracted_subject else subject,
                code=data.get("code", "unknown"),
                board=data.get("board", ""),
                syllabus=extracted_syllabus if extracted_syllabus else syllabus,
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
        self.extractor = PDFTextExtractor()
        self._sibling_hint_cache: dict[str, dict[str, str]] = {}

    def needs_rename(self, pdf_path: Path) -> bool:
        stem = pdf_path.stem
        return not (self._is_well_named(stem) and not self._contains_placeholder_tokens(stem))

    def suggest_rename(
        self, pdf_path: Path, rules: dict[str, SubjectRule]
    ) -> RenamingSuggestion:
        stem = pdf_path.stem

        if self._is_well_named(stem) and not self._contains_placeholder_tokens(stem):
            return RenamingSuggestion(
                original_path=pdf_path,
                suggested_name=self._normalize_name(stem),
                confidence=1.0,
                reason="Already follows naming convention",
                matched_rule=None,
            )

        text = self.extractor.extract_first_pages(pdf_path, pages=2)
        llm_suggestion = self._llm_suggest(pdf_path, text)
        if (
            llm_suggestion.confidence >= 0.7
            and self._is_well_named(llm_suggestion.suggested_name)
            and not self._contains_placeholder_tokens(llm_suggestion.suggested_name)
        ):
            llm_suggestion.reason = f"LLM primary: {llm_suggestion.reason}"
            stabilized = self._stabilize_suggested_name(stem, llm_suggestion.suggested_name)
            llm_suggestion.suggested_name = stabilized
            return llm_suggestion

        for code, rule in rules.items():
            for pattern in rule.patterns:
                try:
                    if self._is_valid_regex_pattern(pattern) and re.search(pattern, stem, re.IGNORECASE):
                        normalized = self._normalize_name(stem)
                        confidence = rule.confidence if self._is_well_named(normalized) else 0.4
                        return RenamingSuggestion(
                            original_path=pdf_path,
                            suggested_name=normalized,
                            confidence=confidence,
                            reason=f"Pattern matched for {code}",
                            matched_rule=code,
                        )
                except re.error:
                    continue

        llm_suggestion.reason = f"LLM low confidence fallback: {llm_suggestion.reason}"
        return llm_suggestion

    def force_suggest_rename(
        self, pdf_path: Path, rules: dict[str, SubjectRule]
    ) -> RenamingSuggestion:
        suggestion = self.suggest_rename(pdf_path, rules)
        if suggestion.confidence > 0.7 and not self._should_reinspect_forced(pdf_path, suggestion):
            return suggestion
        text = self.extractor.extract_first_pages(pdf_path, pages=2)
        forced = self._force_best_effort_suggestion(pdf_path, text, suggestion)
        return forced or suggestion

    def _should_reinspect_forced(
        self,
        pdf_path: Path,
        suggestion: RenamingSuggestion,
    ) -> bool:
        stem = self._normalize_name(pdf_path.stem)
        code = self._first_nonempty(
            self._code_from_stem(stem),
            self._compound_code_from_stem(stem),
        )
        year = self._year_from_stem(stem)
        if self._validated_year(year, code):
            return False
        return suggestion.reason == "Already follows naming convention"

    def _contains_placeholder_tokens(self, stem: str) -> bool:
        lowered = self._normalize_name(stem)
        tokens = set(lowered.split("-"))
        return bool(tokens & {"unknown", "unk", "na", "n-a"})

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
        return "unknown"

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
        normalized = self._normalize_name(stem)
        return bool(
            re.match(
                r"^\d{4}-(s|jun|nov|m|w|mar|may|feb|jan|oct|spec)-"
                r"(alevel|a-level|aslevel|as-level|igcse|ib)-"
                r"[a-z0-9]+(?:-[a-z0-9]+)*-"
                r"(cie|edexcel|aqa|ocr|cambridge|ib)-"
                r"[a-z0-9]+-"
                r"(p?\d+|paper\d+)(?:-[a-z0-9]+)?-"
                r"(?:dup\d+-)?"
                r"(qp|ms|in|er|transcript|sqp|sm|sp|prm|pm|te|gt)$",
                normalized,
                re.IGNORECASE,
            )
        )

    def _build_name(self, stem: str, rule: SubjectRule, code: str) -> str:
        base = re.sub(r"[\(\)]", "", stem).strip()
        base = re.sub(r"\s+", "-", base)
        return f"{rule.subject}-{rule.syllabus}-{code}-{base}"

    def _llm_suggest(self, pdf_path: Path, text: str) -> RenamingSuggestion:
        prompt = self._build_suggestion_prompt(pdf_path, text)
        try:
            data = self.client.create_json(
                system_prompt="Extract exam metadata and return exactly one JSON object. No commentary.",
                user_prompt=prompt,
                max_tokens=500,
            )
        except Exception:
            try:
                response = self.client.create_text(
                    system_prompt="Extract exam metadata and return exactly one JSON object. No commentary.",
                    user_prompt=prompt,
                    max_tokens=500,
                )
                data = extract_json_object(response)
            except Exception as e:
                fallback = self._canonicalize_from_metadata(pdf_path, text, {})
                return RenamingSuggestion(
                    original_path=pdf_path,
                    suggested_name=fallback or pdf_path.stem.replace(".pdf", "").replace(".PDF", ""),
                    confidence=0.35 if fallback else 0.0,
                    reason=f"Heuristic fallback after LLM failure: {str(e)[:100]}",
                )

        normalized = self._canonicalize_from_metadata(pdf_path, text, data)
        if not normalized:
            fallback = self._canonicalize_from_metadata(pdf_path, text, {})
            return RenamingSuggestion(
                original_path=pdf_path,
                suggested_name=fallback or pdf_path.stem.replace(".pdf", "").replace(".PDF", ""),
                confidence=0.45 if fallback else 0.0,
                reason=f"Heuristic fallback after incomplete metadata: {str(data)[:100]}",
            )

        return RenamingSuggestion(
            original_path=pdf_path,
            suggested_name=normalized,
            confidence=self._normalize_confidence(data.get("confidence")),
            reason=str(data.get("reason", "LLM suggestion")),
        )

    def _build_suggestion_prompt(self, pdf_path: Path, text: str) -> str:
        context = self._path_context(pdf_path)
        return f"""You are extracting structured metadata for an exam PDF filename.

Return exactly one JSON object with these fields:
- year
- session
- level
- subject
- board
- code
- paper
- variant
- type
- confidence
- reason

Rules:
- Use lowercase short values where practical.
- session should be one of: jan, feb, mar, may, jun, jul, aug, oct, nov, dec, spec
- level should be one of: alevel, igcse, ib
- board should be one of: cie, cambridge, edexcel, aqa, ocr, ib
        - type should be one of: qp, ms, er, in, transcript, sqp, sm, sp, prm, pm, te, gt
- If a field is unknown, return an empty string instead of commentary.
- Do not return a full filename. Return fields only.

Path context:
- filename: {pdf_path.name}
- inferred_level: {context.get("level", "")}
- inferred_subject: {context.get("subject", "")}
- inferred_board: {context.get("board", "")}
- inferred_code: {context.get("code", "")}

PDF content (first 2 pages, truncated):
{text[:2200]}"""

    def _normalize_name(self, name: str) -> str:
        if name.lower().endswith(".pdf"):
            name = name[:-4]
        name = name.strip()
        name = re.sub(r",\d+bytes", "", name, flags=re.IGNORECASE)
        name = re.sub(r"\(to-be-fixed\)", "", name, flags=re.IGNORECASE)
        name = re.sub(r"\((\d+)\)$", r"-dup\1", name)
        name = re.sub(r"\ba-level\b", "alevel", name, flags=re.IGNORECASE)
        name = re.sub(r"\bas-level\b", "aslevel", name, flags=re.IGNORECASE)
        name = re.sub(r"\bspecimen\b", "spec", name, flags=re.IGNORECASE)
        name = re.sub(r"[\(\)]", "", name)
        name = re.sub(r"[_\s]+", "-", name)
        name = re.sub(r"-+", "-", name)
        name = name.lower().strip("-")
        kind_group = r"(qp|ms|in|er|transcript|sqp|sm|sp|prm|pm|te|gt)"
        name = re.sub(rf"-(p)(\d+)-", r"-\2-", name)
        name = re.sub(rf"^(?P<prefix>.+)-(?P<kind>{kind_group})-(?P<hash>[a-f0-9]{{8,}})(?:-(?P<dup>\d+))?$", self._rewrite_artifact_suffix, name)
        name = re.sub(rf"^(?P<prefix>.+)-(?P<kind>{kind_group})-dup(?P<dup>\d+)$", r"\g<prefix>-dup\g<dup>-\g<kind>", name)
        name = re.sub(rf"^(?P<prefix>.+)-(?P<kind>{kind_group})-(?P<dup>\d+)$", self._rewrite_numeric_artifact_suffix, name)
        name = re.sub(rf"^(?P<prefix>.+)-(?P<kind>{kind_group})-duplicate$", r"\g<prefix>-dup1-\g<kind>", name)
        name = re.sub(rf"^(?P<prefix>.+)-(?P<kind>{kind_group})-alt$", r"\g<prefix>-\g<kind>", name)
        name = re.sub(r"-(pre)$", r"-prm", name)
        name = re.sub(r"-([a-z0-9]{3,})-\1-", r"-\1-", name)
        name = re.sub(rf"-(?P<kind>{kind_group})-(?P=kind)$", r"-\g<kind>", name)
        name = re.sub(r"-(\d)(\d)-(qp|ms|in|er|transcript|sqp|sm|sp|prm|pm|te|gt)$", r"-\1-\2-\3", name)
        return name

    def _rewrite_artifact_suffix(self, match: re.Match[str]) -> str:
        dup_index = match.group("dup") or "1"
        return f"{match.group('prefix')}-dup{dup_index}-{match.group('kind')}"

    def _rewrite_numeric_artifact_suffix(self, match: re.Match[str]) -> str:
        return f"{match.group('prefix')}-dup{match.group('dup')}-{match.group('kind')}"

    def _is_valid_regex_pattern(self, pattern: str) -> bool:
        if not pattern or "{" in pattern or "}" in pattern:
            return False
        try:
            re.compile(pattern)
        except re.error:
            return False
        return True

    def build_duplicate_name(self, suggested_name: str, duplicate_index: int) -> str:
        normalized = self._normalize_name(suggested_name)
        match = re.search(
            r"^(?P<prefix>.+)-(?P<kind>qp|ms|in|er|transcript|sqp|sm|sp|prm|pm|te|gt)$",
            normalized,
            re.IGNORECASE,
        )
        if not match:
            return f"{normalized}-dup{duplicate_index}"
        return f"{match.group('prefix')}-dup{duplicate_index}-{match.group('kind').lower()}"

    def _stabilize_suggested_name(self, original_stem: str, suggested_name: str) -> str:
        original = self._normalize_name(original_stem)
        suggested = suggested_name

        original_board = self._extract_board_token(original)
        suggested_board = self._extract_board_token(suggested)
        if original_board and suggested_board and original_board != suggested_board:
            suggested = re.sub(
                rf"(?<=-){re.escape(suggested_board)}(?=-)",
                original_board,
                suggested,
                count=1,
            )

        raw_original = re.sub(r"[\(\)\s]+", "-", original_stem.strip().lower())
        raw_original = re.sub(r"-+", "-", raw_original)
        compact_match = re.search(
            r"-(\d)(\d)-(qp|ms|in|er|transcript|sqp|sm|sp|prm|pm|te|gt)$",
            raw_original,
            re.IGNORECASE,
        )
        if compact_match:
            paper_num, variant, type_ = compact_match.groups()
            missing_variant_pattern = rf"-(p?{paper_num})-{type_.lower()}$"
            if re.search(missing_variant_pattern, suggested, re.IGNORECASE):
                suggested = re.sub(
                    missing_variant_pattern,
                    f"-{paper_num}-{variant}-{type_.lower()}",
                    suggested,
                    flags=re.IGNORECASE,
                )

        return suggested

    def _extract_board_token(self, stem: str) -> str | None:
        match = re.search(r"-(cie|cambridge|edexcel|aqa|ocr|ib)-", stem, re.IGNORECASE)
        if match:
            return match.group(1).lower()
        return None

    def _force_best_effort_suggestion(
        self,
        pdf_path: Path,
        text: str,
        prior_suggestion: RenamingSuggestion | None = None,
    ) -> RenamingSuggestion | None:
        forced_name = self._force_best_effort_name(pdf_path, text, prior_suggestion)
        if not forced_name:
            return None
        return RenamingSuggestion(
            original_path=pdf_path,
            suggested_name=forced_name,
            confidence=0.71,
            reason="Forced best-effort canonicalization from folder context, filename, OCR/text hints, and nearest subject paper structure",
            matched_rule="forced-fallback",
        )

    def _force_best_effort_name(
        self,
        pdf_path: Path,
        text: str,
        prior_suggestion: RenamingSuggestion | None = None,
    ) -> str | None:
        practice_candidate = self.practice_suggest_rename(pdf_path, text)
        if practice_candidate:
            return practice_candidate

        context = self._path_context(pdf_path)
        stem_hint = self._normalize_name(pdf_path.stem)
        text_hint = self._text_hints(text)
        sibling_hint = self._sibling_text_hints(pdf_path)
        prior = self._normalize_name(prior_suggestion.suggested_name) if prior_suggestion else ""
        context_code = self._first_nonempty(
            self._code_from_stem(stem_hint),
            context.get("code"),
            sibling_hint.get("code"),
            self._code_from_stem(prior),
            text_hint.get("code"),
            self._compound_code_from_stem(stem_hint),
        )

        year = self._first_nonempty(
            self._validated_year(self._year_from_stem(stem_hint), context_code),
            self._validated_year(self._year_from_loose_stem(stem_hint), context_code),
            self._validated_year(self._year_from_stem(prior), context_code),
            self._validated_year(self._year_from_loose_stem(prior), context_code),
            self._validated_year(text_hint.get("year", ""), context_code),
            self._validated_year(sibling_hint.get("year", ""), context_code),
        )
        session = self._first_nonempty(
            self._session_from_stem(stem_hint),
            self._session_from_loose_stem(stem_hint),
            self._session_from_stem(prior),
            text_hint.get("session"),
            sibling_hint.get("session"),
        )
        level = self._first_nonempty(
            self._level_from_stem(stem_hint),
            context.get("level"),
            self._level_from_stem(prior),
        )
        subject = self._first_nonempty(
            context.get("subject"),
            self._subject_from_folder(pdf_path),
            self._subject_from_stem(prior),
        )
        board = self._first_nonempty(
            self._board_from_stem(stem_hint),
            context.get("board"),
            self._board_from_stem(prior),
            self._board_from_text(text),
        )
        if not session and board == "edexcel" and year:
            session = "jun"
        code = self._first_nonempty(
            self._code_from_stem(stem_hint),
            context.get("code"),
            self._code_from_stem(prior),
            text_hint.get("code"),
            sibling_hint.get("code"),
            self._compound_code_from_stem(stem_hint),
        )
        type_ = self._first_nonempty(
            self._type_from_stem(stem_hint),
            self._type_from_loose_stem(stem_hint),
            self._type_from_stem(prior),
            text_hint.get("type"),
            sibling_hint.get("type"),
        )

        paper, variant = self._resolve_paper_variant(
            None,
            None,
            text_hint.get("paper"),
            text_hint.get("variant"),
            stem_hint,
        )
        if not paper or not variant:
            sibling_paper, sibling_variant = self._resolve_paper_variant(
                None,
                None,
                sibling_hint.get("paper"),
                sibling_hint.get("variant"),
                stem_hint,
            )
            paper = paper or sibling_paper
            variant = variant or sibling_variant
        if not paper:
            paper = self._paper_from_compound_code(stem_hint)
        if not variant and prior:
            _, prior_variant = self._resolve_paper_variant(None, None, None, None, prior)
            variant = prior_variant

        required = [year, session, level, subject, board, code, paper, type_]
        if not year and session == "spec":
            year = self._specimen_fallback_year(code)
            required = [year, session, level, subject, board, code, paper, type_]
        if any(not value for value in required):
            return None

        parts = [year, session, level, subject, board, code, paper]
        if variant:
            parts.append(variant)
        parts.append(type_)
        candidate = self._normalize_name("-".join(parts))
        if self._contains_placeholder_tokens(candidate):
            return None
        return candidate if self._is_well_named(candidate) else None

    def _canonicalize_from_metadata(self, pdf_path: Path, text: str, data: dict[str, Any]) -> str | None:
        context = self._path_context(pdf_path)
        stem_hint = self._normalize_name(pdf_path.stem)
        text_hint = self._text_hints(text)
        sibling_hint = self._sibling_text_hints(pdf_path)
        context_code = self._first_nonempty(
            self._code_from_stem(stem_hint),
            context.get("code"),
            self._normalize_code(str(data.get("code", ""))),
            text_hint.get("code"),
            sibling_hint.get("code"),
        )

        year = self._first_nonempty(
            self._validated_year(self._year_from_stem(stem_hint), context_code),
            self._validated_year(self._year_from_loose_stem(stem_hint), context_code),
            self._validated_year(self._normalize_year(data.get("year")), context_code),
            self._validated_year(text_hint.get("year", ""), context_code),
            self._validated_year(sibling_hint.get("year", ""), context_code),
        )
        session = self._first_nonempty(
            self._session_from_stem(stem_hint),
            self._normalize_session(str(data.get("session", ""))),
            text_hint.get("session"),
            sibling_hint.get("session"),
        )
        level = self._first_nonempty(
            self._level_from_stem(stem_hint),
            context.get("level"),
            self._normalize_level(str(data.get("level", ""))),
        )
        subject = self._first_nonempty(
            self._slugify_subject(str(data.get("subject", ""))),
            context.get("subject"),
        )
        board = self._first_nonempty(
            self._board_from_stem(stem_hint),
            context.get("board"),
            self._normalize_board(str(data.get("board", ""))),
        )
        if not session and board == "edexcel" and year:
            session = "jun"
        code = self._first_nonempty(
            self._code_from_stem(stem_hint),
            context.get("code"),
            self._normalize_code(str(data.get("code", ""))),
            text_hint.get("code"),
            sibling_hint.get("code"),
        )
        type_ = self._first_nonempty(
            self._type_from_stem(stem_hint),
            self._normalize_type(str(data.get("type", ""))),
            text_hint.get("type"),
            sibling_hint.get("type"),
        )

        paper, variant = self._resolve_paper_variant(
            data.get("paper"),
            data.get("variant"),
            text_hint.get("paper"),
            text_hint.get("variant"),
            stem_hint,
        )
        if not paper or not variant:
            sibling_paper, sibling_variant = self._resolve_paper_variant(
                None,
                None,
                sibling_hint.get("paper"),
                sibling_hint.get("variant"),
                stem_hint,
            )
            paper = paper or sibling_paper
            variant = variant or sibling_variant

        required = [year, session, level, subject, board, code, paper, type_]
        if not year and session == "spec":
            year = self._specimen_fallback_year(code)
            required = [year, session, level, subject, board, code, paper, type_]
        if any(not item for item in required):
            return None

        parts = [year, session, level, subject, board, code, paper]
        if variant:
            parts.append(variant)
        parts.append(type_)
        candidate = self._normalize_name("-".join(parts))
        if self._contains_placeholder_tokens(candidate):
            return None
        return candidate if self._is_well_named(candidate) else None

    def _first_nonempty(self, *values: str | None) -> str:
        for value in values:
            if value:
                return value
        return ""

    def _normalize_year(self, value: Any) -> str:
        text = str(value or "").strip()
        return text if re.fullmatch(r"(19|20)\d{2}", text) else ""

    def _specimen_fallback_year(self, exam_code: str) -> str:
        minimum = self._validated_year(str({
            "9618": 2021,
        }.get(exam_code, "")), exam_code)
        if minimum:
            return minimum
        if re.fullmatch(r"7\d{3}", exam_code) or re.fullmatch(r"9[a-z0-9]{3}", exam_code):
            return str(2014)
        return str(2000) if exam_code else ""

    def _validated_year(self, year: str, exam_code: str | None = None) -> str:
        if not year or not re.fullmatch(r"(19|20)\d{2}", year):
            return ""
        year_value = int(year)
        max_year = dt.date.today().year - 1
        if year_value > max_year:
            return ""
        minimum = 2000
        if exam_code == "9618":
            minimum = 2021
        elif exam_code and re.fullmatch(r"7\d{3}", exam_code):
            minimum = 2014
        elif exam_code and re.fullmatch(r"9[a-z0-9]{3}", exam_code):
            minimum = 2014
        if year_value < minimum:
            return ""
        return year

    def _year_from_loose_stem(self, stem: str) -> str:
        patterns = [
            re.search(r"(jan|feb|mar|apr|may|jun|june|jul|aug|sep|sept|oct|nov|dec)[-_]?(\d{2,4})", stem, re.IGNORECASE),
            re.search(r"(\d{2,4})[-_]?(jan|feb|mar|apr|may|jun|june|jul|aug|sep|sept|oct|nov|dec)", stem, re.IGNORECASE),
            re.search(r"\by(\d{2})\b", stem, re.IGNORECASE),
        ]
        for match in patterns:
            if not match:
                continue
            for group in match.groups():
                token = str(group)
                if token.isdigit():
                    return self._expand_short_year(token)
        return ""

    def _expand_short_year(self, token: str) -> str:
        if re.fullmatch(r"\d{4}", token):
            return token
        if re.fullmatch(r"\d{2}", token):
            return f"20{int(token):02d}"
        return ""

    def _normalize_session(self, value: str) -> str:
        text = value.strip().lower()
        mapping = {
            "june": "jun",
            "jun": "jun",
            "summer": "jun",
            "s": "s",
            "november": "nov",
            "nov": "nov",
            "winter": "nov",
            "w": "w",
            "march": "mar",
            "mar": "mar",
            "m": "m",
            "may": "may",
            "october": "oct",
            "oct": "oct",
            "specimen": "spec",
            "spec": "spec",
        }
        return mapping.get(text, "")

    def _session_from_loose_stem(self, stem: str) -> str:
        lowered = stem.lower().replace("_", "-")
        for token in re.split(r"[-]+", lowered):
            normalized = self._normalize_session(token)
            if normalized:
                return normalized
            compact_match = re.fullmatch(r"(jan|feb|mar|apr|may|jun|june|jul|aug|sep|sept|oct|nov|dec)(\d{2,4})", token)
            if compact_match:
                compact = compact_match.group(1)
                normalized = self._normalize_session(compact)
                if normalized:
                    return normalized
        return ""

    def _normalize_level(self, value: str) -> str:
        text = value.strip().lower().replace("-", "")
        text = text.replace(" ", "")
        mapping = {
            "alevel": "alevel",
            "aslevel": "alevel",
            "igcse": "igcse",
            "ib": "ib",
        }
        return mapping.get(text, "")

    def _normalize_board(self, value: str) -> str:
        text = value.strip().lower()
        mapping = {
            "cie": "cie",
            "cambridge": "cie",
            "ucles": "cie",
            "aqa": "aqa",
            "edexcel": "edexcel",
            "pearson": "edexcel",
            "ocr": "ocr",
            "ib": "ib",
        }
        return mapping.get(text, "")

    def _normalize_code(self, value: str) -> str:
        text = value.strip()
        return text.lower() if re.fullmatch(r"[a-z0-9]{3,6}", text, re.IGNORECASE) else ""

    def _normalize_type(self, value: str) -> str:
        text = value.strip().lower()
        allowed = {"qp", "ms", "er", "in", "transcript", "sqp", "sm", "sp", "prm", "pm", "te", "gt"}
        return text if text in allowed else ""

    def _type_from_loose_stem(self, stem: str) -> str:
        lowered = stem.lower()
        if "question-paper" in lowered or "questionpaper" in lowered or "-qp" in lowered:
            return "qp"
        if lowered.endswith("-qs") or "-qs-" in lowered:
            return "sqp"
        if "specimen-mark-scheme" in lowered or "specimen_mark_scheme" in lowered or "-sms" in lowered:
            return "sm"
        if lowered.endswith("-rms") or "-rms-" in lowered:
            return "ms"
        if "mark-scheme" in lowered or "markscheme" in lowered or "-ms" in lowered:
            return "ms"
        if "examiner-report" in lowered or "examiner_report" in lowered or "-wre" in lowered:
            return "er"
        if "listening-transcript" in lowered or "-tr" in lowered:
            return "transcript"
        if "teacher-notes" in lowered or "teachers-notes" in lowered or "-tn" in lowered:
            return "te"
        if "insert" in lowered or "-ins" in lowered or lowered.endswith("-si") or "-si-" in lowered:
            return "in"
        if "pre-release-material" in lowered or "pre_release_material" in lowered or "-pre" in lowered:
            return "prm"
        if "booklet" in lowered:
            return "in"
        if "transcript" in lowered:
            return "transcript"
        if lowered.endswith("-te") or "-te-" in lowered:
            return "te"
        return ""

    def _normalize_confidence(self, value: Any) -> float:
        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))
        text = str(value or "").strip().lower()
        if not text:
            return 0.5
        if text in {"high", "strong"}:
            return 0.9
        if text in {"medium", "moderate"}:
            return 0.7
        if text in {"low", "weak"}:
            return 0.3
        try:
            return max(0.0, min(1.0, float(text)))
        except ValueError:
            return 0.5

    def _slugify_subject(self, value: str) -> str:
        text = value.strip().lower()
        if not text:
            return ""
        text = re.sub(r"\([^)]*\)", "", text)
        text = re.sub(r"\b(aqa|cie|cambridge|edexcel|ocr|ib)\b", "", text)
        text = re.sub(r"[^a-z0-9]+", "-", text)
        return re.sub(r"-+", "-", text).strip("-")

    def _subject_from_folder(self, pdf_path: Path) -> str:
        for parent in pdf_path.parents:
            match = re.match(r"(?P<board>AQA|Cie|Edexcel|OCR|IB)\s+(?P<subject>.+?)\s+\((?P<code>[^)]+)\)$", parent.name, re.IGNORECASE)
            if match:
                return self._slugify_subject(match.group("subject"))
        return ""

    def _subject_from_stem(self, stem: str) -> str:
        parts = stem.split("-")
        board_indexes = [i for i, token in enumerate(parts) if token in {"cie", "cambridge", "edexcel", "aqa", "ocr", "ib"}]
        if not board_indexes:
            return ""
        board_index = board_indexes[0]
        start = 2
        if len(parts) > 2 and parts[2] in {"alevel", "a-level", "aslevel", "as-level", "igcse", "ib"}:
            start = 3
        subject = "-".join(parts[start:board_index]).strip("-")
        return self._slugify_subject(subject)

    def _path_context(self, pdf_path: Path) -> dict[str, str]:
        result = {"level": "", "subject": "", "board": "", "code": ""}
        for parent in pdf_path.parents:
            name = parent.name
            lowered = name.lower()
            if lowered in {"a-level", "igcse", "ib"}:
                result["level"] = "alevel" if lowered == "a-level" else lowered
            match = re.match(r"(?P<board>AQA|Cie|Edexcel|OCR|IB)\s+(?P<subject>.+?)\s+\((?P<code>[^)]+)\)$", name, re.IGNORECASE)
            if match:
                result["board"] = self._normalize_board(match.group("board"))
                result["subject"] = self._slugify_subject(match.group("subject"))
                result["code"] = self._normalize_code(match.group("code"))
        return result

    def _board_from_text(self, text: str) -> str:
        lowered = text.lower()
        if "cambridge international" in lowered or "cambridge university press" in lowered:
            return "cie"
        if "aqa" in lowered:
            return "aqa"
        if "edexcel" in lowered or "pearson" in lowered:
            return "edexcel"
        if "ocr" in lowered:
            return "ocr"
        if "international baccalaureate" in lowered or "\nib\n" in lowered:
            return "ib"
        return ""

    def _text_hints(self, text: str) -> dict[str, str]:
        hints: dict[str, str] = {}
        lowered = text.lower()
        normalized_ws = re.sub(r"\s+", " ", lowered)
        if "specimen paper" in lowered or "for examination from" in lowered or " specimen " in f" {normalized_ws} ":
            hints["session"] = "spec"
        elif "summer" in lowered:
            hints["session"] = "jun"
        elif "winter" in lowered:
            hints["session"] = "nov"
        elif re.search(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)?\s*\d{1,2}\s+may\s+(?:20\d{2}|19\d{2})\b", lowered):
            hints["session"] = "jun"
        elif "may/june" in lowered or " june " in f" {normalized_ws} ":
            hints["session"] = "jun"
        elif re.search(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)?\s*\d{1,2}\s+(?:june|july)\s+(?:20\d{2}|19\d{2})\b", lowered):
            hints["session"] = "jun"
        elif "october/november" in lowered or " november " in f" {normalized_ws} ":
            hints["session"] = "nov"
        elif re.search(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)?\s*\d{1,2}\s+(?:october|november)\s+(?:20\d{2}|19\d{2})\b", lowered):
            hints["session"] = "nov"
        elif "february/march" in lowered or " march " in f" {normalized_ws} ":
            hints["session"] = "mar"
        elif re.search(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)?\s*\d{1,2}\s+(?:january|february|march|april)\s+(?:20\d{2}|19\d{2})\b", lowered):
            hints["session"] = "mar"

        if not hints.get("session"):
            compact_session_match = re.search(r"\b(jan|feb|mar|apr|may|jun|june|jul|aug|sep|sept|oct|nov|dec)(\d{2})\b", lowered)
            if compact_session_match:
                session_token = compact_session_match.group(1)
                compact_map = {
                    "jan": "mar",
                    "feb": "mar",
                    "mar": "mar",
                    "apr": "mar",
                    "may": "jun",
                    "jun": "jun",
                    "june": "jun",
                    "jul": "jun",
                    "aug": "jun",
                    "sep": "nov",
                    "sept": "nov",
                    "oct": "nov",
                    "nov": "nov",
                    "dec": "nov",
                }
                mapped = compact_map.get(session_token)
                if mapped:
                    hints["session"] = mapped

        if "mark scheme" in lowered or "markscheme" in lowered:
            hints["type"] = "ms"
        elif re.search(r"\brms\b", lowered):
            hints["type"] = "ms"
        elif "examiner report" in lowered:
            hints["type"] = "er"
        elif "report on the examination" in lowered:
            hints["type"] = "er"
        elif "listening transcript" in lowered:
            hints["type"] = "transcript"
        elif (
            "teacher examiner" in lowered
            or "teachers notes" in lowered
            or "teacher notes" in lowered
            or "examiners material" in lowered
        ):
            hints["type"] = "te"
        elif "pre-release material" in lowered or "pre release material" in lowered:
            hints["type"] = "prm"
        elif "insert" in lowered or "data booklet" in lowered or "resource booklet" in lowered or "source booklet" in lowered:
            hints["type"] = "in"
        elif "booklet" in lowered:
            hints["type"] = "in"
        elif "question paper" in lowered:
            hints["type"] = "qp"

        paper_match = re.search(r"\bPaper\s+(\d{1,2})\b", text, re.IGNORECASE)
        explicit_paper = ""
        if paper_match:
            explicit_paper = paper_match.group(1).lstrip("0") or "0"
            hints["paper"] = explicit_paper
        aqa_paper_variant_match = re.search(r"\bPaper\s+(\d{1,2})([A-Z])\b", text, re.IGNORECASE)
        if aqa_paper_variant_match:
            hints["paper"] = aqa_paper_variant_match.group(1).lstrip("0") or "0"
            hints["variant"] = aqa_paper_variant_match.group(2).lower()

        publication_match = re.search(
            r"\b([A-Z0-9]{4,5})[_/](\d{1,2}[A-Z]?)_(\d{2})(\d{2})_(QP|MS|ER|IN|TRANSCRIPT)\b",
            text,
            re.IGNORECASE,
        )
        if publication_match:
            hints["code"] = self._normalize_code(publication_match.group(1))
            paper_variant = publication_match.group(2).lower()
            paper_hint, variant_hint = self._split_component_hint(
                paper_variant,
                explicit_paper=explicit_paper,
                type_hint=hints.get("type", ""),
            )
            if paper_hint:
                hints["paper"] = paper_hint
            if variant_hint:
                hints["variant"] = variant_hint
            hints["year"] = self._expand_short_year(publication_match.group(3))
            session = self._session_from_month_number(publication_match.group(4))
            if session:
                hints["session"] = session
            hints["type"] = self._normalize_type(publication_match.group(5))

        year_match = self._exam_year_from_text(text)
        if year_match:
            hints.setdefault("year", year_match)

        code_variant_match = re.search(r"\b([A-Z0-9]{4,5})/(\d{1,2}[A-Z0-9/+]*)\b", text)
        if code_variant_match:
            hints["code"] = self._normalize_code(code_variant_match.group(1))
            paper_variant = code_variant_match.group(2).lower()
            paper_hint, variant_hint = self._split_component_hint(
                paper_variant,
                explicit_paper=explicit_paper,
                type_hint=hints.get("type", ""),
            )
            if paper_hint:
                hints["paper"] = paper_hint
            if variant_hint:
                hints["variant"] = variant_hint
        return hints

    def practice_suggest_rename(self, pdf_path: Path, text: str) -> str | None:
        lowered = self._normalize_name(pdf_path.stem)
        normalized_text = re.sub(r"\s+", " ", text.lower())
        if (
            "practice" not in lowered
            and "practice paper" not in normalized_text
            and not re.match(r"^\d+-(?:19|20)\d{2}-paper-\d+", lowered)
        ):
            return None
        context = self._path_context(pdf_path)
        if not context.get("subject") or not context.get("board") or not context.get("code"):
            return None
        year = self._first_nonempty(
            self._validated_year(self._year_from_stem(lowered), context.get("code")),
            self._validated_year(self._exam_year_from_text(text), context.get("code")),
        )
        if not year:
            generic_year = re.search(r"\b(20\d{2}|19\d{2})\b", text)
            if generic_year:
                year = self._validated_year(generic_year.group(1), context.get("code"))
        if not year:
            return None
        paper_match = re.search(r"\bpaper\s*(\d{1,2})\b", text, re.IGNORECASE)
        if not paper_match:
            paper_match = re.search(r"practice[- ]paper[- ](\d{1,2})", lowered, re.IGNORECASE)
        if not paper_match:
            return None
        paper = paper_match.group(1).lstrip("0") or "0"
        variant = ""
        mode_match = re.search(r"practice-paper-\d+-(pure|mechanics|statistics|probability-and-statistics)", lowered)
        if not mode_match:
            mode_match = re.search(r"\b(pure|mechanics|statistics|probability and statistics)\b", normalized_text)
        if mode_match:
            mapping = {
                "pure": "",
                "mechanics": "2",
                "statistics": "1",
                "probability-and-statistics": "1",
                "probability and statistics": "1",
            }
            variant = mapping.get(mode_match.group(1), "")
        type_ = (
            "ms"
            if any(token in lowered for token in ["answer", "answers", "model-answer", "model-answers"])
            or "model answer" in normalized_text
            or "model answers" in normalized_text
            else "qp"
        )
        session = "spec"
        parts = [year, session, "alevel", context["subject"], context["board"], context["code"], paper]
        if variant:
            parts.append(variant)
        parts.append(type_)
        candidate = self._normalize_name("-".join(parts))
        return candidate if self._is_well_named(candidate) else None

    def _split_component_hint(
        self,
        value: str,
        explicit_paper: str = "",
        type_hint: str = "",
    ) -> tuple[str, str]:
        token = re.sub(r"[^a-z0-9]", "", value.strip().lower())
        if not token:
            return "", ""
        if explicit_paper:
            if token == explicit_paper:
                return explicit_paper, ""
            if token.startswith(explicit_paper):
                remainder = token[len(explicit_paper):]
                if type_hint in {"transcript", "te"} and remainder in {"t", "v"}:
                    return explicit_paper, ""
                if remainder == "0":
                    return explicit_paper, ""
                return explicit_paper, remainder
            if token.lstrip("0") == explicit_paper:
                return explicit_paper, ""
        if re.fullmatch(r"\d{2}", token):
            return token[0], token[1]
        if re.fullmatch(r"\d[a-z0-9]", token):
            return token[0], token[1]
        if re.fullmatch(r"\d{1,2}", token):
            return token.lstrip("0") or "0", ""
        match = re.match(r"(\d{1,2})([a-z]+)$", token)
        if match:
            return match.group(1).lstrip("0") or "0", match.group(2)
        return "", ""

    def _exam_year_from_text(self, text: str) -> str:
        patterns = [
            r"\bspecimen\s+(20\d{2}|19\d{2})\b",
            r"\b(?:jan|feb|mar|apr|may|jun|june|jul|aug|sep|sept|oct|nov|dec)(\d{2})\b",
            r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+(20\d{2}|19\d{2})\b",
            r"\b\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+(20\d{2}|19\d{2})\b",
            r"\b(?:summer|winter|spring|autumn|january|february|march|april|may|june|july|august|september|october|november|december)\s+(20\d{2}|19\d{2})\b",
            r"\b(?:copyright\s+)?(20\d{2}|19\d{2})\s+(?:pearson|edexcel|aqa|ocr|cambridge)\b",
            r"\bfor examination from\s+(20\d{2}|19\d{2})\b",
            r"\b(?:specimen|sample assessment).*?(20\d{2}|19\d{2})\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                year = match.group(1)
                return self._expand_short_year(year) if re.fullmatch(r"\d{2}", year) else year
        return ""

    def _session_from_month_number(self, value: str) -> str:
        mapping = {
            "01": "jan",
            "02": "feb",
            "03": "mar",
            "05": "may",
            "06": "jun",
            "10": "oct",
            "11": "nov",
        }
        return mapping.get(value, "")

    def _sibling_text_hints(self, pdf_path: Path) -> dict[str, str]:
        group_key = self._opaque_group_key(pdf_path)
        if not group_key:
            return {}
        cached = self._sibling_hint_cache.get(group_key)
        if cached is not None:
            return cached

        hints: dict[str, str] = {}
        siblings = sorted(pdf_path.parent.glob(f"{group_key}*.pdf"))
        for sibling in siblings[:6]:
            if sibling == pdf_path:
                continue
            try:
                sibling_text = self.extractor.extract_first_pages(sibling, pages=2)
            except Exception:
                continue
            sibling_hints = self._text_hints(sibling_text)
            for key, value in sibling_hints.items():
                if value and key not in hints:
                    hints[key] = value
            if all(key in hints for key in ("year", "session", "code", "paper", "type")):
                break

        self._sibling_hint_cache[group_key] = hints
        return hints

    def _opaque_group_key(self, pdf_path: Path) -> str:
        match = re.match(r"(ppr_[A-Za-z0-9]+)_", pdf_path.stem)
        return match.group(1) if match else ""

    def _year_from_stem(self, stem: str) -> str:
        match = re.search(r"\b((19|20)\d{2})\b", stem.replace("_", "-"))
        return match.group(1) if match else ""

    def _session_from_stem(self, stem: str) -> str:
        for token in re.split(r"[-_]+", stem):
            normalized = self._normalize_session(token)
            if normalized:
                return normalized
        return ""

    def _level_from_stem(self, stem: str) -> str:
        if "-alevel-" in stem or "-a-level-" in stem:
            return "alevel"
        if "-igcse-" in stem:
            return "igcse"
        if "-ib-" in stem:
            return "ib"
        return ""

    def _board_from_stem(self, stem: str) -> str:
        return self._extract_board_token(stem) or ""

    def _code_from_stem(self, stem: str) -> str:
        match = re.search(r"-(cie|cambridge|edexcel|aqa|ocr|ib)-([a-z0-9]{3,6})-", stem, re.IGNORECASE)
        return self._normalize_code(match.group(2)) if match else ""

    def _compound_code_from_stem(self, stem: str) -> str:
        for token in re.split(r"[-_]+", stem):
            if re.fullmatch(r"\d{5}", token):
                return token[:4]
        return ""

    def _type_from_stem(self, stem: str) -> str:
        match = re.search(r"(?:^|[-_])(qp|ms|er|in|transcript|sqp|sm|sp|prm|pm|te|gt)(?:$|[-_])", stem, re.IGNORECASE)
        return match.group(1).lower() if match else ""

    def _paper_from_compound_code(self, stem: str) -> str:
        for token in re.split(r"[-_]+", stem):
            if re.fullmatch(r"\d{5}", token):
                return token[-1]
        return ""

    def _resolve_paper_variant(
        self,
        data_paper: Any,
        data_variant: Any,
        hint_paper: str | None,
        hint_variant: str | None,
        stem: str,
    ) -> tuple[str, str]:
        stem_match = re.search(r"-(?:p)?(\d)(?:-(\d|[a-z]))?-(qp|ms|er|in|transcript|sqp|sm|sp|prm|pm|te|gt)$", stem, re.IGNORECASE)
        compact_match = re.search(r"[_-]p?(\d)(\d)(?:[_-]|$)", stem, re.IGNORECASE)
        paper = ""
        variant = ""

        if stem_match:
            paper = stem_match.group(1)
            if stem_match.group(2):
                variant = stem_match.group(2).lower()

        if compact_match:
            paper = paper or compact_match.group(1)
            variant = variant or compact_match.group(2)

        data_paper_text = re.sub(r"^p", "", str(data_paper or "").strip().lower())
        data_variant_text = str(data_variant or "").strip().lower()
        if not paper and re.fullmatch(r"\d{1,2}", data_paper_text):
            paper = data_paper_text
        if not variant and re.fullmatch(r"[a-z0-9]{1,3}", data_variant_text):
            variant = data_variant_text
        if not paper:
            paper = hint_paper or ""
        if not variant:
            variant = hint_variant or ""

        return paper, variant

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
