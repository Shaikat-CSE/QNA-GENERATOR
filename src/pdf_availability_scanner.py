from __future__ import annotations

import csv
import json
import re
import shutil
import tkinter as tk
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

BYTES_SUFFIX_RE = re.compile(r"-[\d,]+bytes$", re.IGNORECASE)
PDF_KIND_RE = re.compile(r"^(?P<stem>.+)-(?P<kind>qp|ms|er|in|transcript|sqp|sm|sp|prm|pm)$", re.IGNORECASE)
IB_PAPER_RE = re.compile(r"^(?P<stem>.+)-paper\d+-(?P<tz>tz\d+|n)-(?P<kind>qp|ms|er|in)$", re.IGNORECASE)
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
DEFAULT_FILENAME_ALIASES_FILE = CONFIG_DIR / "filename_aliases.json"
TOKEN_RE = re.compile(r"[a-z]+|\d+", re.IGNORECASE)
DEFAULT_FILENAME_ALIASES: dict[str, dict[str, list[str]]] = {
    "kind_aliases": {
        "qp": ["qp", "question paper", "questionpaper", "question-paper", "questions"],
        "ms": ["ms", "mark scheme", "markscheme", "mark-scheme", "marking scheme", "answers"],
        "er": ["er", "examiner report", "examiner-report", "examinerreport"],
        "in": ["in", "insert", "resource booklet"],
        "transcript": ["transcript", "listening transcript"],
        "sqp": ["sqp", "specimen question paper", "specimen paper", "specimen-qp"],
        "sm": ["sm", "specimen markscheme", "specimen-ms", "specimen mark scheme"],
        "sp": ["sp", "specimen"],
        "prm": ["prm", "pre-release material", "pre release", "pre_release"],
        "pm": ["pm", "pre-release"],
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

    @property
    def status(self) -> str:
        if self.has_qp and self.has_ms:
            return "Complete"
        elif self.has_qp:
            return "Missing MS"
        elif self.has_ms:
            return "Missing QP"
        return "No files"

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
                target[str(label)] = aliases
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


def canonicalize_key_tokens(tokens: tuple[str, ...], aliases: dict[str, dict[str, list[str]]]) -> tuple[str, ...]:
    tokens = replace_alias_tokens(tokens, aliases.get("session_aliases", {}))
    tokens = replace_alias_tokens(tokens, aliases.get("subject_aliases", {}))
    tokens = replace_alias_tokens(tokens, aliases.get("syllabus_aliases", {}))
    return tokens


def title_from_tokens(tokens: list[str]) -> str:
    return " ".join(token.upper() if len(token) <= 3 else token.title() for token in tokens)


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
    return stem if match else None


def classify_pdf_filename(
    path: Path,
    aliases: dict[str, dict[str, list[str]]],
) -> tuple[FilenameClassification | None, ReviewItem | None]:
    stem = BYTES_SUFFIX_RE.sub("", path.stem.lower())

    # Try IB pattern first (paper1-tz1-qp)
    ib_match = IB_PAPER_RE.match(stem)
    if ib_match:
        return (
            FilenameClassification(
                paper_key=ib_match.group("stem"),
                kind=ib_match.group("kind").lower(),
                source="strict",
            ),
            None,
        )

    # Try standard pattern (ends with -qp/-ms/-er/-in/-transcript)
    strict_match = PDF_KIND_RE.match(stem)
    if strict_match:
        return (
            FilenameClassification(
                paper_key=strict_match.group("stem"),
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
    key_tokens = canonicalize_key_tokens(remove_token_span(tokens, start, end), aliases)
    if not key_tokens:
        return (
            None,
            ReviewItem(
                filename=path.name,
                path=str(path),
                reason="Could not build a paper key after removing the paper type marker",
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


def scan_pdf_directory_report(input_dir: Path) -> AvailabilityScanReport:
    aliases = load_filename_aliases()
    grouped: dict[str, dict[str, list[Path]]] = defaultdict(lambda: defaultdict(list))
    review_items: list[ReviewItem] = []

    for path in sorted(input_dir.rglob("*.pdf")):
        # Skip resources folders - only scan past-papers
        if "resources" in path.parts or "past-papers" not in str(path):
            continue

        classification, review_item = classify_pdf_filename(path, aliases)
        if review_item is not None:
            review_items.append(review_item)
        if classification is None:
            continue
        grouped[classification.paper_key][classification.kind].append(path)

    results: list[PaperStatus] = []
    for paper_key in sorted(grouped):
        kinds = grouped[paper_key]
        year_match = re.match(r"^(19|20)\d{2}", paper_key)
        year = year_match.group(0) if year_match else "unknown"

        qp_paths = kinds.get("qp", [])
        ms_paths = kinds.get("ms", [])
        er_paths = kinds.get("er", [])
        in_paths = kinds.get("in", [])
        transcript_paths = kinds.get("transcript", [])

        preferred_qp = choose_preferred_path(qp_paths)
        preferred_ms = choose_preferred_path(ms_paths)
        preferred_er = choose_preferred_path(er_paths)
        preferred_in = choose_preferred_path(in_paths)
        preferred_transcript = choose_preferred_path(transcript_paths)

        subject, syllabus = extract_subject_syllabus(paper_key, aliases)

        results.append(
            PaperStatus(
                year=year,
                paper_key=paper_key,
                has_qp=len(qp_paths) > 0,
                has_ms=len(ms_paths) > 0,
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
        canvas_width = self.canvas.winfo_width()
        self.canvas.itemconfig(self.canvas_window, width=canvas_width)

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
                values = ["All"] + sorted(set(r.subject for r in self.results))
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

        self.year_var = getattr(self, 'year_var')
        self.subject_var = getattr(self, 'subject_var')
        self.syllabus_var = getattr(self, 'syllabus_var')
        self.status_var = getattr(self, 'status_var')

        self.status_var = tk.StringVar(value="All")
        status_combo = ttk.Combobox(
            filters_frame,
            textvariable=self.status_var,
            values=["All", "Complete", "Missing MS", "Missing QP"],
            state="readonly",
            width=14
        )
        status_combo.grid(row=0, column=7, sticky="w", padx=(0, 0))
        status_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_filters())

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

        self.filtered_results = [
            r for r in self.results
            if (year == "All" or r.year == year)
            and (subject == "All" or r.subject == subject)
            and (syllabus == "All" or r.syllabus == syllabus)
            and (status == "All" or r.status == status)
        ]

        self._populate_matrix()

    def _populate_matrix(self) -> None:
        for widget in self.matrix_container.winfo_children():
            widget.destroy()

        from collections import defaultdict
        matrix = defaultdict(lambda: defaultdict(lambda: {"qp": False, "ms": False, "papers": []}))

        for r in self.filtered_results:
            session_match = re.search(r"-([swm])-", r.paper_key)
            session = session_match.group(1).upper() if session_match else "?"
            year_session = f"{r.year}-{session}"

            matrix[r.subject][year_session]["qp"] = matrix[r.subject][year_session]["qp"] or r.has_qp
            matrix[r.subject][year_session]["ms"] = matrix[r.subject][year_session]["ms"] or r.has_ms
            matrix[r.subject][year_session]["papers"].append(r)

        subjects = sorted(matrix.keys())
        sessions = sorted(set(sess for subj in matrix.values() for sess in subj.keys()))

        if not subjects or not sessions:
            no_data = tk.Label(
                self.matrix_container,
                text="No papers found",
                font=("Segoe UI", 14),
                bg="#ffffff",
                fg=self.TEXT_MUTED
            )
            no_data.pack(padx=40, pady=40)
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

        self.summary_var.set(
            f"{len(self.filtered_results)} papers  |  {complete} Complete  |  {missing_ms} Missing MS  |  {missing_qp} Missing QP{review_text}"
        )

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

        buttons_frame = tk.Frame(container, bg=self.BG_MAIN, pady=(16, 0))
        buttons_frame.grid(row=2, column=0, sticky="ew")

        self._create_modern_button(
            buttons_frame,
            "Upload Missing Files",
            lambda: self._upload_files(subject, session, papers, detail_window),
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

        buttons_frame = tk.Frame(container, bg=self.BG_MAIN, pady=(16, 0))
        buttons_frame.grid(row=len(file_types) + 3, column=0, sticky="ew")

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
        self.results = report.papers
        self.review_items = report.review_items
        self.filtered_results = self.results

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

        buttons_frame = tk.Frame(container, bg=self.BG_MAIN, pady=(16, 0))
        buttons_frame.grid(row=2, column=0, sticky="ew")

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
