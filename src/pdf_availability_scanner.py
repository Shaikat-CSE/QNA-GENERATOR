from __future__ import annotations

import csv
import datetime as dt
import json
import re
import shutil
import threading
import tkinter as tk
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from pypdf import PdfReader

BYTES_SUFFIX_RE = re.compile(r"-[\d,]+bytes$", re.IGNORECASE)
PDF_KIND_RE = re.compile(r"^(?P<stem>.+?)(?:-dup\d+)?-(?P<kind>qp|ms|er|in|transcript|sqp|sm|sp|prm|pm|te|gt)$", re.IGNORECASE)
IB_PAPER_RE = re.compile(r"^(?P<stem>.+)-paper\d+-(?P<tz>tz\d+|n)-(?P<kind>qp|ms|er|in|te|gt)$", re.IGNORECASE)
LEGACY_CAMBRIDGE_RE = re.compile(
    r"^(?P<code>\d{4})_y(?P<year>\d{2})_(?P<kind>sm|sp|sqp|qp|ms|er|in|transcript)(?:_(?P<paper>\d+))?$",
    re.IGNORECASE,
)
COMPACT_CAMBRIDGE_RE = re.compile(
    r"^(?P<code>\d{4})[-_](?P<session>[smw])(?P<year>\d{2})[-_](?P<kind>qp|ms|er|in|sm|sp|sqp|transcript)[-_](?P<paper>\d)(?P<variant>\d)(?:-\d+)?$",
    re.IGNORECASE,
)
AQA_SHORTHAND_RE = re.compile(
    r"^aqa[-_](?P<code>\d{5})(?P<option>[a-z])?[-_](?P<kind>tr|tn|sms|sqp)(?:[-_](?P<extra>add|cr))?(?:[-_](?P<session>jun|nov|mar|feb|jan|oct)(?P<year>\d{2}))?$",
    re.IGNORECASE,
)
LEGACY_SPECIMEN_INSERT_RE = re.compile(
    r"^(?P<code>\d{4})[-_]y(?P<year>\d{2})[-_](?P<kind>si)[-_](?P<paper>\d+)$",
    re.IGNORECASE,
)
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
DEFAULT_FILENAME_ALIASES_FILE = CONFIG_DIR / "filename_aliases.json"
TOKEN_RE = re.compile(r"[a-z]+|\d+", re.IGNORECASE)
MAX_VALID_PAPER_YEAR = dt.date.today().year - 1
MONTH_YEAR_RE = re.compile(
    r"\b(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s*(?P<year>20\d{2}|\d{2})\b",
    re.IGNORECASE,
)
DAY_MONTH_YEAR_RE = re.compile(
    r"\b\d{1,2}\s+(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(?P<year>20\d{2})\b",
    re.IGNORECASE,
)
EXAM_FROM_YEAR_RE = re.compile(r"\bfor examination from\s+(?P<year>20\d{2})\b", re.IGNORECASE)
SESSION_TOKEN_MAP: dict[str, set[str]] = {
    "s": {"s", "summer", "sum", "jun", "june", "may", "mj", "mayjun", "mayjune"},
    "w": {"w", "winter", "nov", "november", "oct", "october", "on"},
    "m": {"m", "march", "mar", "feb", "february", "jan", "january"},
    "spec": {"spec", "specimen"},
}
MONTH_TO_SESSION = {
    "jan": "M",
    "january": "M",
    "feb": "M",
    "february": "M",
    "mar": "M",
    "march": "M",
    "apr": "M",
    "april": "M",
    "may": "S",
    "jun": "S",
    "june": "S",
    "jul": "S",
    "july": "S",
    "aug": "S",
    "august": "S",
    "sep": "W",
    "sept": "W",
    "september": "W",
    "oct": "W",
    "october": "W",
    "nov": "W",
    "november": "W",
    "dec": "W",
    "december": "W",
}
DEFAULT_FILENAME_ALIASES: dict[str, dict[str, list[str]]] = {
    "kind_aliases": {
        "qp": ["qp", "question paper", "questionpaper", "question-paper", "questions"],
        "ms": ["ms", "rms", "mark scheme", "markscheme", "mark-scheme", "marking scheme", "answers"],
        "er": ["er", "examiner report", "examiner-report", "examinerreport", "report on the examination", "wre"],
        "in": ["in", "si", "insert", "resource booklet", "data booklet", "booklet", "source booklet", "sources booklet", "extracts booklet"],
        "transcript": ["transcript", "listening transcript", "tr"],
        "sqp": ["sqp", "qs", "specimen question paper", "specimen paper", "specimen-qp"],
        "sm": ["sm", "sms", "specimen markscheme", "specimen-ms", "specimen mark scheme"],
        "sp": ["sp", "specimen"],
        "prm": ["prm", "pre-release material", "pre release", "pre_release"],
        "pm": ["pm", "pre-release"],
        "te": ["te", "tn", "teacher notes", "teachers notes", "teacher-notes", "teachers-notes"],
        "gt": ["gt"],
    },
    "session_aliases": {
        "s": ["s", "summer", "june", "may june", "may-june"],
        "w": ["w", "winter", "november", "october november", "october-november"],
        "m": ["m", "march", "february march", "february-march"],
    },
    "subject_aliases": {
        "Accounting": ["accounting", "acc"],
        "Additional Mathematics": ["additional mathematics", "add maths", "addmaths", "am"],
        "Biology": ["biology", "bio", "4bi1"],
        "Business": ["business", "bus"],
        "Business Management": ["business management", "business-management", "bm"],
        "Business Studies": ["business studies", "business-studies", "bs"],
        "Chemistry": ["chemistry", "chem", "4ch1"],
        "Chinese": ["chinese", "mandarin", "chn"],
        "Chinese A": ["chinese a", "chinese a language literature"],
        "Chinese B Mandarin": ["chinese b mandarin", "chinese b", "chn b"],
        "Chinese First Language": ["chinese first language", "cfl", "chinese fl"],
        "Chinese Mandarin Foreign Language": ["chinese mandarin foreign language", "chinese mandarin fl", "cmfl"],
        "Chinese Second Language": ["chinese second language", "csl", "chinese sl"],
        "Combined Science": ["combined science", "combinedsciences", "sc"],
        "Commerce": ["commerce", "comm"],
        "Computer Science": ["computer science", "computer-science", "computerscience", "cs", "4cp0", "4cs0"],
        "Design Technology": ["design technology", "design-and-technology", "dt", "design technology"],
        "Digital Societies": ["digital societies", "digital-societies", "ds"],
        "Economics": ["economics", "econ", "econmics"],
        "English A Language Literature": ["english a language literature", "eal", "eng a"],
        "English Language": ["english language", "english-language", "eng lang", "elang"],
        "English Literature": ["english literature", "english-literature", "eng lit", "englit", "english lit"],
        "English Second Language": ["english second language", "esl", "english sl", "eng as second language"],
        "Enterprise": ["enterprise", "ent"],
        "Environmental Management": ["environmental management", "em"],
        "Environmental Systems Societies": ["environmental systems and societies", "ess", "environmental systems societies"],
        "First Language English": ["first language english", "fle", "fleng"],
        "Food and Nutrition": ["food and nutrition", "food nutrition", "fn"],
        "Food Science and Technology": ["food science and technology", "fst"],
        "French": ["french", "fr"],
        "Further Mathematics": ["further mathematics", "further-maths", "fm", "furthermaths", "furthermathematics"],
        "Geography": ["geography", "geo"],
        "Global Perspectives": ["global perspectives", "global-perspectives", "gp", "globalperspectives"],
        "Global Politics": ["global politics", "gp"],
        "History": ["history", "hist"],
        "Human Biology": ["human biology", "humanbio", "hb"],
        "ICT": ["ict", "information and communication technology", "it"],
        "Information Technology": ["information technology", "ict", "it"],
        "International Mathematics": ["international mathematics", "intl maths", "international maths"],
        "Mathematics": ["mathematics", "maths", "math", "4ma1", "mathematics and statistics"],
        "Mathematics AA": ["mathematics aa", "mathematics analysis and approaches", "aa"],
        "Music": ["music", "mus"],
        "Philosophy": ["philosophy", "phil", "philo"],
        "Physical Education": ["physical education", "pe", "physical-education", "sport"],
        "Physical Science": ["physical science", "phys science", "ps"],
        "Physics": ["physics", "phys", "4ph1"],
        "Psychology": ["psychology", "psych", "psy"],
        "Social and Cultural Anthropology": ["social and cultural anthropology", "sca", "anthropology"],
        "Sociology": ["sociology", "soc"],
        "Sports Exercise Health Science": ["sports exercise health science", "sehs", "sports health science"],
        "Visual Arts": ["visual arts", "va", "art"],
    },
    "syllabus_aliases": {
        "IGCSE": ["igcse", "international gcse", "intl gcse"],
        "A-Level": ["alevel", "a level", "a-level", "gce", "as", "as-a"],
        "IB": ["ib", "international baccalaureate", "ibdp"],
        "Cambridge": ["cambridge", "cie", "ucles", "camb", "cambridge intl"],
        "Edexcel": ["edexcel", "pearson", "edx"],
        "AQA": ["aqa", "assessment and qualifications alliance"],
        "OCR": ["ocr"],
    },
}
SUBJECT_NOISE_TOKENS = frozenset(
    {
        "question",
        "questions",
        "paper",
        "papers",
        "mark",
        "marks",
        "scheme",
        "marking",
        "answer",
        "answers",
        "qp",
        "ms",
        "er",
        "in",
        "n",
        "r",
        "regional",
        "variant",
        "tz",
        "time",
        "zone",
        "paper",
        "component",
        "option",
        "written",
        "practical",
        "oral",
        "audio",
        "script",
        "level",
        "component",
        "unit",
        "module",
        "AS",
        "A2",
        "unit",
    }
)


@dataclass
class PaperStatus:
    year: str
    session: str
    paper_key: str
    has_qp: bool
    has_ms: bool
    qp_path: str
    ms_path: str
    subject: str = "unknown"
    syllabus: str = "unknown"
    has_er: bool = False
    has_in: bool = False
    has_transcript: bool = False
    er_path: str = "-"
    in_path: str = "-"
    transcript_path: str = "-"
    source: str = "unknown"

    @property
    def status(self) -> str:
        if self.has_qp and self.has_ms:
            return "Complete"
        elif self.has_qp:
            return "Missing MS"
        elif self.has_ms:
            return "Missing QP"
        return "No QP/MS"

    @property
    def status_icon(self) -> str:
        if self.has_qp and self.has_ms:
            return "✓"
        if self.has_qp or self.has_ms:
            return "⚠"
        return "✗"


@dataclass(frozen=True)
class ReviewItem:
    filename: str
    path: str
    reason: str
    suggestion: str = ""


@dataclass(frozen=True)
class AvailabilityScanReport:
    papers: list[PaperStatus]
    review_items: list[ReviewItem]


@dataclass(frozen=True)
class FilenameClassification:
    paper_key: str
    kind: str
    source: str


def tokenize_text(text: str) -> tuple[str, ...]:
    return tuple(match.group(0).lower() for match in TOKEN_RE.finditer(text))


def slug_tokens(text: str) -> tuple[str, ...]:
    return tokenize_text(text)


def merge_alias_config(raw: dict[str, object] | None) -> dict[str, dict[str, list[str]]]:
    merged = {
        section: {key: list(values) for key, values in section_values.items()}
        for section, section_values in DEFAULT_FILENAME_ALIASES.items()
    }
    if not isinstance(raw, dict):
        return merged

    for section in ("kind_aliases", "session_aliases", "subject_aliases", "syllabus_aliases"):
        section_raw = raw.get(section)
        if not isinstance(section_raw, dict):
            continue
        target = merged.setdefault(section, {})
        for label, aliases_raw in section_raw.items():
            if not isinstance(aliases_raw, list):
                continue
            aliases = [str(item).strip() for item in aliases_raw if str(item).strip()]
            if aliases:
                existing = target.setdefault(str(label), [])
                for alias in aliases:
                    if alias not in existing:
                        existing.append(alias)
    return merged


def load_filename_aliases(path: Path = DEFAULT_FILENAME_ALIASES_FILE) -> dict[str, dict[str, list[str]]]:
    if not path.exists():
        return merge_alias_config(None)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return merge_alias_config(None)
    return merge_alias_config(raw)


def alias_token_map(aliases: dict[str, list[str]]) -> dict[str, list[tuple[str, ...]]]:
    mapped: dict[str, list[tuple[str, ...]]] = {}
    for label, values in aliases.items():
        mapped[label] = sorted(
            {slug_tokens(value) for value in values if slug_tokens(value)},
            key=len,
            reverse=True,
        )
    return mapped


def find_alias_matches(tokens: tuple[str, ...], aliases: dict[str, list[str]]) -> list[tuple[str, int, int]]:
    matches: list[tuple[str, int, int]] = []
    for label, phrases in alias_token_map(aliases).items():
        for phrase in phrases:
            phrase_len = len(phrase)
            for index in range(0, len(tokens) - phrase_len + 1):
                if tokens[index : index + phrase_len] == phrase:
                    matches.append((label, index, index + phrase_len))
    return matches


def contains_token_phrase(tokens: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    if not phrase:
        return False
    phrase_len = len(phrase)
    return any(tokens[index : index + phrase_len] == phrase for index in range(0, len(tokens) - phrase_len + 1))


def remove_token_span(tokens: tuple[str, ...], start: int, end: int) -> tuple[str, ...]:
    return tokens[:start] + tokens[end:]


def replace_alias_tokens(tokens: tuple[str, ...], aliases: dict[str, list[str]]) -> tuple[str, ...]:
    phrases: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    for label, values in aliases.items():
        replacement = slug_tokens(label)
        for value in values:
            phrase = slug_tokens(value)
            if phrase:
                phrases.append((phrase, replacement))
    phrases.sort(key=lambda item: len(item[0]), reverse=True)

    output: list[str] = []
    index = 0
    while index < len(tokens):
        matched = False
        for phrase, replacement in phrases:
            phrase_len = len(phrase)
            if tokens[index : index + phrase_len] == phrase:
                output.extend(replacement)
                index += phrase_len
                matched = True
                break
        if not matched:
            output.append(tokens[index])
            index += 1
    return tuple(output)


def build_text_only_aliases(aliases: dict[str, list[str]]) -> dict[str, list[str]]:
    filtered: dict[str, list[str]] = {}
    for label, values in aliases.items():
        text_values = []
        for value in values:
            value_tokens = slug_tokens(value)
            if value_tokens and all(token.isalpha() for token in value_tokens):
                text_values.append(value)
        if text_values:
            filtered[label] = text_values
    return filtered


def normalize_strict_key_tokens(tokens: tuple[str, ...], aliases: dict[str, dict[str, list[str]]]) -> tuple[str, ...]:
    output: list[str] = []
    index = 0
    while index < len(tokens):
        if index + 1 < len(tokens) and tokens[index] == "a" and tokens[index + 1] == "level":
            output.append("alevel")
            index += 2
            continue
        if index + 1 < len(tokens) and tokens[index] == "as" and tokens[index + 1] == "level":
            output.append("aslevel")
            index += 2
            continue
        if index + 1 < len(tokens) and tokens[index] == "further" and tokens[index + 1] == "maths":
            output.extend(["further", "mathematics"])
            index += 2
            continue

        token = tokens[index]
        if token == "maths":
            token = "mathematics"
        elif token == "cie":
            token = "cambridge"
        output.append(token)
        index += 1

    return normalize_paper_key_tokens(tuple(output))


def infer_board_token_from_path(path: Path) -> str | None:
    path_tokens = tokenize_text(str(path).lower())
    if "cambridge" in path_tokens or "cie" in path_tokens:
        return "cambridge"
    if "edexcel" in path_tokens or "pearson" in path_tokens:
        return "edexcel"
    if "aqa" in path_tokens:
        return "aqa"
    if "ocr" in path_tokens:
        return "ocr"
    if "ib" in path_tokens:
        return "ib"
    return None


def inject_board_token(tokens: tuple[str, ...], board_token: str) -> tuple[str, ...]:
    if board_token in tokens:
        return tokens
    insert_at = len(tokens)
    for index, token in enumerate(tokens):
        if re.fullmatch(r"\d{4}", token) or re.fullmatch(r"\d+[a-z]+\d*", token):
            insert_at = index
            break
    updated = list(tokens)
    updated.insert(insert_at, board_token)
    return tuple(updated)


def canonicalize_key_tokens(tokens: tuple[str, ...], aliases: dict[str, dict[str, list[str]]]) -> tuple[str, ...]:
    tokens = replace_alias_tokens(tokens, aliases.get("session_aliases", {}))
    tokens = replace_alias_tokens(tokens, aliases.get("subject_aliases", {}))
    tokens = replace_alias_tokens(tokens, aliases.get("syllabus_aliases", {}))
    return normalize_paper_key_tokens(tokens)


def normalize_paper_key_tokens(tokens: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    index = 0

    while index < len(tokens):
        # Merge split syllabus codes like 9-hi-0 -> 9hi0.
        if (
            index + 2 < len(tokens)
            and re.fullmatch(r"\d{1,2}", tokens[index])
            and re.fullmatch(r"[a-z]{1,3}", tokens[index + 1])
            and re.fullmatch(r"\d{1,2}", tokens[index + 2])
        ):
            normalized.append(f"{tokens[index]}{tokens[index + 1]}{tokens[index + 2]}")
            index += 3
            continue

        token = tokens[index]
        if re.fullmatch(r"0\d", token):
            token = str(int(token))
        normalized.append(token)
        index += 1

    deduped: list[str] = []
    for token in normalized:
        if (
            deduped
            and deduped[-1] == token
            and re.fullmatch(r"\d+[a-z]+\d*", token)
        ):
            continue
        deduped.append(token)

    # Normalize compact Cambridge/CIE component notation like 33 -> 3-3.
    if len(deduped) >= 2:
        tail = deduped[-1]
        token_set = set(deduped)
        has_numeric_syllabus_code = any(
            re.fullmatch(r"\d{4}", token) and token not in {"1900", "2000", "2100"}
            for token in deduped[1:]
        )
        if re.fullmatch(r"\d{2}", tail) and (("cie" in token_set or "cambridge" in token_set) or has_numeric_syllabus_code):
            deduped[-1:] = [tail[0], tail[1]]

    return tuple(deduped)


def title_from_tokens(tokens: list[str]) -> str:
    return " ".join(token.upper() if len(token) <= 3 else token.title() for token in tokens)


def slugify_filename_subject(subject: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", subject.strip().lower())).strip("-")


def infer_subject_from_key_tokens(
    paper_key: str,
    aliases: dict[str, dict[str, list[str]]],
) -> str:
    tokens = list(tokenize_text(paper_key))
    removable: set[str] = set(SUBJECT_NOISE_TOKENS)

    for section in ("session_aliases", "syllabus_aliases"):
        for label, values in aliases.get(section, {}).items():
            removable.update(slug_tokens(label))
            for value in values:
                removable.update(slug_tokens(value))

    candidates: list[str] = []
    for token in tokens:
        if token in removable:
            continue
        if token.isdigit():
            continue
        if len(token) <= 2:
            continue
        if re.fullmatch(r"\d+[a-z]+\d*", token):
            continue
        if re.fullmatch(r"\d{4}", token):
            continue
        candidates.append(token)

    return title_from_tokens(candidates[:3]) if candidates else "unknown"


def canonical_stem(path: Path) -> str | None:
    stem = BYTES_SUFFIX_RE.sub("", path.stem.lower())
    match = PDF_KIND_RE.match(stem)
    if not match:
        return None
    normalized_tokens = normalize_strict_key_tokens(tokenize_text(match.group("stem")), load_filename_aliases())
    board_token = infer_board_token_from_path(path)
    if board_token is not None:
        normalized_tokens = inject_board_token(normalized_tokens, board_token)
    return f"{'-'.join(normalized_tokens)}-{match.group('kind').lower()}"


def is_year_token(year_text: str) -> bool:
    if not re.fullmatch(r"(19|20)\d{2}", year_text):
        return False
    year = int(year_text)
    return year <= MAX_VALID_PAPER_YEAR


def extract_exam_code_token(paper_key: str) -> str | None:
    for part in paper_key.lower().split("-"):
        if re.fullmatch(r"[0479]\d{3}", part):
            return part
        if re.fullmatch(r"9[a-z0-9]{3}", part):
            return part
        prefix_match = re.match(r"(?P<code>[0479]\d{3})[a-z0-9]+$", part)
        if prefix_match:
            return prefix_match.group("code")
    return None


def extract_exam_code_from_path(path: Path) -> str | None:
    for part in reversed(path.parts):
        paren_match = re.search(r"\((?P<code>[0479]\d{3}|9[a-z0-9]{3})\)", part, re.IGNORECASE)
        if paren_match:
            return paren_match.group("code").lower()
        direct_match = re.search(r"\b(?P<code>[0479]\d{3}|9[a-z0-9]{3})\b", part, re.IGNORECASE)
        if direct_match:
            return direct_match.group("code").lower()
    return None


def minimum_year_for_exam_code(exam_code: str | None) -> int | None:
    if not exam_code:
        return None
    if exam_code == "9618":
        return 2021
    if re.fullmatch(r"7\d{3}", exam_code):
        return 2014
    if re.fullmatch(r"9[a-z0-9]{3}", exam_code):
        return 2014
    return None


def specimen_year_for_exam_code(exam_code: str | None) -> int | None:
    minimum = minimum_year_for_exam_code(exam_code)
    if minimum is not None:
        return minimum
    return 2000 if exam_code else None


def extract_display_year(paper_key: str, source: str = "unknown") -> str:
    year_match = re.match(r"^(?P<year>\d{4})", paper_key)
    if not year_match:
        return "unknown"
    year = year_match.group("year")
    if not is_year_token(year):
        return "unknown"
    exam_code = extract_exam_code_token(paper_key)
    minimum_year = minimum_year_for_exam_code(exam_code)
    if minimum_year is not None and int(year) < minimum_year:
        return "unknown"
    if source != "legacy" and extract_session_label(paper_key) == "?":
        return "unknown"
    return year


def normalize_year_text(year_text: str) -> str | None:
    value = year_text.strip()
    if len(value) == 2:
        value = f"20{value}"
    if is_year_token(value):
        return value
    return None


def infer_exam_year_session_from_pdf(path: Path, exam_code: str | None = None) -> tuple[str | None, str | None]:
    try:
        reader = PdfReader(str(path))
    except Exception:
        return None, None

    text_parts: list[str] = []
    metadata = reader.metadata or {}
    for key in ("/Title", "/Subject", "/SeriesMonth", "/ExamSeriesFacet", "/Subtitle", "/grouping"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            text_parts.append(value)

    for index in range(min(2, len(reader.pages))):
        try:
            page_text = reader.pages[index].extract_text() or ""
        except Exception:
            page_text = ""
        if page_text:
            text_parts.append(page_text[:4000])

    haystack = "\n".join(text_parts)
    lowered = haystack.lower()

    if "specimen" in lowered or "sample set" in lowered:
        match = EXAM_FROM_YEAR_RE.search(haystack)
        if match:
            return match.group("year"), "SPEC"
        specimen_year = specimen_year_for_exam_code(exam_code)
        return (str(specimen_year), "SPEC") if specimen_year else (None, "SPEC")

    for pattern in (DAY_MONTH_YEAR_RE, MONTH_YEAR_RE):
        match = pattern.search(haystack)
        if not match:
            continue
        year = normalize_year_text(match.group("year"))
        if not year:
            continue
        month = match.group("month").lower()
        session = MONTH_TO_SESSION.get(month)
        if session:
            return year, session

    metadata_text = " ".join(
        str(metadata.get(key, "")).strip()
        for key in ("/PublishedWhen", "/CreationDate", "/ModDate")
    )
    for pattern in (DAY_MONTH_YEAR_RE, MONTH_YEAR_RE):
        match = pattern.search(metadata_text)
        if not match:
            continue
        year = normalize_year_text(match.group("year"))
        if not year:
            continue
        month = match.group("month").lower()
        session = MONTH_TO_SESSION.get(month)
        if session:
            return year, session

    candidate_years = {
        year
        for year in (
            normalize_year_text(match.group(0))
            for match in re.finditer(r"\b20\d{2}\b", haystack)
        )
        if year is not None
    }
    minimum_year = minimum_year_for_exam_code(exam_code)
    if minimum_year is not None:
        candidate_years = {year for year in candidate_years if int(year) >= minimum_year}
    if candidate_years:
        return max(candidate_years, key=int), None

    return None, None


def sort_year_values(years: set[str]) -> list[str]:
    def year_key(value: str) -> tuple[int, int | str]:
        if value.isdigit():
            return (0, -int(value))
        return (1, value)

    return sorted(years, key=year_key)


def alias_key_is_exact_enough(
    original_tokens: tuple[str, ...],
    key_tokens: tuple[str, ...],
    aliases: dict[str, dict[str, list[str]]],
) -> bool:
    if not key_tokens:
        return False
    if not is_year_token(key_tokens[0]):
        return False

    year_tokens = [token for token in original_tokens if is_year_token(token)]
    if len(year_tokens) != 1:
        return False
    if year_tokens[0] != key_tokens[0]:
        return False
    return extract_session_label("-".join(original_tokens)) != "?"


def should_ignore_non_exam_pdf(stem: str) -> bool:
    lowered = stem.lower()
    return bool(
        re.search(r"(?:^|[-_])other$", lowered)
        or "year-1-and-as" in lowered
        or "student-book" in lowered
        or "data-booklet-generic" in lowered
        or "data-formulae-generic" in lowered
        or "formulae-generic" in lowered
        or re.search(r"\b97[89]\d{10}\b", lowered)
    )


def classify_pdf_filename(
    path: Path,
    aliases: dict[str, dict[str, list[str]]],
) -> tuple[FilenameClassification | None, ReviewItem | None]:
    stem = BYTES_SUFFIX_RE.sub("", path.stem.lower())

    if should_ignore_non_exam_pdf(stem):
        return None, None

    legacy_match = LEGACY_CAMBRIDGE_RE.match(stem)
    if legacy_match:
        year = f"20{legacy_match.group('year')}"
        if not is_year_token(year):
            return (
                None,
                ReviewItem(
                    filename=path.name,
                    path=str(path),
                    reason=f"Legacy filename resolved to out-of-range year {year}",
                ),
            )

        key_tokens = [year]
        board_token = infer_board_token_from_path(path)
        if board_token is not None:
            key_tokens.append(board_token)
        key_tokens.append(legacy_match.group("code"))
        paper = legacy_match.group("paper")
        if paper:
            key_tokens.extend(["paper", str(int(paper))])
        paper_key = "-".join(key_tokens)
        return (
            FilenameClassification(
                paper_key=paper_key,
                kind=legacy_match.group("kind").lower(),
                source="legacy",
            ),
            None,
        )

    specimen_insert_match = LEGACY_SPECIMEN_INSERT_RE.match(stem)
    if specimen_insert_match:
        year = f"20{specimen_insert_match.group('year')}"
        if not is_year_token(year):
            return (
                None,
                ReviewItem(
                    filename=path.name,
                    path=str(path),
                    reason=f"Legacy filename resolved to out-of-range year {year}",
                ),
            )
        key_tokens = [year, "spec"]
        board_token = infer_board_token_from_path(path) or "cambridge"
        key_tokens.append(board_token)
        key_tokens.append(specimen_insert_match.group("code"))
        key_tokens.extend(["paper", str(int(specimen_insert_match.group("paper")))])
        return (
            FilenameClassification(
                paper_key="-".join(key_tokens),
                kind="in",
                source="legacy",
            ),
            None,
        )

    compact_match = COMPACT_CAMBRIDGE_RE.match(stem)
    if compact_match:
        year = f"20{compact_match.group('year')}"
        session = compact_match.group("session").lower()
        key_tokens = [year, session]
        board_token = infer_board_token_from_path(path) or "cambridge"
        key_tokens.append(board_token)
        key_tokens.append(compact_match.group("code"))
        key_tokens.append(compact_match.group("paper"))
        key_tokens.append(compact_match.group("variant"))
        paper_key = "-".join(key_tokens)
        kind = compact_match.group("kind").lower()
        return (
            FilenameClassification(
                paper_key=paper_key,
                kind=kind,
                source="compact-cambridge",
            ),
            None,
        )

    aqa_match = AQA_SHORTHAND_RE.match(stem)
    if aqa_match:
        code5 = aqa_match.group("code")
        code = code5[:4]
        paper = code5[-1]
        option = (aqa_match.group("option") or "").lower()
        kind_token = aqa_match.group("kind").lower()
        kind_map = {"tr": "transcript", "tn": "te", "sms": "sm", "sqp": "sqp"}
        kind = kind_map[kind_token]
        if kind in {"sm", "sqp"}:
            session = "spec"
            year_value = specimen_year_for_exam_code(code)
            year = str(year_value) if year_value else ""
        else:
            session = (aqa_match.group("session") or "").lower()
            year_suffix = aqa_match.group("year") or ""
            year = f"20{year_suffix}" if year_suffix else ""
        if year and session:
            key_tokens = [year, session]
            level = "alevel"
            _, (subject, _) = find_subject_folder(path.parent, aliases)
            if subject != "unknown":
                key_tokens.extend([level, slugify_filename_subject(subject), "aqa", code, paper])
                if option:
                    key_tokens.append(option)
                paper_key = "-".join(key_tokens)
                return (
                    FilenameClassification(
                        paper_key=paper_key,
                        kind=kind,
                        source="aqa-shorthand",
                    ),
                    None,
                )

    # Try IB pattern first (paper1-tz1-qp)
    ib_match = IB_PAPER_RE.match(stem)
    if ib_match:
        normalized_tokens = normalize_strict_key_tokens(tokenize_text(ib_match.group("stem")), aliases)
        board_token = infer_board_token_from_path(path)
        if board_token is not None:
            normalized_tokens = inject_board_token(normalized_tokens, board_token)
        paper_key = "-".join(normalized_tokens)
        return (
            FilenameClassification(
                paper_key=paper_key,
                kind=ib_match.group("kind").lower(),
                source="strict",
            ),
            None,
        )

    # Try standard pattern (ends with -qp/-ms/-er/-in/-transcript)
    strict_match = PDF_KIND_RE.match(stem)
    if strict_match:
        normalized_tokens = normalize_strict_key_tokens(tokenize_text(strict_match.group("stem")), aliases)
        board_token = infer_board_token_from_path(path)
        if board_token is not None:
            normalized_tokens = inject_board_token(normalized_tokens, board_token)
        paper_key = "-".join(normalized_tokens)
        return (
            FilenameClassification(
                paper_key=paper_key,
                kind=strict_match.group("kind").lower(),
                source="strict",
            ),
            None,
        )

    tokens = tokenize_text(stem)
    kind_matches = find_alias_matches(tokens, aliases.get("kind_aliases", {}))
    if not kind_matches:
        return (
            None,
            ReviewItem(
                filename=path.name,
                path=str(path),
                reason="No question-paper or mark-scheme marker found",
            ),
        )

    matched_kinds = sorted({match[0] for match in kind_matches})
    if len(matched_kinds) != 1:
        return (
            None,
            ReviewItem(
                filename=path.name,
                path=str(path),
                reason=f"Ambiguous paper type markers: {', '.join(matched_kinds)}",
            ),
        )

    kind, start, end = max(kind_matches, key=lambda match: match[2] - match[1])
    key_source_tokens = remove_token_span(tokens, start, end)
    key_tokens = canonicalize_key_tokens(key_source_tokens, aliases)
    if not key_tokens:
        return (
            None,
            ReviewItem(
                filename=path.name,
                path=str(path),
                reason="Could not build a paper key after removing the paper type marker",
            ),
        )

    if not alias_key_is_exact_enough(key_source_tokens, key_tokens, aliases):
        return (
            None,
            ReviewItem(
                filename=path.name,
                path=str(path),
                reason="Filename was too ambiguous to derive an exact paper year and session",
            ),
        )

    paper_key = "-".join(key_tokens)
    suggestion = f"{paper_key}-{kind}.pdf"
    return (
        FilenameClassification(paper_key=paper_key, kind=kind, source="alias"),
        ReviewItem(
            filename=path.name,
            path=str(path),
            reason="Recognized using filename aliases",
            suggestion=suggestion,
        ),
    )


def choose_preferred_path(paths: list[Path]) -> Path | None:
    if not paths:
        return None

    def score(path: Path) -> tuple[int, int, int, str]:
        has_bytes_suffix = 0 if BYTES_SUFFIX_RE.search(path.stem) else 1
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        return (has_bytes_suffix, size, -len(path.name), path.name.lower())

    return max(paths, key=score)


def extract_subject_syllabus(
    paper_key: str,
    aliases: dict[str, dict[str, list[str]]] | None = None,
) -> tuple[str, str]:
    """Extract subject and syllabus from paper key."""
    lower_key = paper_key.lower()
    key_tokens = tokenize_text(lower_key)
    aliases = aliases or load_filename_aliases()

    # Subject detection
    subject = "unknown"
    for label, values in aliases.get("subject_aliases", {}).items():
        if any(contains_token_phrase(key_tokens, slug_tokens(value)) for value in values):
            subject = label
            break
    if subject == "unknown":
        subject = infer_subject_from_key_tokens(paper_key, aliases)

    # Syllabus detection
    syllabus = "unknown"
    for label, values in aliases.get("syllabus_aliases", {}).items():
        if any(contains_token_phrase(key_tokens, slug_tokens(value)) for value in values):
            syllabus = label
            break

    return subject, syllabus


def extract_subject_syllabus_from_folder(folder_path: Path, aliases: dict[str, dict[str, list[str]]] | None = None) -> tuple[str, str]:
    """Extract subject and syllabus from folder name like 'AQA Geography (7037)' or 'Cie Geography (9696)'."""
    aliases = aliases or load_filename_aliases()
    folder_name = folder_path.name

    subject = "unknown"
    syllabus = "unknown"

    folder_tokens = tuple(folder_name.lower().split())
    folder_lower = folder_name.lower()
    parent_name = folder_path.parent.name if folder_path.parent != folder_path else ""

    for label, values in aliases.get("subject_aliases", {}).items():
        if label.lower() in folder_lower:
            subject = label
            break
        for v in values:
            v_tokens = tuple(v.lower().split())
            if len(v_tokens) == 1:
                if v_tokens[0] in folder_tokens:
                    subject = label
                    break
            elif v.lower() in folder_lower:
                subject = label
                break
        if subject != "unknown":
            break

    for label, values in aliases.get("syllabus_aliases", {}).items():
        if label.lower() in folder_lower or label.lower() in parent_name.lower():
            syllabus = label
            break
        for v in values:
            v_tokens = tuple(v.lower().split())
            if len(v_tokens) == 1:
                if v_tokens[0] in folder_tokens or v_tokens[0] == parent_name.lower():
                    syllabus = label
                    break
            elif v.lower() in folder_lower or v.lower() in parent_name.lower():
                syllabus = label
                break
        if syllabus != "unknown":
            break

    if subject == "unknown":
        match = re.search(r'\(([^)]+)\)', folder_name)
        if match:
            code = match.group(1)
            code_lower = code.lower()
            for s_label, s_values in aliases.get("subject_aliases", {}).items():
                if code_lower in [v.lower() for v in s_values]:
                    subject = s_label
                    break
            if subject == "unknown":
                if code.isdigit():
                    subject = code
                else:
                    subject = folder_name.split()[0] if folder_name.split() else "unknown"

    return subject, syllabus


def find_subject_folder(folder_path: Path, aliases: dict[str, dict[str, list[str]]]) -> tuple[Path, tuple[str, str]]:
    """Find the folder that contains subject info by traversing up the tree."""
    current = folder_path
    for _ in range(5):
        result = extract_subject_syllabus_from_folder(current, aliases)
        if result[0] != "unknown":
            return current, result
        parent = current.parent
        if parent == current:
            break
        current = parent
    return folder_path, ("unknown", "unknown")


def should_include_pdf_path(path: Path) -> bool:
    lower_parts = {part.lower() for part in path.parts}
    if "resources" in lower_parts:
        return False
    return True


def extract_session_label(paper_key: str) -> str:
    tokens = tokenize_text(paper_key)
    for token in tokens:
        for label, aliases in SESSION_TOKEN_MAP.items():
            if token in aliases:
                return label.upper() if label != "spec" else "SPEC"
    return "?"


def scan_pdf_directory_report(input_dir: Path) -> AvailabilityScanReport:
    aliases = load_filename_aliases()
    grouped: dict[str, dict[str, list[Path]]] = defaultdict(lambda: defaultdict(list))
    paper_sources: dict[str, set[str]] = defaultdict(set)
    folder_subjects: dict[str, tuple[str, str]] = {}
    review_items: list[ReviewItem] = []

    for path in sorted(input_dir.rglob("*.pdf")):
        if not should_include_pdf_path(path):
            continue

        classification, review_item = classify_pdf_filename(path, aliases)
        if review_item is not None:
            review_items.append(review_item)
        if classification is None:
            continue

        subject_folder, (subject, syllabus) = find_subject_folder(path.parent, aliases)
        folder_key = str(subject_folder)
        if folder_key not in folder_subjects:
            folder_subjects[folder_key] = (subject, syllabus)

        grouped[classification.paper_key][classification.kind].append(path)
        paper_sources[classification.paper_key].add(classification.source)

    results: list[PaperStatus] = []
    for paper_key in sorted(grouped):
        kinds = grouped[paper_key]

        sample_path = None
        for kind_paths in kinds.values():
            if kind_paths:
                sample_path = kind_paths[0]
                break

        if sample_path:
            _, (subject, syllabus) = find_subject_folder(sample_path.parent, aliases)
        else:
            subject, syllabus = "unknown", "unknown"

        if subject == "unknown" or syllabus == "unknown":
            inferred_subject, inferred_syllabus = extract_subject_syllabus(paper_key, aliases)
            if subject == "unknown":
                subject = inferred_subject
            if syllabus == "unknown":
                syllabus = inferred_syllabus

        source = "legacy" if "legacy" in paper_sources.get(paper_key, set()) else "unknown"
        year = extract_display_year(paper_key, source)
        session = extract_session_label(paper_key)

        qp_paths = kinds.get("qp", [])
        ms_paths = kinds.get("ms", [])
        sqp_paths = kinds.get("sqp", [])
        sp_paths = kinds.get("sp", [])
        sm_paths = kinds.get("sm", [])
        er_paths = kinds.get("er", [])
        in_paths = kinds.get("in", [])
        transcript_paths = kinds.get("transcript", [])

        qp_equivalent_paths = qp_paths + sqp_paths + sp_paths
        ms_equivalent_paths = ms_paths + sm_paths

        preferred_qp = (
            choose_preferred_path(qp_paths)
            or choose_preferred_path(sqp_paths)
            or choose_preferred_path(sp_paths)
        )
        preferred_ms = choose_preferred_path(ms_paths) or choose_preferred_path(sm_paths)
        preferred_er = choose_preferred_path(er_paths)
        preferred_in = choose_preferred_path(in_paths)
        preferred_transcript = choose_preferred_path(transcript_paths)

        if year == "unknown" or session == "?":
            preferred_any = (
                preferred_qp
                or preferred_ms
                or preferred_er
                or preferred_in
                or preferred_transcript
            )
            inferred_year = None
            inferred_session = None
            if preferred_any is not None:
                exam_code = extract_exam_code_token(paper_key) or extract_exam_code_from_path(preferred_any)
                inferred_year, inferred_session = infer_exam_year_session_from_pdf(
                    preferred_any,
                    exam_code,
                )
            if year == "unknown" and inferred_year:
                year = inferred_year
            if session == "?" and inferred_session:
                session = inferred_session

        results.append(
            PaperStatus(
                year=year,
                session=session,
                paper_key=paper_key,
                has_qp=len(qp_equivalent_paths) > 0,
                has_ms=len(ms_equivalent_paths) > 0,
                qp_path=str(preferred_qp) if preferred_qp else "-",
                ms_path=str(preferred_ms) if preferred_ms else "-",
                subject=subject,
                syllabus=syllabus,
                has_er=len(er_paths) > 0,
                has_in=len(in_paths) > 0,
                has_transcript=len(transcript_paths) > 0,
                er_path=str(preferred_er) if preferred_er else "-",
                in_path=str(preferred_in) if preferred_in else "-",
                transcript_path=str(preferred_transcript) if preferred_transcript else "-",
                source=source,
            )
        )

    return AvailabilityScanReport(papers=results, review_items=review_items)


def scan_pdf_directory(input_dir: Path) -> list[PaperStatus]:
    return scan_pdf_directory_report(input_dir).papers


def export_to_csv(results: list[PaperStatus], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Year", "Subject", "Syllabus", "Paper", "QP", "MS", "ER", "IN", "Transcript", "Status", "QP_Path", "MS_Path", "ER_Path", "IN_Path", "Transcript_Path"])
        for item in results:
            writer.writerow([
                item.year,
                item.subject,
                item.syllabus,
                item.paper_key,
                "✓" if item.has_qp else "✗",
                "✓" if item.has_ms else "✗",
                "✓" if item.has_er else "✗",
                "✓" if item.has_in else "✗",
                "✓" if item.has_transcript else "✗",
                item.status,
                item.qp_path,
                item.ms_path,
                item.er_path,
                item.in_path,
                item.transcript_path,
            ])


def export_review_to_csv(review_items: list[ReviewItem], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Filename", "Reason", "Suggested_Name", "Path"])
        for item in review_items:
            writer.writerow([item.filename, item.reason, item.suggestion, item.path])


class AvailabilityReportWindow:
    ACCENT = "#0891b2"
    ACCENT_DEEP = "#0e7490"
    BG_MAIN = "#f8fafc"
    BG_CARD = "#ffffff"
    BG_HEADER = "#0c1a2e"
    TEXT_PRIMARY = "#0f172a"
    TEXT_MUTED = "#64748b"
    SUCCESS = "#059669"
    WARNING = "#d97706"
    DANGER = "#dc2626"
    COMPLETE_BG = "#d1fae5"
    PARTIAL_BG = "#fef3c7"
    MISSING_BG = "#fee2e2"
    BORDER = "rgba(14, 116, 144, 0.12)"

    def __init__(self, parent: tk.Tk, report: AvailabilityScanReport | list[PaperStatus], input_dir: Path) -> None:
        if isinstance(report, AvailabilityScanReport):
            self.results = report.papers
            self.review_items = report.review_items
        else:
            self.results = report
            self.review_items = []
        self.input_dir = input_dir
        self.filtered_results = self.results

        self.window = tk.Toplevel(parent)
        self.window.title("PDF Availability Report")
        self.window.geometry("1400x800")
        self.window.minsize(1200, 700)
        self.window.configure(bg=self.BG_MAIN)

        self._build_ui()
        self._populate_matrix()

    def _build_ui(self) -> None:
        container = tk.Frame(self.window, bg=self.BG_MAIN)
        container.pack(fill="both", expand=True, padx=24, pady=24)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)

        header_frame = tk.Frame(container, bg=self.BG_HEADER, padx=20, pady=16)
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        header_frame.columnconfigure(0, weight=1)

        title_label = tk.Label(
            header_frame,
            text="PDF Availability Report",
            font=("Segoe UI", 18, "bold"),
            fg="white",
            bg=self.BG_HEADER
        )
        title_label.pack(anchor="w")

        subtitle_label = tk.Label(
            header_frame,
            text=f"Scanning: {self.input_dir.name}",
            font=("Segoe UI", 10),
            fg="#94a3b8",
            bg=self.BG_HEADER
        )
        subtitle_label.pack(anchor="w", pady=(2, 0))

        filter_card = tk.Frame(container, bg=self.BG_CARD, relief="solid", borderwidth=1, padx=16, pady=16)
        filter_card.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        self._build_filter_panel(filter_card)

        self.summary_card = tk.Frame(container, bg="#e0f2fe", relief="solid", borderwidth=1, padx=16, pady=12)
        self.summary_card.grid(row=2, column=0, sticky="ew", pady=(0, 16))
        self.summary_var = tk.StringVar(value="Loading...")
        summary_label = tk.Label(
            self.summary_card,
            textvariable=self.summary_var,
            font=("Segoe UI", 11, "bold"),
            bg="#e0f2fe",
            fg="#0c4a6e",
            anchor="w"
        )
        summary_label.pack(fill="x")

        matrix_card = tk.Frame(container, bg=self.BG_CARD, relief="solid", borderwidth=1)
        matrix_card.grid(row=3, column=0, sticky="nsew", pady=(0, 16))
        matrix_card.columnconfigure(0, weight=1)
        matrix_card.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(matrix_card, bg="#ffffff", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        h_scroll = ttk.Scrollbar(matrix_card, orient="horizontal", command=self.canvas.xview)
        h_scroll.grid(row=1, column=0, sticky="ew")
        v_scroll = ttk.Scrollbar(matrix_card, orient="vertical", command=self.canvas.yview)
        v_scroll.grid(row=0, column=1, sticky="ns")

        self.canvas.configure(xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)

        self.matrix_container = tk.Frame(self.canvas, bg="#ffffff")
        self.canvas_window = self.canvas.create_window((0, 0), window=self.matrix_container, anchor="nw")

        self.matrix_container.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self._on_canvas_resize())

        self._build_buttons(container)

    def _on_canvas_resize(self) -> None:
        pass

    def _build_filter_panel(self, parent: tk.Frame) -> None:
        filter_label = tk.Label(
            parent,
            text="Filters",
            font=("Segoe UI", 12, "bold"),
            fg=self.TEXT_PRIMARY,
            bg=self.BG_CARD
        )
        filter_label.grid(row=0, column=0, columnspan=8, sticky="w", pady=(0, 12))

        filters_frame = tk.Frame(parent, bg=self.BG_CARD)
        filters_frame.grid(row=1, column=0, columnspan=8, sticky="w")
        self.filter_combos = {}

        filter_specs = [
            ("Year:", "year_var", 12),
            ("Subject:", "subject_var", 20),
            ("Syllabus:", "syllabus_var", 14),
            ("Status:", "status_var", 14),
        ]

        for i, (label_text, var_name, width) in enumerate(filter_specs):
            tk.Label(
                filters_frame,
                text=label_text,
                font=("Segoe UI", 9, "bold"),
                fg=self.TEXT_MUTED,
                bg=self.BG_CARD
            ).grid(row=0, column=i*2, sticky="w", padx=(0, 5))

            var = tk.StringVar(value="All")
            setattr(self, var_name, var)

            values = ["All"]
            if label_text == "Year:":
                values = ["All"] + sorted(set(r.year for r in self.results), reverse=True)
            elif label_text == "Subject:":
                def is_bad_subject_static(subj: str) -> bool:
                    if subj.lower() in {"unknown", "jun", "nov", "mar", "s", "w", "m", "a"}:
                        return True
                    if len(subj) <= 2:
                        return True
                    if len(subj) <= 4 and subj.isupper():
                        return True
                    if re.search(r'[bcdfghjklmnpqrstvwxz]{5,}', subj.lower()):
                        return True
                    if subj in {"Pdf", "PDF", "Pre-U", "Pre U"}:
                        return True
                    return False
                filtered_subjects = [s for s in set(r.subject for r in self.results)
                                   if not is_bad_subject_static(s)]
                values = ["All"] + sorted(filtered_subjects)
            elif label_text == "Syllabus:":
                values = ["All"] + sorted(set(r.syllabus for r in self.results))

            combo = ttk.Combobox(
                filters_frame,
                textvariable=var,
                values=values,
                state="readonly",
                width=width
            )
            combo.grid(row=0, column=i*2+1, sticky="w", padx=(0, 20))
            combo.bind("<<ComboboxSelected>>", lambda e: self._apply_filters())
            self.filter_combos[var_name] = combo

        self.year_var = getattr(self, 'year_var')
        self.subject_var = getattr(self, 'subject_var')
        self.syllabus_var = getattr(self, 'syllabus_var')
        self.status_var = getattr(self, 'status_var')

        self.status_var = tk.StringVar(value="All")
        status_combo = ttk.Combobox(
            filters_frame,
            textvariable=self.status_var,
            values=["All", "Complete", "Missing MS", "Missing QP", "No QP/MS"],
            state="readonly",
            width=14
        )
        status_combo.grid(row=0, column=7, sticky="w", padx=(0, 0))
        status_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_filters())
        self.filter_combos["status_var"] = status_combo

    @staticmethod
    def _is_bad_subject_label(subj: str) -> bool:
        if subj.lower() in {"unknown", "jun", "nov", "mar", "s", "w", "m", "a"}:
            return True
        if len(subj) <= 2:
            return True
        if len(subj) <= 4 and subj.isupper():
            return True
        if re.search(r'[bcdfghjklmnpqrstvwxz]{5,}', subj.lower()):
            return True
        if subj in {"Pdf", "PDF", "Pre-U", "Pre U"}:
            return True
        return False

    def _update_filter_values(self) -> None:
        if not hasattr(self, "filter_combos"):
            return

        filter_values = {
            "year_var": ["All"] + sort_year_values(set(r.year for r in self.results)),
            "subject_var": ["All"] + sorted(
                s for s in set(r.subject for r in self.results)
                if not self._is_bad_subject_label(s)
            ),
            "syllabus_var": ["All"] + sorted(set(r.syllabus for r in self.results)),
            "status_var": ["All", "Complete", "Missing MS", "Missing QP", "No QP/MS"],
        }
        for var_name, values in filter_values.items():
            combo = self.filter_combos.get(var_name)
            if combo is not None:
                combo.configure(values=values)

    def _build_buttons(self, parent: tk.Frame) -> None:
        buttons_frame = tk.Frame(parent, bg=self.BG_MAIN)
        buttons_frame.grid(row=4, column=0, sticky="ew")
        buttons_frame.columnconfigure(0, weight=1)

        btn_frame = tk.Frame(buttons_frame, bg=self.BG_MAIN)
        btn_frame.pack(side="left")

        export_btn = self._create_modern_button(
            btn_frame,
            "Export CSV",
            self._export_csv,
            "#059669"
        )
        export_btn.pack(side="left", padx=(0, 10))

        self.review_count_var = tk.StringVar(value=f"Review ({len(self.review_items)})")
        self.review_button = self._create_modern_button(
            btn_frame,
            self.review_count_var,
            self._show_review_window,
            self.ACCENT if self.review_items else "#94a3b8"
        )
        self.review_button.pack(side="left", padx=(0, 10))
        if not self.review_items:
            self.review_button.configure(state="disabled")

        refresh_btn = self._create_modern_button(
            btn_frame,
            "Refresh",
            self._refresh_data,
            "#64748b"
        )
        refresh_btn.pack(side="left", padx=(0, 10))

        close_btn = self._create_modern_button(
            btn_frame,
            "Close",
            self.window.destroy,
            "#94a3b8"
        )
        close_btn.pack(side="left")

    def _create_modern_button(self, parent: tk.Frame, text, command, bg_color) -> tk.Button:
        if isinstance(text, tk.StringVar):
            text_var = text
        else:
            text_var = tk.StringVar(value=text)

        btn = tk.Button(
            parent,
            textvariable=text_var,
            command=command,
            font=("Segoe UI", 9, "bold"),
            fg="white",
            bg=bg_color,
            activebackground=bg_color,
            activeforeground="white",
            relief="flat",
            padx=16,
            pady=8,
            cursor="hand2"
        )
        return btn

    def _apply_filters(self) -> None:
        year = self.year_var.get()
        subject = self.subject_var.get()
        syllabus = self.syllabus_var.get()
        status = self.status_var.get()

        def is_bad_subject(subj: str) -> bool:
            if subj.lower() in {"unknown", "jun", "nov", "mar", "s", "w", "m", "a"}:
                return True
            if len(subj) <= 2:
                return True
            if len(subj) <= 4 and subj.isupper():
                return True
            if re.search(r'[bcdfghjklmnpqrstvwxz]{5,}', subj.lower()):
                return True
            if subj in {"Pdf", "PDF", "Pre-U", "Pre U"}:
                return True
            return False

        self.filtered_results = [
            r for r in self.results
            if (year == "All" or r.year == year)
            and (subject == "All" or r.subject == subject)
            and (syllabus == "All" or r.syllabus == syllabus)
            and (status == "All" or r.status == status)
            and not self._is_bad_subject_label(r.subject)
        ]

        self._populate_matrix()

    def _get_row_key(self, r: PaperStatus) -> str:
        parts = r.paper_key.split("-")
        code = None
        for p in parts:
            if re.match(r"^[0479]\d{3}$", p):
                code = p
                break
        if code:
            return f"{r.subject} - {r.syllabus} - {code}"
        return f"{r.subject} - {r.syllabus}"

    def _populate_matrix(self) -> None:
        for widget in self.matrix_container.winfo_children():
            widget.destroy()

        from collections import defaultdict
        matrix = defaultdict(lambda: defaultdict(lambda: {"qp": False, "ms": False, "papers": []}))
        unknown_year_papers: list[PaperStatus] = []

        for r in self.filtered_results:
            if r.year == "unknown":
                unknown_year_papers.append(r)
                continue
            session = r.session
            year_session = f"{r.year}-{session}"
            row_key = self._get_row_key(r)

            matrix[row_key][year_session]["qp"] = matrix[row_key][year_session]["qp"] or r.has_qp
            matrix[row_key][year_session]["ms"] = matrix[row_key][year_session]["ms"] or r.has_ms
            matrix[row_key][year_session]["papers"].append(r)

        subjects = sorted(matrix.keys())
        sessions = sorted(
            set(sess for subj in matrix.values() for sess in subj.keys()),
            key=lambda s: (-int(s.split("-")[0]) if s.split("-")[0].isdigit() else 0, s)
        )

        MAX_MATRIX_ROWS = 150
        if len(subjects) > MAX_MATRIX_ROWS:
            subjects = subjects[:MAX_MATRIX_ROWS]

        if not subjects or not sessions:
            no_data = tk.Label(
                self.matrix_container,
                text="No papers found",
                font=("Segoe UI", 14),
                bg="#ffffff",
                fg=self.TEXT_MUTED
            )
            no_data.pack(padx=40, pady=40)
            if unknown_year_papers:
                self.summary_var.set(f"No year-qualified papers found  |  {len(unknown_year_papers)} unknown-year files excluded from matrix")
            else:
                self.summary_var.set("No papers found")
            return

        header_bg = self.BG_HEADER
        header_fg = "white"
        cell_font = ("Segoe UI", 10)

        header_label = tk.Label(
            self.matrix_container,
            text="Subject",
            font=("Segoe UI", 10, "bold"),
            bg=header_bg,
            fg=header_fg,
            padx=12,
            pady=10
        )
        header_label.grid(row=0, column=0, sticky="nsew")

        for col, session in enumerate(sessions, start=1):
            header = tk.Label(
                self.matrix_container,
                text=session,
                font=("Segoe UI", 9, "bold"),
                bg=header_bg,
                fg=header_fg,
                padx=8,
                pady=10
            )
            header.grid(row=0, column=col, sticky="nsew")

        for row, subject in enumerate(subjects, start=1):
            row_bg = "#f8fafc" if row % 2 == 0 else "#ffffff"
            subject_label = tk.Label(
                self.matrix_container,
                text=subject,
                font=cell_font,
                bg=row_bg,
                fg=self.TEXT_PRIMARY,
                padx=12,
                pady=8,
                anchor="w"
            )
            subject_label.grid(row=row, column=0, sticky="nsew")

            for col, session in enumerate(sessions, start=1):
                cell_data = matrix[subject][session]
                has_qp = cell_data["qp"]
                has_ms = cell_data["ms"]
                papers = cell_data["papers"]

                if has_qp and has_ms:
                    bg = self.COMPLETE_BG
                    text = "Complete"
                    fg = self.SUCCESS
                elif has_qp or has_ms:
                    bg = self.PARTIAL_BG
                    text = "Partial"
                    fg = self.WARNING
                else:
                    bg = self.MISSING_BG
                    text = "Missing"
                    fg = self.DANGER

                btn = tk.Button(
                    self.matrix_container,
                    text=text,
                    bg=bg,
                    fg=fg,
                    font=("Segoe UI", 8, "bold"),
                    relief="flat",
                    borderwidth=0,
                    cursor="hand2",
                    activebackground=bg,
                    activeforeground=fg,
                    padx=8,
                    pady=6,
                    command=lambda s=subject, sess=session, p=papers: self._on_cell_click(s, sess, p)
                )
                btn.grid(row=row, column=col, sticky="nsew", padx=1, pady=1)

        complete = sum(1 for r in self.filtered_results if r.has_qp and r.has_ms)
        missing_ms = sum(1 for r in self.filtered_results if r.has_qp and not r.has_ms)
        missing_qp = sum(1 for r in self.filtered_results if not r.has_qp and r.has_ms)
        review_text = f"  |  {len(self.review_items)} files need review" if self.review_items else ""
        unknown_text = (
            f"  |  {len(unknown_year_papers)} unknown-year files excluded from matrix"
            if unknown_year_papers
            else ""
        )

        self.summary_var.set(
            f"{len(self.filtered_results)} papers  |  {complete} Complete  |  {missing_ms} Missing MS  |  {missing_qp} Missing QP{review_text}{unknown_text}"
        )

        self.canvas.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_cell_click(self, subject: str, session: str, papers: list[PaperStatus]) -> None:
        detail_window = tk.Toplevel(self.window)
        detail_window.title(f"{subject} - {session}")
        detail_window.geometry("1000x550")
        detail_window.configure(bg=self.BG_MAIN)

        container = tk.Frame(detail_window, bg=self.BG_MAIN, padx=24, pady=24)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        header_frame = tk.Frame(container, bg=self.BG_HEADER, padx=16, pady=12)
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 16))

        tk.Label(
            header_frame,
            text=f"{subject} - {session}",
            font=("Segoe UI", 14, "bold"),
            fg="white",
            bg=self.BG_HEADER
        ).pack(anchor="w")

        tree_frame = tk.Frame(container, bg=self.BG_CARD, relief="solid", borderwidth=1)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        style = ttk.Style()
        style.configure("Modern.Treeview", background=self.BG_CARD, fieldbackground=self.BG_CARD, rowheight=28)
        style.configure("Modern.Treeview.Heading", font=("Segoe UI", 9, "bold"))

        columns = ("paper", "qp", "ms", "er", "in", "transcript", "status")
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=15, style="Modern.Treeview")

        tree.heading("paper", text="Paper Key")
        tree.heading("qp", text="QP")
        tree.heading("ms", text="MS")
        tree.heading("er", text="ER")
        tree.heading("in", text="IN")
        tree.heading("transcript", text="TR")
        tree.heading("status", text="Status")

        tree.column("paper", width=350)
        tree.column("qp", width=50)
        tree.column("ms", width=50)
        tree.column("er", width=50)
        tree.column("in", width=50)
        tree.column("transcript", width=50)
        tree.column("status", width=120)

        if papers:
            for paper in papers:
                tag = "complete" if paper.has_qp and paper.has_ms else "incomplete"
                values = (
                    paper.paper_key,
                    "✓" if paper.has_qp else "✗",
                    "✓" if paper.has_ms else "✗",
                    "✓" if paper.has_er else "-",
                    "✓" if paper.has_in else "-",
                    "✓" if paper.has_transcript else "-",
                    paper.status
                )
                tree.insert("", "end", values=values, tags=(tag,))

        tree.tag_configure("complete", foreground=self.SUCCESS)
        tree.tag_configure("incomplete", foreground=self.DANGER)

        tree.grid(row=0, column=0, sticky="nsew")

        v_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        v_scroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=v_scroll.set)

        buttons_frame = tk.Frame(container, bg=self.BG_MAIN)
        buttons_frame.grid(row=2, column=0, sticky="ew", pady=(16, 0))

        self._create_modern_button(
            buttons_frame,
            "Upload Missing Files",
            lambda: self._upload_files(subject, session, papers, detail_window),
            self.ACCENT
        ).pack(side="left", padx=(0, 10))

        self._create_modern_button(
            buttons_frame,
            "Download Missing Files",
            lambda: self._download_files(subject, session, papers, detail_window),
            self.ACCENT
        ).pack(side="left", padx=(0, 10))

        self._create_modern_button(
            buttons_frame,
            "Close",
            detail_window.destroy,
            "#94a3b8"
        ).pack(side="left")

    def _upload_files(self, subject: str, session: str, papers: list[PaperStatus], parent_window: tk.Toplevel) -> None:
        upload_window = tk.Toplevel(parent_window)
        upload_window.title("Upload Missing Files")
        upload_window.geometry("600x450")
        upload_window.configure(bg=self.BG_MAIN)

        container = tk.Frame(upload_window, bg=self.BG_MAIN, padx=24, pady=24)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)

        header_frame = tk.Frame(container, bg=self.BG_HEADER, padx=16, pady=12)
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 16))

        tk.Label(
            header_frame,
            text="Upload Missing Files",
            font=("Segoe UI", 14, "bold"),
            fg="white",
            bg=self.BG_HEADER
        ).pack(anchor="w")

        missing = []
        for paper in papers:
            if not paper.has_qp:
                missing.append(f"{paper.paper_key} (Missing QP)")
            if not paper.has_ms:
                missing.append(f"{paper.paper_key} (Missing MS)")

        message = (
            f"No known paper entries found for {subject} {session}. "
            "You can still upload PDFs to the scanned folder and rescan."
            if not papers
            else "No missing files detected. You can still upload additional PDFs if needed."
        )

        tk.Label(
            container,
            text=message,
            font=("Segoe UI", 9),
            fg=self.TEXT_MUTED,
            bg=self.BG_MAIN,
            wraplength=500,
            justify="left"
        ).grid(row=1, column=0, sticky="w", pady=(0, 12))

        listbox_frame = tk.Frame(container, bg=self.BG_CARD, relief="solid", borderwidth=1)
        listbox_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 16))

        listbox = tk.Listbox(listbox_frame, height=12, font=("Segoe UI", 9))
        listbox.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        v_scroll = ttk.Scrollbar(listbox_frame, orient="vertical", command=listbox.yview)
        v_scroll.pack(side="right", fill="y")
        listbox.configure(yscrollcommand=v_scroll.set)

        if missing:
            for item in missing:
                listbox.insert("end", item)
        else:
            listbox.insert("end", f"{subject} / {session} - upload PDFs here")

        buttons_frame = tk.Frame(container, bg=self.BG_MAIN)
        buttons_frame.grid(row=3, column=0, sticky="ew")

        self._create_modern_button(
            buttons_frame,
            "Browse Files",
            lambda: self._browse_upload(papers, upload_window),
            self.ACCENT
        ).pack(side="left", padx=(0, 10))

        self._create_modern_button(
            buttons_frame,
            "Close",
            upload_window.destroy,
            "#94a3b8"
        ).pack(side="left")

    def _browse_upload(self, papers: list[PaperStatus], parent_window: tk.Toplevel) -> None:
        files = filedialog.askopenfilenames(
            title="Select PDF files to upload",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            parent=parent_window
        )

        if not files:
            return

        uploaded = 0
        errors = []

        for file_path in files:
            try:
                src = Path(file_path)
                dest = self.input_dir / src.name

                if dest.exists():
                    if not messagebox.askyesno("File Exists", f"{src.name} already exists. Replace it?", parent=parent_window):
                        continue

                shutil.copy2(src, dest)
                uploaded += 1
            except Exception as e:
                errors.append(f"{src.name}: {str(e)}")

        if uploaded > 0:
            messagebox.showinfo("Upload Complete", f"Uploaded {uploaded} file(s) successfully.", parent=parent_window)
            parent_window.destroy()
            self._refresh_data()

        if errors:
            messagebox.showerror("Upload Errors", "\n".join(errors), parent=parent_window)

    def _download_files(self, subject: str, session: str, papers: list[PaperStatus], parent_window: tk.Toplevel) -> None:
        download_window = tk.Toplevel(parent_window)
        download_window.title("Download Missing Files")
        download_window.geometry("650x450")
        download_window.configure(bg=self.BG_MAIN)

        container = tk.Frame(download_window, bg=self.BG_MAIN, padx=24, pady=24)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)

        header_frame = tk.Frame(container, bg=self.BG_HEADER, padx=16, pady=12)
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 16))

        tk.Label(
            header_frame,
            text="Download Missing Files",
            font=("Segoe UI", 14, "bold"),
            fg="white",
            bg=self.BG_HEADER
        ).pack(anchor="w")

        tk.Label(
            container,
            text=f"Subject: {subject} | Session: {session}",
            font=("Segoe UI", 10, "bold"),
            fg=self.TEXT_PRIMARY,
            bg=self.BG_MAIN
        ).grid(row=1, column=0, sticky="w", pady=(0, 8))

        missing_papers = []
        for paper in papers:
            if not paper.has_qp:
                missing_papers.append(("qp", paper.paper_key))
            if not paper.has_ms:
                missing_papers.append(("ms", paper.paper_key))

        if missing_papers:
            tk.Label(
                container,
                text=f"Missing {len(missing_papers)} file(s). Select papers to search for:",
                font=("Segoe UI", 9),
                fg=self.TEXT_MUTED,
                bg=self.BG_MAIN
            ).grid(row=2, column=0, sticky="w", pady=(0, 8))

            list_frame = tk.Frame(container, bg=self.BG_CARD, relief="solid", borderwidth=1)
            list_frame.grid(row=3, column=0, sticky="nsew", pady=(0, 12))

            canvas = tk.Canvas(list_frame, bg=self.BG_CARD, highlightthickness=0)
            scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
            check_frame = tk.Frame(canvas, bg=self.BG_CARD)

            canvas.configure(yscrollcommand=scrollbar.set)
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

            canvas_window = canvas.create_window((0, 0), window=check_frame, anchor="nw")

            def on_frame_configure(e):
                canvas.configure(scrollregion=canvas.bbox("all"))

            check_frame.bind("<Configure>", on_frame_configure)

            var_qp = tk.BooleanVar(value=True)
            var_ms = tk.BooleanVar(value=True)

            tk.Label(
                check_frame,
                text="Select paper patterns to search for:",
                font=("Segoe UI", 9, "bold"),
                fg=self.TEXT_PRIMARY,
                bg=self.BG_CARD
            ).pack(anchor="w", padx=10, pady=(8, 4))

            for ptype, key in missing_papers:
                cb = tk.Checkbutton(
                    check_frame,
                    text=f"[{ptype.upper()}] {key}",
                    variable=var_qp if ptype == "qp" else var_ms,
                    font=("Segoe UI", 9),
                    fg=self.TEXT_PRIMARY,
                    bg=self.BG_CARD,
                    anchor="w"
                )
                cb.pack(anchor="w", padx=20)

            container.rowconfigure(3, weight=1)
        else:
            tk.Label(
                container,
                text="No missing files detected.",
                font=("Segoe UI", 9),
                fg=self.TEXT_MUTED,
                bg=self.BG_MAIN
            ).grid(row=2, column=0, sticky="w", pady=(0, 12))

        tk.Label(
            container,
            text="Enter the URL of a page containing exam paper links:",
            font=("Segoe UI", 9),
            fg=self.TEXT_MUTED,
            bg=self.BG_MAIN
        ).grid(row=4, column=0, sticky="w", pady=(0, 8))

        url_frame = tk.Frame(container, bg=self.BG_CARD, relief="solid", borderwidth=1)
        url_frame.grid(row=5, column=0, sticky="ew", pady=(0, 16))

        url_var = tk.StringVar()
        url_entry = tk.Entry(
            url_frame,
            textvariable=url_var,
            font=("Segoe UI", 11),
            bg=self.BG_CARD,
            fg=self.TEXT_PRIMARY,
            relief="flat",
            insertbackground=self.TEXT_PRIMARY
        )
        url_entry.pack(fill="x", padx=12, pady=10)

        buttons_frame = tk.Frame(container, bg=self.BG_MAIN)
        buttons_frame.grid(row=6, column=0, sticky="ew")

        self._create_modern_button(
            buttons_frame,
            "Search & Download",
            lambda: self._scrape_url(url_var.get(), subject, missing_papers, download_window, papers),
            self.ACCENT
        ).pack(side="left", padx=(0, 10))

        self._create_modern_button(
            buttons_frame,
            "Close",
            download_window.destroy,
            "#94a3b8"
        ).pack(side="left")

    def _scrape_url(self, url: str, subject: str, missing_papers: list = None, parent_window: tk.Toplevel = None, papers: list = None) -> None:
        if not url or not url.strip():
            messagebox.showwarning("URL Required", "Please enter a URL.", parent=parent_window)
            return

        url = url.strip()

        progress_window = tk.Toplevel(parent_window)
        progress_window.title("Downloading...")
        progress_window.geometry("500x350")
        progress_window.configure(bg=self.BG_MAIN)
        progress_window.transient(parent_window)

        container = tk.Frame(progress_window, bg=self.BG_MAIN, padx=24, pady=24)
        container.pack(fill="both", expand=True)

        tk.Label(
            container,
            text="Searching and downloading...",
            font=("Segoe UI", 11),
            fg=self.TEXT_PRIMARY,
            bg=self.BG_MAIN
        ).pack(pady=(0, 12))

        log_text = tk.Text(
            container,
            height=12,
            font=("Consolas", 9),
            bg=self.BG_CARD,
            fg=self.TEXT_PRIMARY,
            relief="flat",
            state="disabled",
            wrap="none"
        )
        log_text.pack(fill="both", expand=True)

        log_queue = []
        log_lock = threading.Lock()

        def process_log_queue():
            while True:
                with log_lock:
                    if log_queue:
                        msg = log_queue.pop(0)
                    else:
                        break
                log_text.configure(state="normal")
                log_text.insert("end", msg + "\n")
                log_text.see("end")
                log_text.configure(state="disabled")
            log_text.after(100, process_log_queue)

        def log(msg):
            with log_lock:
                log_queue.append(msg)

        def do_scrape():
            try:
                from src.pdf_scraper import scrape_pdfs, scrape_for_specific_files, scrape_all_subjects_from_url
                import os
                from pathlib import Path

                output_dir = str(self.input_dir)

                if papers:
                    for p in papers:
                        if p.qp_path and p.qp_path != "-":
                            paper_path = Path(p.qp_path)
                            if paper_path.parent.exists() and "past-papers" in str(paper_path):
                                output_dir = str(paper_path.parent)
                                break
                        elif p.ms_path and p.ms_path != "-":
                            paper_path = Path(p.ms_path)
                            if paper_path.parent.exists() and "past-papers" in str(paper_path):
                                output_dir = str(paper_path.parent)
                                break

                log(f"Subject: {subject}")
                log(f"Output: {output_dir}")
                log(f"URL: {url}")
                log("")

                if missing_papers:
                    patterns = []
                    for ptype, key in missing_papers:
                        parts = key.split("-")
                        if len(parts) >= 4:
                            code = parts[3]
                            session_part = parts[1][:2]
                            patterns.append(f"{code}_{session_part}*")

                    unique_patterns = list(set(patterns))
                    log(f"Searching for {len(unique_patterns)} paper patterns...")
                    log(f"Patterns: {unique_patterns}")
                    log("")

                    results = scrape_for_specific_files(url, output_dir, unique_patterns)

                    log("")
                    log("=== RESULTS ===")
                    log(f"Downloaded: {results['downloaded']}")
                    log(f"Skipped: {results['skipped']}")
                    if results['not_found']:
                        log(f"Not found on page: {results['not_found']}")
                    if results['errors']:
                        log(f"Errors: {results['errors'][:3]}")
                else:
                    log("Auto-discovering all subjects from URL...")

                    def scrape_logger(msg):
                        log(msg)

                    results = scrape_all_subjects_from_url(url, output_dir, logger=scrape_logger)
                    log("")
                    log("=== RESULTS ===")
                    for subj, res in sorted(results.items()):
                        if "downloaded" in res:
                            log(f"{subj}: {res['downloaded']} files")
                        elif "error" in res:
                            log(f"{subj}: ERROR - {res['error']}")

                progress_window.after(500, lambda: [
                    messagebox.showinfo("Download Complete", "Download process finished. Check log for details.", parent=parent_window),
                    progress_window.destroy(),
                    parent_window.destroy() if parent_window else None,
                    self._refresh_data()
                ])
            except Exception as e:
                import traceback
                log(f"Error: {str(e)}")
                log(traceback.format_exc())
                progress_window.after(500, lambda: [
                    messagebox.showerror("Download Failed", str(e), parent=parent_window),
                    progress_window.destroy()
                ])

        process_log_queue()
        threading.Thread(target=do_scrape, daemon=True).start()

    def _show_replace_dialog(self, paper: PaperStatus, parent_window: tk.Toplevel) -> None:
        replace_window = tk.Toplevel(parent_window)
        replace_window.title(f"Replace Files - {paper.paper_key}")
        replace_window.geometry("500x380")
        replace_window.configure(bg=self.BG_MAIN)

        container = tk.Frame(replace_window, bg=self.BG_MAIN, padx=24, pady=24)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)

        header_frame = tk.Frame(container, bg=self.BG_HEADER, padx=16, pady=12)
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 20))

        tk.Label(
            header_frame,
            text=f"Replace Files",
            font=("Segoe UI", 14, "bold"),
            fg="white",
            bg=self.BG_HEADER
        ).pack(anchor="w")

        tk.Label(
            container,
            text=f"Paper: {paper.paper_key}",
            font=("Segoe UI", 10),
            fg=self.TEXT_PRIMARY,
            bg=self.BG_MAIN
        ).grid(row=1, column=0, sticky="w", pady=(0, 16))

        file_types = []
        if paper.has_qp:
            file_types.append(("Question Paper", "qp", self.SUCCESS))
        if paper.has_ms:
            file_types.append(("Mark Scheme", "ms", self.SUCCESS))
        if paper.has_er:
            file_types.append(("Examiner Report", "er", self.SUCCESS))
        if paper.has_in:
            file_types.append(("Insert", "in", self.SUCCESS))
        if paper.has_transcript:
            file_types.append(("Transcript", "transcript", self.SUCCESS))

        for i, (label, file_type, color) in enumerate(file_types):
            row = i + 2
            file_frame = tk.Frame(container, bg=self.BG_CARD, relief="solid", borderwidth=1, padx=12, pady=10)
            file_frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))

            tk.Label(
                file_frame,
                text=label,
                font=("Segoe UI", 9),
                fg=self.TEXT_PRIMARY,
                bg=self.BG_CARD
            ).pack(side="left", padx=(0, 10))

            self._create_modern_button(
                file_frame,
                "Replace",
                lambda ft=file_type: self._replace_file(paper, ft, replace_window),
                color
            ).pack(side="right")

        buttons_frame = tk.Frame(container, bg=self.BG_MAIN)
        buttons_frame.grid(row=len(file_types) + 3, column=0, sticky="ew", pady=(16, 0))

        self._create_modern_button(
            buttons_frame,
            "Close",
            replace_window.destroy,
            "#94a3b8"
        ).pack(side="left")

    def _replace_file(self, paper: PaperStatus, file_type: str, parent_window: tk.Toplevel) -> None:
        file_path = filedialog.askopenfilename(
            title=f"Select new {file_type.upper()} file",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            parent=parent_window
        )

        if not file_path:
            return

        try:
            src = Path(file_path)
            if file_type == "qp":
                dest_path = paper.qp_path
            elif file_type == "ms":
                dest_path = paper.ms_path
            elif file_type == "er":
                dest_path = paper.er_path
            elif file_type == "in":
                dest_path = paper.in_path
            elif file_type == "transcript":
                dest_path = paper.transcript_path
            else:
                return

            dest = Path(dest_path)

            if not messagebox.askyesno("Confirm Replace", f"Replace {dest.name} with {src.name}?", parent=parent_window):
                return

            shutil.copy2(src, dest)
            messagebox.showinfo("Success", f"Replaced {dest.name} successfully.", parent=parent_window)
            parent_window.destroy()
            self._refresh_data()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to replace file: {str(e)}", parent=parent_window)

    def _refresh_data(self) -> None:
        report = scan_pdf_directory_report(self.input_dir)
        self.apply_report(report)

    def apply_report(self, report: AvailabilityScanReport | list[PaperStatus]) -> None:
        if isinstance(report, AvailabilityScanReport):
            self.results = report.papers
            self.review_items = report.review_items
        else:
            self.results = report
            self.review_items = []
        self.filtered_results = self.results

        self._update_filter_values()
        self.year_var.set("All")
        self.subject_var.set("All")
        self.syllabus_var.set("All")
        self.status_var.set("All")

        self.review_count_var.set(f"Review ({len(self.review_items)})")
        if self.review_items:
            self.review_button.configure(state="normal", bg=self.ACCENT)
        else:
            self.review_button.configure(state="disabled", bg="#94a3b8")

        self._apply_filters()

    def _show_review_window(self) -> None:
        review_window = tk.Toplevel(self.window)
        review_window.title("Filename Review")
        review_window.geometry("1100x600")
        review_window.configure(bg=self.BG_MAIN)
        review_window.minsize(900, 500)

        container = tk.Frame(review_window, bg=self.BG_MAIN, padx=24, pady=24)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        header_frame = tk.Frame(container, bg=self.BG_HEADER, padx=16, pady=12)
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 16))

        tk.Label(
            header_frame,
            text=f"Filename Review ({len(self.review_items)} files)",
            font=("Segoe UI", 14, "bold"),
            fg="white",
            bg=self.BG_HEADER
        ).pack(anchor="w")

        tree_frame = tk.Frame(container, bg=self.BG_CARD, relief="solid", borderwidth=1)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        columns = ("filename", "reason", "suggestion")
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=18)

        tree.heading("filename", text="Filename")
        tree.heading("reason", text="Reason")
        tree.heading("suggestion", text="Suggested Name")

        tree.column("filename", width=300)
        tree.column("reason", width=350)
        tree.column("suggestion", width=350)

        for item in self.review_items:
            tree.insert("", "end", values=(item.filename, item.reason, item.suggestion))

        tree.grid(row=0, column=0, sticky="nsew")

        v_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        v_scroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=v_scroll.set)

        buttons_frame = tk.Frame(container, bg=self.BG_MAIN)
        buttons_frame.grid(row=2, column=0, sticky="ew", pady=(16, 0))

        self._create_modern_button(
            buttons_frame,
            "Export CSV",
            self._export_review_csv,
            self.ACCENT
        ).pack(side="left", padx=(0, 10))

        self._create_modern_button(
            buttons_frame,
            "Close",
            review_window.destroy,
            "#94a3b8"
        ).pack(side="left")

    def _export_csv(self) -> None:
        output_path = self.input_dir / "availability_report.csv"
        export_to_csv(self.filtered_results, output_path)
        import os
        os.startfile(output_path)  # type: ignore[attr-defined]

    def _export_review_csv(self) -> None:
        output_path = self.input_dir / "filename_review.csv"
        export_review_to_csv(self.review_items, output_path)
        import os
        os.startfile(output_path)  # type: ignore[attr-defined]
