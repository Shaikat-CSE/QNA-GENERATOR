from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import fitz

try:
    from .minimax_client import MiniMaxClient, MiniMaxConfig
except ImportError:
    from minimax_client import MiniMaxClient, MiniMaxConfig

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:  # pragma: no cover - optional dependency
    RapidOCR = None

try:
    import numpy as np
except ImportError:  # pragma: no cover - optional dependency
    np = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover - optional dependency
    Image = None

try:
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover - optional dependency
    SentenceTransformer = None


DEFAULT_INPUT_DIR: Path | None = None
DEFAULT_OUTPUT_DIR = Path("generated_markdowns")
DEFAULT_TAXONOMY_FILE: Path | None = None
DEFAULT_ENV_FILE = Path(".env")
DEFAULT_STATE_FILE = Path(".qna_cli_state.json")
DEFAULT_PROFILE_FILE = Path("config/profiles/edexcel_generic.json")
DEFAULT_CLIP_MODEL = "clip-ViT-B-32"
PROFILES_DIR = Path("config/profiles")
DEFAULT_PROMPT_TOPIC_LIMIT = 10
MIN_PROMPT_SHORTLIST_SCORE = 8
DEFAULT_TAXONOMY_MODE = "auto"
DEFAULT_AUTO_TAXONOMY_FILENAME = "taxonomy.auto.json"
DEFAULT_AUTO_TAXONOMY_SAMPLE_LIMIT = 60
DEFAULT_AUTO_TAXONOMY_QUESTION_CHAR_LIMIT = 420
DEFAULT_AUTO_TAXONOMY_ANSWER_CHAR_LIMIT = 180
VISUAL_MERGE_GAP = 24.0
VISUAL_CLIP_PADDING = 18.0
VISUAL_HORIZONTAL_ATTACH_GAP = 180.0
VISUAL_VERTICAL_ATTACH_GAP = 18.0
VISUAL_CLUSTER_HORIZONTAL_GAP = 90.0
VISUAL_CLUSTER_VERTICAL_GAP = 90.0
VISUAL_CLUSTER_MIN_HEIGHT = 70.0
VISUAL_CLUSTER_MIN_WIDTH = 70.0
BYTES_SUFFIX_RE = re.compile(r"-[\d,]+bytes$", re.IGNORECASE)
PDF_KIND_RE = re.compile(r"^(?P<stem>.+)-(?P<kind>qp|ms)$", re.IGNORECASE)
QUESTION_START_RE = re.compile(r"^\s*(?P<number>\d{1,2})\s+(?P<rest>.+)$")
QUESTION_ID_RE = re.compile(r"^(?P<number>\d{1,2})\s*(?:\((?P<part>[a-z])\))?", re.IGNORECASE)
TOTAL_LINE_RE = re.compile(r"^\(Total for Question\s+\d+", re.IGNORECASE)
TOTAL_MARKS_LINE_RE = re.compile(r"^\(?Total\s+for\s+(?:Question|Paper)\b", re.IGNORECASE)
PAPER_REFERENCE_RE = re.compile(r"(?P<spec>[a-z0-9]+)-(?P<paper>\d{1,2})-[a-z0-9]+$", re.IGNORECASE)
SEARCH_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "against",
        "because",
        "before",
        "between",
        "could",
        "during",
        "each",
        "from",
        "into",
        "other",
        "their",
        "there",
        "these",
        "those",
        "through",
        "under",
        "which",
        "with",
        "would",
    }
)
NUMBER_WORDS_RE = r"(?:one|two|three|four|five|six|seven|eight|nine|ten)"
COMMAND_WORDS_RE = r"(?:State|Name|Give|Write|Identify|Complete|Describe|Explain|Justify|Compare|Calculate|Construct|Define|Suggest|Choose)"


@dataclass(frozen=True)
class PaperPair:
    key: str
    year: str
    question_pdf: Path
    mark_scheme_pdf: Path


@dataclass(frozen=True)
class ParserProfile:
    name: str
    description: str
    taxonomy_file: Path | None
    question_drop_patterns: tuple[re.Pattern[str], ...]
    mark_scheme_drop_patterns: tuple[re.Pattern[str], ...]
    skip_mark_scheme_headers: frozenset[str]
    paper_reference_suffixes: tuple[str, ...]


@dataclass(frozen=True)
class TopicMatch:
    chapter_id: str
    chapter_name: str
    topic_id: str
    topic_name: str
    confidence: float
    keywords: list[str]
    source: str
    rationale: str | None = None


@dataclass(frozen=True)
class QuestionRecord:
    question_number: int
    question_label: str
    question_text: str
    answer_text: str
    topic_match: TopicMatch | None
    llm_applied: bool
    content_blocks: tuple[dict[str, Any], ...] = ()
    assets: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class PendingVisualBlock:
    page_number: int
    bbox: tuple[float, float, float, float]
    png_bytes: bytes
    width: int
    height: int
    source_type: str
    asset_text: str = ""


@dataclass(frozen=True)
class ExtractedQuestionContent:
    question_number: int
    question_label: str
    question_text: str
    content_blocks: tuple[dict[str, Any], ...]
    assets: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RuntimeOptions:
    input_dir: Path
    output_dir: Path
    llm_mode: str
    profile_file: Path


@dataclass(frozen=True)
class ConversionSummary:
    input_dir: Path
    output_dir: Path
    processed_count: int
    generated_files: int
    manifest_path: Path
    topic_index_path: Path
    asset_manifest_path: Path
    validation_report_path: Path
    embedding_manifest_path: Path | None
    skipped_messages: list[str]


@dataclass(frozen=True)
class OcrResult:
    text: str
    lines: tuple[str, ...]
    avg_confidence: float
    detections: tuple[dict[str, Any], ...]


@dataclass
class MenuState:
    folders: list[str]
    llm_mode: str
    taxonomy_mode: str
    profile: str
    env_file: str
    limit: int | None
    paper_filter: str | None


ACTIVE_PROFILE: ParserProfile | None = None
FALLBACK_PROFILE_RAW = {
    "name": "Edexcel Generic",
    "description": "Generic Edexcel-style question paper and mark scheme parsing without subject taxonomy.",
    "taxonomy_file": None,
    "paper_reference_suffixes": ["b", "br"],
    "question_drop_patterns": [
        "^\\*P[0-9A-Z]+\\*$",
        "^\\d+\\s+\\*P[0-9A-Z]+\\*$",
        "^P[0-9A-Z]+$",
        "^\\d+$",
        "^Turn over$",
        "^Turn over\\s+\\*P[0-9A-Z]+\\*$",
        "^DO NOT WRITE IN THIS AREA.*$",
        "^Answer ALL questions\\.$",
        "^[A-Z0-9]+/[A-Z0-9]+",
    ],
    "mark_scheme_drop_patterns": [
        "^\\d+$",
        "^Question\\b.*$",
        "^Number\\b.*$",
        "^Answer$",
        "^Mark$",
        "^Additional guidance$",
        "^Additional$",
        "^guidance$",
    ],
    "skip_mark_scheme_headers": [
        "question",
        "number",
        "answer",
        "mark",
        "additional guidance",
        "additional",
        "guidance",
    ],
}


def resolve_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def compile_patterns(patterns: Iterable[str]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(str(pattern), re.IGNORECASE) for pattern in patterns)


def build_parser_profile(path: Path, raw: dict[str, Any]) -> ParserProfile:
    taxonomy_file_raw = raw.get("taxonomy_file")
    taxonomy_file: Path | None = None
    if taxonomy_file_raw:
        taxonomy_candidate = Path(str(taxonomy_file_raw))
        if not taxonomy_candidate.is_absolute():
            profile_relative_candidate = (path.parent / taxonomy_candidate).resolve()
            if profile_relative_candidate.exists():
                taxonomy_candidate = profile_relative_candidate
            else:
                taxonomy_candidate = resolve_path(taxonomy_candidate)
        taxonomy_file = taxonomy_candidate

    return ParserProfile(
        name=str(raw.get("name", path.stem)),
        description=str(raw.get("description", "")).strip(),
        taxonomy_file=taxonomy_file,
        question_drop_patterns=compile_patterns(raw.get("question_drop_patterns", [])),
        mark_scheme_drop_patterns=compile_patterns(raw.get("mark_scheme_drop_patterns", [])),
        skip_mark_scheme_headers=frozenset(
            str(item).strip().lower() for item in raw.get("skip_mark_scheme_headers", []) if str(item).strip()
        ),
        paper_reference_suffixes=tuple(
            str(item).strip().lower() for item in raw.get("paper_reference_suffixes", []) if str(item).strip()
        ),
    )


FALLBACK_PROFILE = build_parser_profile(DEFAULT_PROFILE_FILE.resolve(), FALLBACK_PROFILE_RAW)


def current_profile() -> ParserProfile:
    return ACTIVE_PROFILE or FALLBACK_PROFILE


def list_available_profile_files(profiles_dir: Path = PROFILES_DIR) -> list[Path]:
    resolved_dir = resolve_path(profiles_dir)
    if not resolved_dir.exists():
        return []
    return sorted(path.resolve() for path in resolved_dir.glob("*.json") if path.is_file())


def load_profile(path: Path) -> ParserProfile:
    resolved_path = resolve_path(path)
    if not resolved_path.exists():
        raise FileNotFoundError(f"Profile file does not exist: {resolved_path}")
    raw = json.loads(resolved_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Profile file must contain a JSON object: {resolved_path}")
    return build_parser_profile(resolved_path, raw)


def set_active_profile(profile: ParserProfile) -> None:
    global ACTIVE_PROFILE
    ACTIVE_PROFILE = profile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert paired exam question papers and mark schemes into per-question markdown files."
    )
    input_dir_help = "Directory containing PDF files. If omitted in a terminal, an interactive prompt is shown."
    if DEFAULT_INPUT_DIR is not None:
        input_dir_help += f" Suggested default: {DEFAULT_INPUT_DIR}"
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help=input_dir_help,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for generated markdown files. If omitted, a sibling folder named 'markdowns' is used next to the input folder.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N paired papers after sorting.",
    )
    parser.add_argument(
        "--paper-filter",
        type=str,
        default=None,
        help="Only process paired papers whose normalized key contains this text.",
    )
    parser.add_argument(
        "--llm-mode",
        choices=("off", "cleanup", "cleanup-and-tag"),
        default="off",
        help="Use MiniMax to clean markdown only, or to clean and infer topic/chapter tags.",
    )
    parser.add_argument(
        "--ocr-mode",
        choices=("off", "rapidocr"),
        default="rapidocr",
        help="OCR backend for extracting text inside saved question images.",
    )
    parser.add_argument(
        "--ocr-page-fallback",
        action="store_true",
        help="Use OCR on rendered pages when normal PDF text extraction is too weak.",
    )
    parser.add_argument(
        "--embedding-mode",
        choices=("off", "clip"),
        default="clip",
        help="Generate local embeddings for extracted assets.",
    )
    parser.add_argument(
        "--embedding-model",
        type=str,
        default=DEFAULT_CLIP_MODEL,
        help=f"SentenceTransformers multimodal model for embeddings. Default: {DEFAULT_CLIP_MODEL}",
    )
    parser.add_argument(
        "--llm-provider",
        choices=("minimax",),
        default="minimax",
        help="LLM provider for cleanup/tagging.",
    )
    parser.add_argument(
        "--profile-file",
        type=Path,
        default=DEFAULT_PROFILE_FILE,
        help=f"Parser profile JSON file. Default: {DEFAULT_PROFILE_FILE}",
    )
    parser.add_argument(
        "--taxonomy-file",
        type=Path,
        default=None,
        help="Optional taxonomy JSON override. In auto modes, a missing file can be created and then reused.",
    )
    parser.add_argument(
        "--taxonomy-mode",
        choices=("auto", "static", "auto-draft"),
        default=DEFAULT_TAXONOMY_MODE,
        help="Auto uses profile taxonomy, else saved taxonomy.auto.json, else generates one for tagged runs. Static only uses existing taxonomy. Auto-draft always targets a saved draft taxonomy file.",
    )
    parser.add_argument(
        "--minimax-api-key",
        type=str,
        default=None,
        help="Optional override for MINIMAX_API_KEY.",
    )
    parser.add_argument(
        "--minimax-base-url",
        type=str,
        default=None,
        help="Optional override for MINIMAX_BASE_URL.",
    )
    parser.add_argument(
        "--minimax-model",
        type=str,
        default=None,
        help="Optional override for MINIMAX_MODEL.",
    )
    parser.add_argument(
        "--api-timeout-ms",
        type=int,
        default=None,
        help="Optional HTTP timeout in milliseconds.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help=f"Optional .env file to load before resolving settings. Default: {DEFAULT_ENV_FILE}",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Show a simple terminal UI for folder input and run options.",
    )
    parser.add_argument(
        "--menu",
        action="store_true",
        help="Launch the full interactive CLI menu for managing multiple folders and running conversions.",
    )
    return parser.parse_args()


def normalize_unicode(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = (
        text.replace("\xa0", " ")
        .replace("\u2002", " ")
        .replace("\u2009", " ")
        .replace("\u202f", " ")
        .replace("\uf0b7", "•")
        .replace("\uf0a7", "•")
    )
    text = re.sub(r"[\ue000-\uf8ff]", " ", text)
    text = text.replace("\ufffc", " ").replace("\u02c7", "'")
    text = re.sub(rf"\b({COMMAND_WORDS_RE})(?={NUMBER_WORDS_RE}\b)", r"\1 ", text)
    text = re.sub(rf"\bto(?={NUMBER_WORDS_RE}\b)", "to ", text)
    text = re.sub(rf"\bthese(?={NUMBER_WORDS_RE}\b)", "these ", text, flags=re.IGNORECASE)
    text = re.sub(rf"\bthe(?={NUMBER_WORDS_RE}\b)", "the ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bin(?=Figure\s*\d+\b)", "in ", text)
    return text.rstrip()


def strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def is_tty_session() -> bool:
    return bool(getattr(sys.stdin, "isatty", lambda: False)()) and bool(getattr(sys.stdout, "isatty", lambda: False)())


def derive_default_output_dir(input_dir: Path) -> Path:
    return input_dir.parent / "markdowns"


def prompt_text(prompt: str, *, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    response = input(f"{prompt}{suffix}: ").strip()
    return response or (default or "")


def prompt_existing_folder(default: Path | None) -> Path:
    while True:
        raw = prompt_text("PDF folder path", default=str(default) if default else None)
        candidate = resolve_path(strip_wrapping_quotes(raw))
        if candidate.exists() and candidate.is_dir():
            return candidate
        print(f"Folder not found: {candidate}")


def prompt_llm_mode(default: str = "cleanup-and-tag") -> str:
    choices = {
        "1": "off",
        "2": "cleanup",
        "3": "cleanup-and-tag",
        "off": "off",
        "cleanup": "cleanup",
        "cleanup-and-tag": "cleanup-and-tag",
    }
    while True:
        response = prompt_text(
            "LLM mode 1=off 2=cleanup 3=cleanup-and-tag",
            default="3",
        ).lower()
        if response in choices:
            return choices[response]
        if response == "" and default:
            return default
        print("Enter 1, 2, 3, off, cleanup, or cleanup-and-tag.")


def prompt_taxonomy_mode(default: str = DEFAULT_TAXONOMY_MODE) -> str:
    choices = {
        "1": "auto",
        "2": "static",
        "3": "auto-draft",
        "auto": "auto",
        "static": "static",
        "auto-draft": "auto-draft",
    }
    while True:
        response = prompt_text(
            "Taxonomy mode 1=auto 2=static 3=auto-draft",
            default="3" if default == "auto-draft" else ("2" if default == "static" else "1"),
        ).lower()
        if response in choices:
            return choices[response]
        if response == "" and default:
            return default
        print("Enter 1, 2, 3, auto, static, or auto-draft.")


def prompt_profile_file(default: Path) -> Path:
    profiles = list_available_profile_files()
    default_path = resolve_path(default)
    if profiles:
        print("Available profiles")
        print("------------------")
        for index, path in enumerate(profiles, start=1):
            print(f"{index}. {path}")
        print("")

    while True:
        raw = prompt_text("Profile file path or number", default=str(default_path))
        if raw.isdigit() and profiles:
            index = int(raw)
            if 1 <= index <= len(profiles):
                return profiles[index - 1]
            print("Profile number out of range.")
            continue

        candidate = resolve_path(strip_wrapping_quotes(raw))
        if candidate.exists() and candidate.is_file():
            return candidate
        print(f"Profile file not found: {candidate}")


def load_menu_state(path: Path) -> MenuState:
    if not path.exists():
        return MenuState(
            folders=[],
            llm_mode="cleanup-and-tag",
            taxonomy_mode=DEFAULT_TAXONOMY_MODE,
            profile=str(DEFAULT_PROFILE_FILE),
            env_file=str(DEFAULT_ENV_FILE),
            limit=None,
            paper_filter=None,
        )

    raw = json.loads(path.read_text(encoding="utf-8"))
    folders = raw.get("folders")
    if not isinstance(folders, list):
        folders = []
    return MenuState(
        folders=[str(item) for item in folders],
        llm_mode=str(raw.get("llm_mode", "cleanup-and-tag")),
        taxonomy_mode=str(raw.get("taxonomy_mode", DEFAULT_TAXONOMY_MODE)),
        profile=str(raw.get("profile", str(DEFAULT_PROFILE_FILE))),
        env_file=str(raw.get("env_file", str(DEFAULT_ENV_FILE))),
        limit=raw.get("limit"),
        paper_filter=raw.get("paper_filter"),
    )


def save_menu_state(path: Path, state: MenuState) -> None:
    payload = {
        "folders": state.folders,
        "llm_mode": state.llm_mode,
        "taxonomy_mode": state.taxonomy_mode,
        "profile": state.profile,
        "env_file": state.env_file,
        "limit": state.limit,
        "paper_filter": state.paper_filter,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def pause(message: str = "Press Enter to continue") -> None:
    input(f"{message}...")


def parse_int_or_none(raw: str) -> int | None:
    raw = raw.strip()
    if not raw:
        return None
    return int(raw)


def print_menu(state: MenuState) -> None:
    clear_screen()
    print("QNA Generator CLI")
    print("=================")
    print("")
    print(f"Folders saved : {len(state.folders)}")
    print(f"Profile       : {state.profile}")
    print(f"LLM mode      : {state.llm_mode}")
    print(f"Taxonomy mode : {state.taxonomy_mode}")
    print(f"Env file      : {state.env_file}")
    print(f"Limit         : {state.limit if state.limit is not None else 'none'}")
    print(f"Paper filter  : {state.paper_filter if state.paper_filter else 'none'}")
    print("")
    if state.folders:
        print("Saved PDF folders")
        print("-----------------")
        for index, folder in enumerate(state.folders, start=1):
            folder_path = Path(folder)
            output_dir = derive_default_output_dir(folder_path)
            print(f"{index}. {folder_path}")
            print(f"   -> output: {output_dir}")
        print("")

    print("Actions")
    print("-------")
    print("1. Add PDF folder")
    print("2. Remove PDF folder")
    print("3. Set profile")
    print("4. Set taxonomy mode")
    print("5. Set LLM mode")
    print("6. Set paper filter")
    print("7. Set limit")
    print("8. Set env file")
    print("9. Run one folder")
    print("10. Run all folders")
    print("11. Show folder details")
    print("0. Exit")
    print("")


def prompt_menu_folder_index(state: MenuState, prompt_label: str) -> int | None:
    if not state.folders:
        print("No folders saved yet.")
        return None

    while True:
        raw = prompt_text(prompt_label)
        if not raw:
            return None
        try:
            index = int(raw)
        except ValueError:
            print("Enter a number from the folder list.")
            continue
        if 1 <= index <= len(state.folders):
            return index - 1
        print("Index out of range.")


def menu_add_folder(state: MenuState) -> MenuState:
    folder = prompt_existing_folder(DEFAULT_INPUT_DIR)
    normalized = str(folder.resolve())
    if normalized not in state.folders:
        state.folders.append(normalized)
        state.folders.sort()
        print(f"Added: {normalized}")
    else:
        print("Folder already exists in the list.")
    pause()
    return state


def menu_set_profile(state: MenuState) -> MenuState:
    state.profile = str(prompt_profile_file(Path(state.profile)))
    pause("Profile updated. Press Enter to continue")
    return state


def menu_set_taxonomy_mode(state: MenuState) -> MenuState:
    state.taxonomy_mode = prompt_taxonomy_mode(default=state.taxonomy_mode)
    pause("Taxonomy mode updated. Press Enter to continue")
    return state


def menu_remove_folder(state: MenuState) -> MenuState:
    index = prompt_menu_folder_index(state, "Folder number to remove")
    if index is None:
        pause()
        return state
    removed = state.folders.pop(index)
    print(f"Removed: {removed}")
    pause()
    return state


def menu_set_llm_mode(state: MenuState) -> MenuState:
    state.llm_mode = prompt_llm_mode(default=state.llm_mode)
    pause("LLM mode updated. Press Enter to continue")
    return state


def menu_set_paper_filter(state: MenuState) -> MenuState:
    value = prompt_text("Paper filter substring", default=state.paper_filter or "")
    state.paper_filter = value or None
    pause("Paper filter updated. Press Enter to continue")
    return state


def menu_set_limit(state: MenuState) -> MenuState:
    while True:
        raw = prompt_text("Limit per run (blank for none)", default=str(state.limit) if state.limit is not None else "")
        try:
            state.limit = parse_int_or_none(raw)
            break
        except ValueError:
            print("Enter a whole number or leave it blank.")
    pause("Limit updated. Press Enter to continue")
    return state


def menu_set_env_file(state: MenuState) -> MenuState:
    value = prompt_text("Env file path", default=state.env_file)
    if value:
        state.env_file = value
    pause("Env file updated. Press Enter to continue")
    return state


def build_menu_args(base_args: argparse.Namespace, state: MenuState) -> argparse.Namespace:
    menu_args = argparse.Namespace(**vars(base_args))
    menu_args.llm_mode = state.llm_mode
    menu_args.taxonomy_mode = state.taxonomy_mode
    menu_args.profile_file = Path(state.profile)
    menu_args.paper_filter = state.paper_filter
    menu_args.limit = state.limit
    menu_args.interactive = False
    menu_args.menu = False
    menu_args.input_dir = None
    menu_args.output_dir = None
    menu_args.env_file = Path(state.env_file)
    return menu_args


def print_conversion_summary(summary: ConversionSummary) -> None:
    print("")
    print(f"Input folder : {summary.input_dir}")
    print(f"Output folder: {summary.output_dir}")
    print(f"Processed    : {summary.processed_count} paired papers")
    print(f"Markdowns    : {summary.generated_files}")
    print(f"Manifest     : {summary.manifest_path}")
    print(f"Topic index  : {summary.topic_index_path}")
    if summary.skipped_messages:
        print("Notes:")
        for message in summary.skipped_messages:
            print(f"- {message}")


def run_menu_conversion(base_args: argparse.Namespace, state: MenuState, folders: list[Path]) -> None:
    if not folders:
        print("No folders selected.")
        pause()
        return

    env_path = Path(state.env_file)
    load_env_file(env_path, overwrite=True)
    menu_args = build_menu_args(base_args, state)

    for folder in folders:
        clear_screen()
        print(f"Running conversion for: {folder}")
        output_dir = derive_default_output_dir(folder)
        summary = convert_folder(menu_args, folder, output_dir)
        print_conversion_summary(summary)
        print("")
        print("Completed.")
        print("")
        if folder != folders[-1]:
            pause("Press Enter for the next folder")

    pause()


def menu_run_one(base_args: argparse.Namespace, state: MenuState) -> None:
    index = prompt_menu_folder_index(state, "Folder number to run")
    if index is None:
        pause()
        return
    run_menu_conversion(base_args, state, [Path(state.folders[index])])


def menu_run_all(base_args: argparse.Namespace, state: MenuState) -> None:
    run_menu_conversion(base_args, state, [Path(folder) for folder in state.folders])


def menu_show_folder_details(state: MenuState) -> None:
    index = prompt_menu_folder_index(state, "Folder number to inspect")
    if index is None:
        pause()
        return

    folder = Path(state.folders[index])
    output_dir = derive_default_output_dir(folder)
    print("")
    print(f"Folder      : {folder}")
    print(f"Output      : {output_dir}")
    print(f"Exists      : {folder.exists()}")
    pdf_count = len(list(folder.glob('*.pdf'))) if folder.exists() else 0
    print(f"PDF files   : {pdf_count}")
    print(f"Profile     : {state.profile}")
    print(f"Taxonomy mode: {state.taxonomy_mode}")
    print(f"Paper filter: {state.paper_filter if state.paper_filter else 'none'}")
    print(f"Limit       : {state.limit if state.limit is not None else 'none'}")
    pause()


def launch_menu(base_args: argparse.Namespace) -> int:
    state_path = DEFAULT_STATE_FILE
    state = load_menu_state(state_path)

    while True:
        save_menu_state(state_path, state)
        print_menu(state)
        choice = prompt_text("Choose an action")

        if choice == "1":
            state = menu_add_folder(state)
        elif choice == "2":
            state = menu_remove_folder(state)
        elif choice == "3":
            state = menu_set_profile(state)
        elif choice == "4":
            state = menu_set_taxonomy_mode(state)
        elif choice == "5":
            state = menu_set_llm_mode(state)
        elif choice == "6":
            state = menu_set_paper_filter(state)
        elif choice == "7":
            state = menu_set_limit(state)
        elif choice == "8":
            state = menu_set_env_file(state)
        elif choice == "9":
            menu_run_one(base_args, state)
        elif choice == "10":
            menu_run_all(base_args, state)
        elif choice == "11":
            menu_show_folder_details(state)
        elif choice == "0":
            save_menu_state(state_path, state)
            return 0
        else:
            pause("Unknown option")


def resolve_runtime_options(args: argparse.Namespace) -> RuntimeOptions:
    interactive = args.interactive or (args.input_dir is None and is_tty_session())

    if interactive:
        print("QNA Markdown Converter")
        print("")
        profile_file = prompt_profile_file(args.profile_file)
        input_dir = prompt_existing_folder(args.input_dir or DEFAULT_INPUT_DIR)
        taxonomy_mode = prompt_taxonomy_mode(default=getattr(args, "taxonomy_mode", DEFAULT_TAXONOMY_MODE))
        llm_mode = args.llm_mode if args.llm_mode != "off" else prompt_llm_mode()
        output_dir = args.output_dir or derive_default_output_dir(input_dir)
        print("")
        print(f"Profile file : {profile_file}")
        print(f"Taxonomy mode: {taxonomy_mode}")
        print(f"Input folder : {input_dir}")
        print(f"Output folder: {output_dir}")
        print(f"LLM mode     : {llm_mode}")
        print("")
        args.taxonomy_mode = taxonomy_mode
        return RuntimeOptions(input_dir=input_dir, output_dir=output_dir, llm_mode=llm_mode, profile_file=profile_file)

    if args.input_dir is None:
        raise ValueError("Input directory is required unless you run in interactive or menu mode.")
    input_dir = args.input_dir
    output_dir = args.output_dir or derive_default_output_dir(input_dir)
    profile_file = resolve_path(args.profile_file)
    return RuntimeOptions(input_dir=input_dir, output_dir=output_dir, llm_mode=args.llm_mode, profile_file=profile_file)


def load_env_file(path: Path, *, overwrite: bool = False) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = strip_wrapping_quotes(value.strip())
        if key and (overwrite or key not in os.environ):
            os.environ[key] = value


def canonical_stem(path: Path) -> str | None:
    stem = BYTES_SUFFIX_RE.sub("", path.stem.lower())
    match = PDF_KIND_RE.match(stem)
    if not match:
        return None
    return stem


def choose_preferred(paths: Iterable[Path]) -> Path:
    return max(
        paths,
        key=lambda candidate: (
            candidate.stat().st_size,
            len(candidate.name),
            candidate.name.lower(),
        ),
    )


def build_expected_reference_tokens(paper_key: str) -> list[str]:
    match = PAPER_REFERENCE_RE.search(paper_key)
    if not match:
        return []

    reference_code = match.group("spec").lower()
    raw_paper = match.group("paper")
    paper_numbers = {raw_paper, raw_paper.lstrip("0") or raw_paper}
    suffixes = current_profile().paper_reference_suffixes or ("",)
    tokens: set[str] = set()
    for paper_number in paper_numbers:
        tokens.add(f"paper {paper_number}")
        tokens.add(f"paper: {paper_number}")
        for suffix in suffixes:
            normalized_suffix = suffix.lower()
            if not normalized_suffix:
                continue
            tokens.add(f"{reference_code}/{paper_number}{normalized_suffix}")
            tokens.add(f"{reference_code}_{paper_number}{normalized_suffix}")
            tokens.add(f"paper {paper_number}{normalized_suffix}")
            tokens.add(f"paper: {paper_number}{normalized_suffix}")
    return sorted(tokens)


def extract_preview_text(path: Path, *, page_limit: int = 3) -> str:
    with fitz.open(path) as document:
        page_count = min(page_limit, document.page_count)
        preview = []
        for index in range(page_count):
            preview.append(normalize_unicode(document[index].get_text("text", sort=False)).lower())
        return "\n".join(preview)


def choose_best_candidate(paths: list[Path], paper_key: str) -> Path:
    if len(paths) == 1:
        return paths[0]

    expected_tokens = build_expected_reference_tokens(paper_key)
    scored: list[tuple[int, int, int, str, Path]] = []
    for path in paths:
        preview = extract_preview_text(path)
        reference_score = sum(3 for token in expected_tokens if token in preview)
        year_match = re.match(r"^(?P<year>\d{4})", paper_key)
        if year_match and year_match.group("year") in preview:
            reference_score += 1
        scored.append(
            (
                reference_score,
                path.stat().st_size,
                len(path.name),
                path.name.lower(),
                path,
            )
        )
    return max(scored)[-1]


def emit_log(logger: Callable[[str], None] | None, message: str) -> None:
    if logger is not None:
        logger(message)


def build_ocr_engine(args: argparse.Namespace, logger: Callable[[str], None] | None = None) -> Any | None:
    if getattr(args, "ocr_mode", "off") == "off":
        emit_log(logger, "[ocr] disabled")
        return None
    if RapidOCR is None:
        emit_log(logger, "[ocr] rapidocr_onnxruntime not installed, OCR disabled")
        return None
    emit_log(logger, "[ocr] initializing RapidOCR engine")
    return RapidOCR()


def normalize_ocr_line(text: str) -> str:
    text = normalize_unicode(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", text)
    text = re.sub(r"(?<=\d)(?=[A-Za-z])", " ", text)
    return text


def run_ocr_detections(
    image_path: Path,
    ocr_engine: Any | None,
    logger: Callable[[str], None] | None = None,
) -> OcrResult:
    if ocr_engine is None:
        return OcrResult(text="", lines=(), avg_confidence=0.0, detections=())

    emit_log(logger, f"[ocr] start {image_path.name}")
    try:
        result = ocr_engine(str(image_path))
    except Exception as exc:  # noqa: BLE001
        emit_log(logger, f"[ocr] failed {image_path.name} | {exc}")
        return OcrResult(text="", lines=(), avg_confidence=0.0, detections=())

    cleaned_detections: list[dict[str, Any]] = []
    scores: list[float] = []
    if isinstance(result, tuple) and result:
        detections = result[0]
        if isinstance(detections, list):
            for item in detections:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                text = normalize_ocr_line(str(item[1]))
                try:
                    score = float(item[2]) if len(item) >= 3 else 0.0
                except (TypeError, ValueError):
                    score = 0.0
                if not text or score < 0.35:
                    continue
                bbox = item[0] if item and isinstance(item[0], (list, tuple)) else []
                cleaned_detections.append(
                    {
                        "bbox": bbox,
                        "text": text,
                        "confidence": round(score, 4),
                    }
                )
                scores.append(score)

    deduped_lines: list[str] = []
    seen_lines: set[str] = set()
    for detection in cleaned_detections:
        text = detection["text"]
        key = text.lower()
        if key in seen_lines:
            continue
        seen_lines.add(key)
        deduped_lines.append(text)

    avg_confidence = sum(scores) / len(scores) if scores else 0.0
    emit_log(logger, f"[ocr] done {image_path.name} | lines={len(deduped_lines)} | avg_conf={avg_confidence:.2f}")
    return OcrResult(
        text="\n".join(deduped_lines).strip(),
        lines=tuple(deduped_lines),
        avg_confidence=round(avg_confidence, 4),
        detections=tuple(cleaned_detections),
    )


def render_page_to_temp_png(page: fitz.Page) -> Path:
    temp_dir = Path(tempfile.gettempdir())
    temp_path = temp_dir / f"qna_page_ocr_{os.getpid()}_{page.number + 1}.png"
    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    temp_path.write_bytes(pixmap.tobytes("png"))
    return temp_path


def discover_pairs(input_dir: Path, paper_filter: str | None = None) -> tuple[list[PaperPair], list[str]]:
    grouped: dict[str, dict[str, list[Path]]] = defaultdict(lambda: defaultdict(list))
    skipped: list[str] = []
    for path in sorted(input_dir.glob("*.pdf")):
        normalized = canonical_stem(path)
        if not normalized:
            skipped.append(f"Skipping unrecognized filename: {path.name}")
            continue
        match = PDF_KIND_RE.match(normalized)
        assert match is not None
        paper_key = match.group("stem")
        kind = match.group("kind").lower()
        grouped[paper_key][kind].append(path)

    if paper_filter:
        paper_filter = paper_filter.lower()

    pairs: list[PaperPair] = []
    for paper_key in sorted(grouped):
        if paper_filter and paper_filter not in paper_key:
            continue
        kinds = grouped[paper_key]
        if "qp" not in kinds or "ms" not in kinds:
            skipped.append(f"Missing pair for {paper_key}: found {sorted(kinds)}")
            continue
        year_match = re.match(r"^(?P<year>\d{4})", paper_key)
        year = year_match.group("year") if year_match else "unknown-year"
        pairs.append(
            PaperPair(
                key=paper_key,
                year=year,
                question_pdf=choose_best_candidate(kinds["qp"], paper_key),
                mark_scheme_pdf=choose_best_candidate(kinds["ms"], paper_key),
            )
        )
    return pairs, skipped


def extract_lines(path: Path, *, sort: bool) -> list[str]:
    lines: list[str] = []
    with fitz.open(path) as document:
        for page in document:
            page_text = page.get_text("text", sort=sort)
            lines.extend(normalize_unicode(line) for line in page_text.splitlines())
    return lines


def should_drop_question_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped in {"DO", "NOT", "WRITE", "IN", "THIS", "AREA", "BLANK PAGE"}:
        return True
    if all(char in "■□•·." for char in stripped):
        return True
    return any(pattern.match(stripped) for pattern in current_profile().question_drop_patterns)


def should_drop_mark_scheme_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if all(char in "■□•·." for char in stripped):
        return True
    return any(pattern.match(stripped) for pattern in current_profile().mark_scheme_drop_patterns)


def normalize_visible_line(line: str) -> str:
    line = line.replace("\t", " ")
    line = re.sub(r" {2,}", " ", line)
    line = line.strip()
    line = re.sub(r"^(\d{1,2})([A-Za-z])", r"\1 \2", line)
    return line


def finalize_block(lines: list[str], *, mode: str) -> str:
    cleaned: list[str] = []
    previous_blank = True
    for raw_line in lines:
        if mode == "question" and should_drop_question_line(raw_line):
            continue
        if mode == "mark_scheme" and should_drop_mark_scheme_line(raw_line):
            continue

        line = normalize_visible_line(raw_line)
        if not line:
            if not previous_blank:
                cleaned.append("")
            previous_blank = True
            continue

        cleaned.append(line)
        previous_blank = False

    while cleaned and cleaned[0] == "":
        cleaned.pop(0)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    return "\n".join(cleaned)


def is_question_start(line: str, expected_number: int) -> bool:
    line = re.sub(r"^\s*(\d{1,2})([A-Z])", r"\1 \2", line)
    match = QUESTION_START_RE.match(line)
    if not match:
        return False
    if int(match.group("number")) != expected_number:
        return False
    rest = match.group("rest").strip()
    if not rest:
        return False
    return rest.startswith("(") or rest[0].isupper()


def split_question_paper(path: Path) -> dict[int, str]:
    blocks: dict[int, str] = {}
    current_number: int | None = None
    current_lines: list[str] = []
    expected_number = 1

    for line in extract_lines(path, sort=False):
        if current_number is None:
            if is_question_start(line, expected_number):
                current_number = expected_number
                current_lines = [line]
                expected_number += 1
            continue

        if is_question_start(line, expected_number):
            blocks[current_number] = finalize_block(current_lines, mode="question")
            current_number = expected_number
            current_lines = [line]
            expected_number += 1
            continue

        current_lines.append(line)

    if current_number is not None and current_lines:
        blocks[current_number] = finalize_block(current_lines, mode="question")
    return blocks


def extract_text_from_text_block(block: dict[str, Any]) -> str:
    lines: list[str] = []
    for line in block.get("lines", []):
        spans = line.get("spans", [])
        text = "".join(normalize_unicode(span.get("text", "")) for span in spans).strip()
        text = re.sub(r"^(\d{1,2})([A-Z])", r"\1 \2", text)
        text = re.sub(r"^\(([a-z])\)([A-Z])", r"(\1) \2", text)
        if text:
            lines.append(text)
    return "\n".join(lines).strip()


def is_decorative_image_block(block: dict[str, Any], page_rect: fitz.Rect) -> bool:
    bbox = fitz.Rect(block.get("bbox", (0, 0, 0, 0)))
    width = bbox.width
    height = bbox.height
    near_left = bbox.x0 <= page_rect.x0 + 50
    near_right = bbox.x1 >= page_rect.x1 - 50
    if width <= 40 and height >= page_rect.height * 0.7 and (near_left or near_right):
        return True
    if width > page_rect.width * 0.75 and height > page_rect.height * 0.75:
        return True
    return False


def is_candidate_drawing_rect(rect: fitz.Rect, page_rect: fitz.Rect) -> bool:
    if rect.is_empty:
        return False
    if rect.width > page_rect.width * 0.75 and rect.height > page_rect.height * 0.75:
        return False
    near_left = rect.x0 <= page_rect.x0 + 50
    near_right = rect.x1 >= page_rect.x1 - 50
    if rect.width <= 40 and rect.height >= page_rect.height * 0.7 and (near_left or near_right):
        return False
    if rect.width < 20 and rect.height < 20:
        return False
    if rect.width < 6 or rect.height < 6:
        return False
    return True


def merge_visual_rects(rects: list[fitz.Rect], gap: float = VISUAL_MERGE_GAP) -> list[fitz.Rect]:
    merged: list[fitz.Rect] = []
    for rect in rects:
        current = fitz.Rect(rect)
        updated = True
        while updated:
            updated = False
            remaining: list[fitz.Rect] = []
            for existing in merged:
                expanded = fitz.Rect(
                    existing.x0 - gap,
                    existing.y0 - gap,
                    existing.x1 + gap,
                    existing.y1 + gap,
                )
                if expanded.intersects(current):
                    current |= existing
                    updated = True
                else:
                    remaining.append(existing)
            merged = remaining
        merged.append(current)
    return merged


def cluster_related_visual_rects(rects: list[fitz.Rect]) -> list[fitz.Rect]:
    clustered: list[fitz.Rect] = []
    for rect in rects:
        current = fitz.Rect(rect)
        changed = True
        while changed:
            changed = False
            remaining: list[fitz.Rect] = []
            for existing in clustered:
                horizontal_gap = max(0.0, max(existing.x0, current.x0) - min(existing.x1, current.x1))
                vertical_gap = max(0.0, max(existing.y0, current.y0) - min(existing.y1, current.y1))
                overlaps_horizontally = not (existing.x1 < current.x0 or current.x1 < existing.x0)
                overlaps_vertically = not (existing.y1 < current.y0 or current.y1 < existing.y0)
                should_merge = (
                    (overlaps_horizontally and vertical_gap <= VISUAL_CLUSTER_VERTICAL_GAP)
                    or (overlaps_vertically and horizontal_gap <= VISUAL_CLUSTER_HORIZONTAL_GAP)
                    or (horizontal_gap <= VISUAL_CLUSTER_HORIZONTAL_GAP and vertical_gap <= VISUAL_CLUSTER_VERTICAL_GAP)
                )
                if should_merge:
                    current |= existing
                    changed = True
                else:
                    remaining.append(existing)
            clustered = remaining
        clustered.append(current)
    return clustered


def collect_visual_regions(page: fitz.Page) -> list[fitz.Rect]:
    page_rect = page.rect
    raw_rects: list[fitz.Rect] = []

    text_dict = page.get_text("dict", sort=False)
    for block in text_dict.get("blocks", []):
        if block.get("type") == 1 and not is_decorative_image_block(block, page_rect):
            raw_rects.append(fitz.Rect(block["bbox"]))

    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if rect is not None and is_candidate_drawing_rect(rect, page_rect):
            raw_rects.append(fitz.Rect(rect))

    merged = merge_visual_rects(raw_rects)
    merged = cluster_related_visual_rects(merged)

    filtered: list[fitz.Rect] = []
    for rect in merged:
        if rect.width < 40 or rect.height < 20:
            continue
        if rect.width * rect.height < 1800:
            continue
        if rect.width < VISUAL_CLUSTER_MIN_WIDTH and rect.height < VISUAL_CLUSTER_MIN_HEIGHT:
            continue
        expanded = fitz.Rect(
            max(page_rect.x0, rect.x0 - VISUAL_CLIP_PADDING),
            max(page_rect.y0, rect.y0 - VISUAL_CLIP_PADDING),
            min(page_rect.x1, rect.x1 + VISUAL_CLIP_PADDING),
            min(page_rect.y1, rect.y1 + VISUAL_CLIP_PADDING),
        )
        filtered.append(expanded)

    filtered.sort(key=lambda item: (round(item.y0, 2), round(item.x0, 2)))
    return filtered


def should_attach_text_to_visual(text: str, text_rect: fitz.Rect, visual_rect: fitz.Rect) -> bool:
    normalized = " ".join(text.split())
    if not normalized:
        return False
    if should_drop_question_line(normalized):
        return False
    if TOTAL_MARKS_LINE_RE.match(normalized):
        return False
    if re.fullmatch(r"\d+", normalized):
        return False
    if len(normalized) > 140 or len(normalized.split()) > 18:
        return False
    if re.match(r"^\d+\s+[A-Z]", normalized):
        return False
    if normalized.startswith("(") and len(normalized) < 10:
        return False

    vertical_overlap = max(0.0, min(text_rect.y1, visual_rect.y1) - max(text_rect.y0, visual_rect.y0))
    horizontal_overlap = max(0.0, min(text_rect.x1, visual_rect.x1) - max(text_rect.x0, visual_rect.x0))
    horizontal_gap = 0.0 if horizontal_overlap > 0 else min(abs(text_rect.x1 - visual_rect.x0), abs(visual_rect.x1 - text_rect.x0))
    vertical_gap = 0.0 if vertical_overlap > 0 else min(abs(text_rect.y1 - visual_rect.y0), abs(visual_rect.y1 - text_rect.y0))

    if vertical_overlap > 0 and horizontal_gap <= VISUAL_HORIZONTAL_ATTACH_GAP:
        return True
    if horizontal_overlap > 0 and vertical_gap <= VISUAL_VERTICAL_ATTACH_GAP and text_rect.y0 >= visual_rect.y0 and len(normalized) <= 120:
        return True
    return False


def clean_visual_asset_text(text: str) -> str:
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        normalized = " ".join(raw_line.split()).strip()
        if not normalized:
            continue
        if should_drop_question_line(normalized):
            continue
        if TOTAL_MARKS_LINE_RE.match(normalized):
            continue
        cleaned_lines.append(normalized)
    return "\n".join(cleaned_lines).strip()


def attach_text_to_visuals(
    visual_rects: list[fitz.Rect],
    text_blocks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[int]]:
    enriched_visuals: list[dict[str, Any]] = []
    consumed_text_indexes: set[int] = set()

    for rect in visual_rects:
        base_rect = fitz.Rect(rect)
        combined_rect = fitz.Rect(rect)
        attached_texts: list[str] = []
        local_consumed: list[int] = []
        for index, block in enumerate(text_blocks):
            if index in consumed_text_indexes:
                continue
            text_rect = fitz.Rect(block["bbox"])
            text = block["text"]
            if should_attach_text_to_visual(text, text_rect, base_rect):
                combined_rect |= text_rect
                attached_texts.append(text)
                local_consumed.append(index)

        consumed_text_indexes.update(local_consumed)
        enriched_visuals.append(
            {
                "rect": combined_rect,
                "asset_text": clean_visual_asset_text("\n".join(attached_texts)),
            }
        )

    return enriched_visuals, consumed_text_indexes


def render_visual_block(page: fitz.Page, rect: fitz.Rect, asset_text: str = "") -> PendingVisualBlock:
    matrix = fitz.Matrix(2, 2)
    pixmap = page.get_pixmap(matrix=matrix, clip=rect, alpha=False)
    if pixmap.width < 260 or pixmap.height < 120:
        page_rect = page.rect
        expanded_rect = fitz.Rect(
            max(page_rect.x0, rect.x0 - 24),
            max(page_rect.y0, rect.y0 - 24),
            min(page_rect.x1, rect.x1 + 24),
            min(page_rect.y1, rect.y1 + 24),
        )
        expanded_pixmap = page.get_pixmap(matrix=matrix, clip=expanded_rect, alpha=False)
        if expanded_pixmap.width > pixmap.width or expanded_pixmap.height > pixmap.height:
            rect = expanded_rect
            pixmap = expanded_pixmap
    return PendingVisualBlock(
        page_number=page.number + 1,
        bbox=(round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2)),
        png_bytes=pixmap.tobytes("png"),
        width=pixmap.width,
        height=pixmap.height,
        source_type="page_region",
        asset_text=asset_text,
    )


def first_non_empty_line(text: str) -> str | None:
    for line in text.splitlines():
        normalized = line.strip()
        if normalized:
            return normalized
    return None


def should_use_page_ocr_fallback(extracted_questions: list[ExtractedQuestionContent]) -> bool:
    if not extracted_questions:
        return True
    total_chars = sum(len(question.question_text.strip()) for question in extracted_questions)
    total_lines = sum(len(question.question_text.splitlines()) for question in extracted_questions)
    return total_chars < 250 or total_lines < 8


def extract_question_paper_from_page_ocr(
    pair: PaperPair,
    ocr_engine: Any | None,
    logger: Callable[[str], None] | None = None,
) -> list[ExtractedQuestionContent]:
    if ocr_engine is None:
        return []

    extracted: list[ExtractedQuestionContent] = []
    current_number: int | None = None
    current_lines: list[str] = []
    expected_number = 1

    with fitz.open(pair.question_pdf) as document:
        for page in document:
            temp_path = render_page_to_temp_png(page)
            try:
                ocr_result = run_ocr_detections(temp_path, ocr_engine, logger=logger)
            finally:
                temp_path.unlink(missing_ok=True)

            for line in ocr_result.lines:
                if should_drop_question_line(line):
                    continue
                if is_question_start(line, expected_number):
                    if current_number is not None and current_lines:
                        question_text = finalize_block(current_lines, mode="question")
                        label = build_question_label(current_number, question_text)
                        extracted.append(
                            ExtractedQuestionContent(
                                question_number=current_number,
                                question_label=label,
                                question_text=question_text,
                                content_blocks=tuple({"type": "text", "content": chunk} for chunk in question_text.split("\n\n") if chunk.strip()),
                                assets=(),
                            )
                        )
                    current_number = expected_number
                    current_lines = [line]
                    expected_number += 1
                elif current_number is not None:
                    current_lines.append(line)

    if current_number is not None and current_lines:
        question_text = finalize_block(current_lines, mode="question")
        label = build_question_label(current_number, question_text)
        extracted.append(
            ExtractedQuestionContent(
                question_number=current_number,
                question_label=label,
                question_text=question_text,
                content_blocks=tuple({"type": "text", "content": chunk} for chunk in question_text.split("\n\n") if chunk.strip()),
                assets=(),
            )
        )

    emit_log(logger, f"[ocr] page fallback extracted questions={len(extracted)}")
    return extracted


def extract_question_paper_with_assets(
    pair: PaperPair,
    output_dir: Path,
    ocr_engine: Any | None = None,
    allow_page_ocr_fallback: bool = False,
    logger: Callable[[str], None] | None = None,
) -> list[ExtractedQuestionContent]:
    pending_questions: list[dict[str, Any]] = []
    current_question: dict[str, Any] | None = None
    expected_number = 1

    with fitz.open(pair.question_pdf) as document:
        for page in document:
            page_items: list[dict[str, Any]] = []
            text_blocks: list[dict[str, Any]] = []
            page_dict = page.get_text("dict", sort=False)

            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                text = extract_text_from_text_block(block)
                if not text:
                    continue
                text_blocks.append(
                    {
                        "bbox": fitz.Rect(block["bbox"]),
                        "text": text,
                    }
                )

            enriched_visuals, consumed_text_indexes = attach_text_to_visuals(collect_visual_regions(page), text_blocks)

            for index, text_block in enumerate(text_blocks):
                if index in consumed_text_indexes:
                    continue
                page_items.append(
                    {
                        "kind": "text",
                        "bbox": text_block["bbox"],
                        "text": text_block["text"],
                    }
                )

            for visual in enriched_visuals:
                page_items.append(
                    {
                        "kind": "visual",
                        "bbox": visual["rect"],
                        "visual": render_visual_block(page, visual["rect"], visual["asset_text"]),
                    }
                )

            page_items.sort(key=lambda item: (round(item["bbox"].y0, 2), round(item["bbox"].x0, 2), item["kind"]))

            for item in page_items:
                if item["kind"] == "text":
                    first_line = first_non_empty_line(item["text"])
                    if first_line is not None and is_question_start(first_line, expected_number):
                        if current_question is not None:
                            pending_questions.append(current_question)
                        current_question = {
                            "question_number": expected_number,
                            "blocks": [item],
                        }
                        emit_log(logger, f"[extract] question start detected q{expected_number}")
                        expected_number += 1
                        continue

                    if current_question is not None:
                        current_question["blocks"].append(item)
                elif current_question is not None:
                    current_question["blocks"].append(item)

    if current_question is not None:
        pending_questions.append(current_question)

    extracted_questions: list[ExtractedQuestionContent] = []
    for question in pending_questions:
        question_number = int(question["question_number"])
        text_lines: list[str] = []
        for block in question["blocks"]:
            if block["kind"] == "text":
                text_lines.extend(block["text"].splitlines())

        base_question_text = finalize_block(text_lines, mode="question")
        question_label = build_question_label(question_number, base_question_text)
        paper_dir = output_dir / pair.year / pair.key
        asset_dir = output_dir / "_assets" / pair.year / pair.key / question_label
        asset_dir.mkdir(parents=True, exist_ok=True)

        markdown_parts: list[str] = []
        content_blocks: list[dict[str, Any]] = []
        asset_entries: list[dict[str, Any]] = []
        asset_index = 0

        for block in question["blocks"]:
            if block["kind"] == "text":
                cleaned_text = finalize_block(block["text"].splitlines(), mode="question")
                if cleaned_text:
                    markdown_parts.append(cleaned_text)
                    content_blocks.append(
                        {
                            "type": "text",
                            "content": cleaned_text,
                        }
                    )
                continue

            visual: PendingVisualBlock = block["visual"]
            asset_index += 1
            asset_id = f"{pair.year}_{pair.key.replace('-', '_')}_{question_label}_fig_{asset_index:02d}"
            file_name = f"fig_{asset_index:02d}.png"
            asset_path = asset_dir / file_name
            asset_path.write_bytes(visual.png_bytes)
            ocr_result = run_ocr_detections(asset_path, ocr_engine, logger=logger)
            ocr_text = ocr_result.text

            markdown_dir = output_dir / pair.year / pair.key
            relative_path = Path(os.path.relpath(asset_path, markdown_dir)).as_posix()
            asset_placeholder = f"[[ASSET:{asset_id}]]"
            markdown_image = f"{asset_placeholder}\n![{asset_id}]({relative_path})"

            asset_entry = {
                "asset_id": asset_id,
                "question_label": question_label,
                "paper_key": pair.key,
                "year": pair.year,
                "page_number": visual.page_number,
                "path": str(asset_path),
                "relative_path": relative_path,
                "source_type": visual.source_type,
                "bbox": list(visual.bbox),
                "width": visual.width,
                "height": visual.height,
                "order": asset_index,
                "asset_text": visual.asset_text,
                "ocr_text": ocr_text,
                "ocr_confidence": ocr_result.avg_confidence,
                "ocr_line_count": len(ocr_result.lines),
            }
            asset_entries.append(asset_entry)
            markdown_parts.append(markdown_image)
            content_blocks.append(
                {
                    "type": "image",
                    "asset_id": asset_id,
                    "placeholder": asset_placeholder,
                    "relative_path": relative_path,
                    "page_number": visual.page_number,
                    "bbox": list(visual.bbox),
                    "width": visual.width,
                    "height": visual.height,
                    "asset_text": visual.asset_text,
                    "ocr_text": ocr_text,
                    "ocr_confidence": ocr_result.avg_confidence,
                    "ocr_line_count": len(ocr_result.lines),
                }
            )
            emit_log(logger, f"[asset] {pair.key} {question_label.upper()} | saved {asset_path.name} from page {visual.page_number}")

        question_text = "\n\n".join(part for part in markdown_parts if part).strip()
        extracted_questions.append(
            ExtractedQuestionContent(
                question_number=question_number,
                question_label=question_label,
                question_text=question_text,
                content_blocks=tuple(content_blocks),
                assets=tuple(asset_entries),
            )
        )

    if allow_page_ocr_fallback and should_use_page_ocr_fallback(extracted_questions):
        emit_log(logger, f"[ocr] page fallback triggered for {pair.key}")
        fallback_questions = extract_question_paper_from_page_ocr(pair, ocr_engine, logger=logger)
        if len(fallback_questions) > len(extracted_questions):
            emit_log(logger, f"[ocr] page fallback adopted for {pair.key}")
            return fallback_questions

    return extracted_questions


def extract_mark_scheme_question_number(block_lines: list[str]) -> int | None:
    candidate_lines: list[str] = []
    for line in block_lines[:18]:
        normalized = normalize_visible_line(line)
        if not normalized:
            continue
        if normalized.lower() in current_profile().skip_mark_scheme_headers:
            continue
        candidate_lines.append(normalized)

    for line in candidate_lines:
        if TOTAL_LINE_RE.match(line):
            continue
        match = QUESTION_ID_RE.match(line)
        if match:
            return int(match.group("number"))
    return None


def split_mark_scheme(path: Path) -> dict[int, str]:
    lines = extract_lines(path, sort=True)
    header_indexes = [index for index, line in enumerate(lines) if line.lstrip().startswith("Question")]

    grouped_blocks: dict[int, list[str]] = defaultdict(list)
    for idx, start in enumerate(header_indexes):
        end = header_indexes[idx + 1] if idx + 1 < len(header_indexes) else len(lines)
        block_lines = lines[start:end]
        question_number = extract_mark_scheme_question_number(block_lines)
        if question_number is None:
            continue
        text = finalize_block(block_lines, mode="mark_scheme")
        if text:
            grouped_blocks[question_number].append(text)

    return {
        question_number: "\n\n".join(text for text in blocks if text)
        for question_number, blocks in sorted(grouped_blocks.items())
    }


def build_question_label(question_number: int, question_text: str) -> str:
    for line in question_text.splitlines():
        match = re.match(rf"^{question_number}\s*\((?P<part>[a-z])\)", line, re.IGNORECASE)
        if match:
            return f"q{question_number}{match.group('part').lower()}"
        match = re.match(r"^\((?P<part>[a-z])\)", line, re.IGNORECASE)
        if match:
            return f"q{question_number}{match.group('part').lower()}"
    return f"q{question_number}"


def derive_auto_taxonomy_path(input_dir: Path) -> Path:
    base_dir = input_dir.parent if input_dir.name.lower() == "past-papers" else input_dir
    return base_dir / DEFAULT_AUTO_TAXONOMY_FILENAME


def truncate_for_prompt(text: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def subject_hint_from_input_dir(input_dir: Path) -> str:
    if input_dir.name.lower() == "past-papers" and input_dir.parent.name:
        return input_dir.parent.name
    return input_dir.name or "Unknown subject"


def collect_taxonomy_examples(
    pairs: list[PaperPair],
    *,
    sample_limit: int = DEFAULT_AUTO_TAXONOMY_SAMPLE_LIMIT,
) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for pair in pairs:
        question_blocks = split_question_paper(pair.question_pdf)
        answer_blocks = split_mark_scheme(pair.mark_scheme_pdf)
        for question_number, question_text in sorted(question_blocks.items()):
            question_label = build_question_label(question_number, question_text)
            examples.append(
                {
                    "paper_key": pair.key,
                    "year": pair.year,
                    "question_label": question_label.upper(),
                    "question_text": truncate_for_prompt(question_text, DEFAULT_AUTO_TAXONOMY_QUESTION_CHAR_LIMIT),
                    "answer_text": truncate_for_prompt(
                        answer_blocks.get(question_number, ""),
                        DEFAULT_AUTO_TAXONOMY_ANSWER_CHAR_LIMIT,
                    ),
                }
            )
            if len(examples) >= sample_limit:
                return examples
    return examples


def normalize_taxonomy_keywords(raw_keywords: Any, fallback_text: str) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()
    if isinstance(raw_keywords, list):
        for item in raw_keywords:
            keyword = re.sub(r"\s+", " ", normalize_taxonomy_text(str(item))).strip(" \t\r\n,.;:-")
            normalized = keyword.lower()
            if not keyword or normalized in seen:
                continue
            seen.add(normalized)
            keywords.append(keyword)
            if len(keywords) >= 10:
                return keywords

    if keywords:
        return keywords

    for token in sorted(tokenize_for_search(fallback_text)):
        if token in seen:
            continue
        keywords.append(token)
        if len(keywords) >= 6:
            break
    return keywords


def normalize_taxonomy_text(text: str) -> str:
    text = normalize_unicode(text)
    text = (
        text.replace("\u2010", "-")
        .replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )
    return re.sub(r"\s+", " ", text).strip()


def normalize_taxonomy_payload(payload: dict[str, Any], fallback_subject: str) -> dict[str, Any]:
    subject = normalize_taxonomy_text(str(payload.get("subject", fallback_subject))) or fallback_subject
    raw_chapters = payload.get("chapters")
    if not isinstance(raw_chapters, list):
        raw_topics = payload.get("topics")
        raw_chapters = [{"name": "Core topics", "topics": raw_topics}] if isinstance(raw_topics, list) else []

    normalized_chapters: list[dict[str, Any]] = []
    chapter_name_seen: set[str] = set()
    for chapter_index, chapter_raw in enumerate(raw_chapters, start=1):
        if not isinstance(chapter_raw, dict):
            continue
        chapter_name = normalize_taxonomy_text(str(chapter_raw.get("name", ""))) or f"Chapter {chapter_index}"
        chapter_key = normalize_for_search(chapter_name)
        if not chapter_key or chapter_key in chapter_name_seen:
            continue
        chapter_name_seen.add(chapter_key)

        raw_topics = chapter_raw.get("topics", [])
        if not isinstance(raw_topics, list):
            continue

        normalized_topics: list[dict[str, Any]] = []
        topic_name_seen: set[str] = set()
        for topic_index, topic_raw in enumerate(raw_topics, start=1):
            if not isinstance(topic_raw, dict):
                continue
            topic_name = normalize_taxonomy_text(str(topic_raw.get("name", ""))) or f"Topic {topic_index}"
            topic_key = normalize_for_search(topic_name)
            if not topic_key or topic_key in topic_name_seen:
                continue
            topic_name_seen.add(topic_key)

            description = normalize_taxonomy_text(str(topic_raw.get("description", ""))) or topic_name
            keywords = normalize_taxonomy_keywords(topic_raw.get("keywords"), f"{topic_name} {description}")
            normalized_topics.append(
                {
                    "id": f"c{len(normalized_chapters) + 1:02d}_t{len(normalized_topics) + 1:02d}",
                    "name": topic_name,
                    "description": description,
                    "keywords": keywords,
                }
            )

        if not normalized_topics:
            continue

        normalized_chapters.append(
            {
                "id": f"c{len(normalized_chapters) + 1:02d}",
                "name": chapter_name,
                "topics": normalized_topics,
            }
        )

    if not normalized_chapters:
        raise ValueError("Generated taxonomy did not contain any valid chapters and topics.")

    return {
        "subject": subject,
        "chapters": normalized_chapters,
    }


def generate_taxonomy_draft(
    *,
    input_dir: Path,
    taxonomy_path: Path,
    pairs: list[PaperPair],
    llm_client: MiniMaxClient,
    logger: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    subject_hint = subject_hint_from_input_dir(input_dir)
    system_prompt = (
        "You design reusable exam-topic taxonomies from extracted exam questions and mark scheme snippets. "
        "Return one JSON object only. Do not use code fences."
    )
    last_error: Exception | None = None
    for sample_limit in (DEFAULT_AUTO_TAXONOMY_SAMPLE_LIMIT, 30, 15):
        examples = collect_taxonomy_examples(pairs, sample_limit=sample_limit)
        if not examples:
            raise ValueError("No extracted questions were available to generate a taxonomy draft.")

        emit_log(logger, f"[taxonomy] generating draft from {len(examples)} sampled questions")
        user_payload = {
            "task": "Create a draft taxonomy that can be reused to tag future questions from the same subject consistently.",
            "rules": [
                "Infer one subject title from the examples and subject hint.",
                "Use broad chapter names and narrower topic names.",
                "Prefer syllabus-style topic labels, not question-specific wording.",
                "Avoid duplicate or overlapping topics.",
                "Use concise descriptions.",
                "Provide 6 to 10 practical keywords per topic.",
                "Only use concepts supported by the examples; do not hallucinate an entire syllabus from thin evidence.",
                "If the sample is narrow, use fewer chapters and topics rather than inventing coverage.",
            ],
            "output_schema": {
                "subject": "string",
                "chapters": [
                    {
                        "name": "string",
                        "topics": [
                            {
                                "name": "string",
                                "description": "string",
                                "keywords": ["string"],
                            }
                        ],
                    }
                ],
            },
            "subject_hint": subject_hint,
            "examples": examples,
        }
        try:
            llm_payload = llm_client.create_json(
                system_prompt=system_prompt,
                user_prompt=json.dumps(user_payload, ensure_ascii=False, indent=2),
                max_tokens=2800,
                temperature=0.0,
            )
            taxonomy = normalize_taxonomy_payload(llm_payload, subject_hint)
            taxonomy_path.parent.mkdir(parents=True, exist_ok=True)
            taxonomy_path.write_text(json.dumps(taxonomy, indent=2, ensure_ascii=False), encoding="utf-8")
            emit_log(logger, f"[taxonomy] draft saved {taxonomy_path}")
            return taxonomy
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if sample_limit == 15:
                raise
            emit_log(logger, f"[taxonomy] draft generation failed with {len(examples)} samples: {exc}")
            emit_log(logger, "[taxonomy] retrying with a smaller sample")

    assert last_error is not None
    raise last_error


def load_taxonomy(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    if not path.exists():
        raise FileNotFoundError(f"Taxonomy file does not exist: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def iter_taxonomy_topics(taxonomy: dict[str, Any] | None) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
    if not taxonomy:
        return
    for chapter in taxonomy.get("chapters", []):
        for topic in chapter.get("topics", []):
            yield chapter, topic


def normalize_for_search(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokenize_for_search(text: str) -> set[str]:
    normalized = normalize_for_search(text)
    if not normalized:
        return set()
    return {
        token
        for token in normalized.split()
        if len(token) >= 3 and token not in SEARCH_STOPWORDS
    }


def score_taxonomy_topic(
    corpus: str,
    corpus_tokens: set[str],
    chapter: dict[str, Any],
    topic: dict[str, Any],
) -> tuple[int, list[str]]:
    matched_keywords: list[str] = []
    score = 0
    keyword_tokens: set[str] = set()

    for keyword in topic.get("keywords", []):
        normalized_keyword = normalize_for_search(keyword)
        keyword_tokens.update(tokenize_for_search(keyword))
        if normalized_keyword and normalized_keyword in corpus:
            matched_keywords.append(str(keyword))
            score += 10 + (len(normalized_keyword.split()) * 3)

    topic_name = normalize_for_search(str(topic.get("name", "")))
    if topic_name and topic_name in corpus:
        score += max(6, len(topic_name.split()) * 2)

    chapter_name = normalize_for_search(str(chapter.get("name", "")))
    if chapter_name and chapter_name in corpus:
        score += max(3, len(chapter_name.split()))

    metadata_tokens = tokenize_for_search(
        " ".join(
            [
                str(chapter.get("name", "")),
                str(topic.get("name", "")),
                str(topic.get("description", "")),
            ]
        )
    )
    score += len(corpus_tokens & metadata_tokens) * 2
    score += len(corpus_tokens & keyword_tokens)
    if matched_keywords:
        score += len(matched_keywords)

    return score, matched_keywords[:6]


def rank_taxonomy_topics(
    question_text: str,
    answer_text: str,
    taxonomy: dict[str, Any] | None,
) -> list[tuple[int, dict[str, Any], dict[str, Any], list[str]]]:
    if not taxonomy:
        return []

    corpus = normalize_for_search(f"{question_text}\n{answer_text}")
    if not corpus:
        return []
    corpus_tokens = tokenize_for_search(corpus)

    ranked: list[tuple[int, dict[str, Any], dict[str, Any], list[str]]] = []
    for chapter, topic in iter_taxonomy_topics(taxonomy):
        score, matched_keywords = score_taxonomy_topic(corpus, corpus_tokens, chapter, topic)
        if score <= 0:
            continue
        ranked.append((score, chapter, topic, matched_keywords))

    ranked.sort(
        key=lambda item: (
            -item[0],
            item[1].get("id", ""),
            item[2].get("id", ""),
        )
    )
    return ranked


def count_taxonomy_topics(taxonomy: dict[str, Any] | None) -> int:
    return sum(1 for _chapter, _topic in iter_taxonomy_topics(taxonomy))


def shortlist_taxonomy_for_prompt(
    question_text: str,
    answer_text: str,
    taxonomy: dict[str, Any] | None,
    *,
    max_topics: int = DEFAULT_PROMPT_TOPIC_LIMIT,
) -> tuple[dict[str, Any] | None, list[str], bool]:
    if not taxonomy:
        return None, [], False

    total_topics = count_taxonomy_topics(taxonomy)
    if total_topics <= max_topics:
        return taxonomy, [], False

    ranked_topics = rank_taxonomy_topics(question_text, answer_text, taxonomy)
    if not ranked_topics:
        return taxonomy, [], False
    if ranked_topics[0][0] < MIN_PROMPT_SHORTLIST_SCORE:
        return taxonomy, [], False

    selected = ranked_topics[:max_topics]
    selected_ids = {topic["id"] for _score, _chapter, topic, _matched in selected}
    selected_id_list = [topic["id"] for _score, _chapter, topic, _matched in selected]

    chapters: list[dict[str, Any]] = []
    for chapter in taxonomy.get("chapters", []):
        selected_topics = [topic for topic in chapter.get("topics", []) if topic.get("id") in selected_ids]
        if not selected_topics:
            continue
        chapters.append(
            {
                "id": chapter.get("id"),
                "name": chapter.get("name"),
                "topics": selected_topics,
            }
        )

    if not chapters:
        return taxonomy, [], False

    return {
        "subject": taxonomy.get("subject", "Unknown"),
        "chapters": chapters,
    }, selected_id_list, True


def infer_topic_heuristically(question_text: str, answer_text: str, taxonomy: dict[str, Any] | None) -> TopicMatch | None:
    if not taxonomy:
        return None
    ranked_topics = rank_taxonomy_topics(question_text, answer_text, taxonomy)
    if not ranked_topics:
        return None

    score, chapter, topic, matched_keywords = ranked_topics[0]
    confidence = min(0.95, 0.35 + (score * 0.04))
    return TopicMatch(
        chapter_id=chapter["id"],
        chapter_name=chapter["name"],
        topic_id=topic["id"],
        topic_name=topic["name"],
        confidence=round(confidence, 2),
        keywords=matched_keywords,
        source="heuristic",
        rationale="Matched topic taxonomy keywords in the extracted question/answer text.",
    )


def render_taxonomy_for_prompt(taxonomy: dict[str, Any] | None) -> str:
    if not taxonomy:
        return "No taxonomy available."
    lines = [f"Subject: {taxonomy.get('subject', 'Unknown')}"]
    for chapter in taxonomy.get("chapters", []):
        lines.append(f"- {chapter['id']}: {chapter['name']}")
        for topic in chapter.get("topics", []):
            keyword_text = ", ".join(topic.get("keywords", [])[:10])
            lines.append(
                f"  - {topic['id']}: {topic['name']} | {topic.get('description', '')} | keywords: {keyword_text}"
            )
    return "\n".join(lines)


def sanitize_section_markdown(text: str, *, section_name: str) -> str:
    lines = [line.rstrip() for line in text.strip().splitlines()]
    cleaned: list[str] = []
    for line in lines:
        if line.strip().startswith("```"):
            continue
        cleaned.append(line)

    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    if cleaned:
        header = cleaned[0].strip().lower().lstrip("#").strip()
        if header == section_name.lower() or header.startswith(section_name.lower() + " "):
            cleaned.pop(0)

    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    return "\n".join(cleaned).strip()


def cleanup_is_safe(raw_text: str, cleaned_text: str) -> bool:
    if not raw_text.strip():
        return not cleaned_text.strip()

    raw_tokens = set(re.findall(r"[a-z0-9]+", raw_text.lower()))
    cleaned_tokens = set(re.findall(r"[a-z0-9]+", cleaned_text.lower()))
    if not raw_tokens or not cleaned_tokens:
        return False

    overlap = len(raw_tokens & cleaned_tokens) / max(1, len(raw_tokens))
    precision = len(raw_tokens & cleaned_tokens) / max(1, len(cleaned_tokens))
    length_ratio = len(cleaned_text) / max(1, len(raw_text))

    return overlap >= 0.75 and precision >= 0.45 and 0.45 <= length_ratio <= 1.85


def extract_markdown_asset_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if (line.strip().startswith("![") and "](" in line) or line.strip().startswith("[[ASSET:")
    ]


def cleanup_preserves_assets(raw_text: str, cleaned_text: str) -> bool:
    raw_assets = extract_markdown_asset_lines(raw_text)
    if not raw_assets:
        return True
    cleaned_assets = extract_markdown_asset_lines(cleaned_text)
    return raw_assets == cleaned_assets


def build_topic_lookup(taxonomy: dict[str, Any] | None) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    lookup: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for chapter, topic in iter_taxonomy_topics(taxonomy):
        lookup[topic["id"]] = (chapter, topic)
    return lookup


def coerce_topic_match_from_llm(
    llm_payload: dict[str, Any],
    taxonomy: dict[str, Any] | None,
    fallback: TopicMatch | None,
) -> TopicMatch | None:
    topic_lookup = build_topic_lookup(taxonomy)
    topic_id = str(llm_payload.get("topic_id", "")).strip()
    chapter_id = str(llm_payload.get("chapter_id", "")).strip()

    if topic_id in topic_lookup:
        chapter, topic = topic_lookup[topic_id]
        confidence_raw = llm_payload.get("confidence", 0.75)
        try:
            confidence = max(0.0, min(1.0, float(confidence_raw)))
        except (TypeError, ValueError):
            confidence = 0.75
        keywords = llm_payload.get("keywords")
        if not isinstance(keywords, list):
            keywords = []
        keywords = [str(item).strip() for item in keywords if str(item).strip()][:8]
        return TopicMatch(
            chapter_id=chapter.get("id", chapter_id or chapter["id"]),
            chapter_name=chapter.get("name", llm_payload.get("chapter_name", "")),
            topic_id=topic.get("id", topic_id),
            topic_name=topic.get("name", llm_payload.get("topic_name", "")),
            confidence=round(confidence, 2),
            keywords=keywords,
            source="llm",
            rationale=str(llm_payload.get("rationale", "")).strip() or None,
        )

    if fallback is not None:
        return fallback

    return None


def enrich_question_record(
    *,
    pair: PaperPair,
    extracted_question: ExtractedQuestionContent,
    answer_text: str,
    llm_mode: str,
    llm_client: MiniMaxClient | None,
    taxonomy: dict[str, Any] | None,
    logger: Callable[[str], None] | None = None,
) -> QuestionRecord:
    question_number = extracted_question.question_number
    question_label = extracted_question.question_label
    question_text = extracted_question.question_text
    emit_log(logger, f"[question] {pair.key} {question_label.upper()} | start")
    heuristic_match = infer_topic_heuristically(question_text, answer_text, taxonomy)
    if heuristic_match is not None:
        emit_log(
            logger,
            f"[question] {pair.key} {question_label.upper()} | heuristic={heuristic_match.topic_id} ({heuristic_match.confidence:.2f})",
        )
    else:
        emit_log(logger, f"[question] {pair.key} {question_label.upper()} | heuristic=none")

    cleaned_question_text = question_text.strip()
    cleaned_answer_text = answer_text.strip()
    final_match = heuristic_match
    llm_applied = False

    if llm_mode != "off":
        if llm_client is None:
            raise RuntimeError("LLM mode was requested but the MiniMax client was not configured.")
        emit_log(logger, f"[question] {pair.key} {question_label.upper()} | llm_mode={llm_mode}")

        if llm_mode == "cleanup-and-tag" and taxonomy is not None:
            prompt_taxonomy, candidate_topic_ids, used_taxonomy_shortlist = shortlist_taxonomy_for_prompt(
                question_text,
                answer_text,
                taxonomy,
            )
            if used_taxonomy_shortlist:
                emit_log(
                    logger,
                    f"[question] {pair.key} {question_label.upper()} | taxonomy_candidates={len(candidate_topic_ids)}/{count_taxonomy_topics(taxonomy)}",
                )
            system_prompt = (
                "You clean extracted exam material into accurate Markdown and classify it against a fixed taxonomy. "
                "Return one JSON object only. Do not use code fences. Do not invent missing content. "
                "Preserve question numbering, subpart labels, marks, and mark-scheme points."
            )
            user_payload = {
                "task": "Clean the extracted question and answer text, then classify the question by chapter/topic.",
                "rules": [
                    "Keep the question wording faithful to the source.",
                    "Remove PDF furniture, repeated headers, page numbers, and obvious extraction noise.",
                    "Format options and mark-scheme points as readable Markdown bullets where appropriate.",
                    "Choose exactly one topic from the provided taxonomy if possible.",
                    "If uncertain, prefer the closest syllabus topic and lower confidence.",
                    "Classify from the question text primarily.",
                    "The answer text must stay faithful to the extracted mark scheme.",
                    "If the answer extraction looks incomplete or noisy, do not repair it from your own knowledge.",
                    "Never reconstruct, invent, or supplement missing answers.",
                ],
                "output_schema": {
                    "cleaned_question_markdown": "string",
                    "cleaned_answer_markdown": "string",
                    "chapter_id": "string",
                    "chapter_name": "string",
                    "topic_id": "string",
                    "topic_name": "string",
                    "confidence": "number between 0 and 1",
                    "keywords": ["short keyword strings"],
                    "rationale": "short explanation",
                },
                "paper": {
                    "paper_key": pair.key,
                    "year": pair.year,
                    "question_label": question_label.upper(),
                },
                "taxonomy": render_taxonomy_for_prompt(prompt_taxonomy),
                "candidate_topic_ids": candidate_topic_ids,
                "question_text": question_text,
                "answer_text": answer_text,
                "heuristic_hint": {
                    "chapter_id": heuristic_match.chapter_id if heuristic_match else None,
                    "chapter_name": heuristic_match.chapter_name if heuristic_match else None,
                    "topic_id": heuristic_match.topic_id if heuristic_match else None,
                    "topic_name": heuristic_match.topic_name if heuristic_match else None,
                },
            }
        else:
            system_prompt = (
                "You clean extracted exam material into accurate Markdown. "
                "Return one JSON object only. Do not use code fences. Do not invent missing content. "
                "Preserve question numbering, subpart labels, marks, and mark-scheme points."
            )
            user_payload = {
                "task": "Clean the extracted question and answer text without adding missing content.",
                "rules": [
                    "Keep the question wording faithful to the source.",
                    "Remove PDF furniture, repeated headers, page numbers, and obvious extraction noise.",
                    "Format options and mark-scheme points as readable Markdown bullets where appropriate.",
                    "The answer text must stay faithful to the extracted mark scheme.",
                    "If the answer extraction looks incomplete or noisy, do not repair it from your own knowledge.",
                    "Never reconstruct, invent, or supplement missing answers.",
                ],
                "output_schema": {
                    "cleaned_question_markdown": "string",
                    "cleaned_answer_markdown": "string",
                },
                "paper": {
                    "paper_key": pair.key,
                    "year": pair.year,
                    "question_label": question_label.upper(),
                },
                "question_text": question_text,
                "answer_text": answer_text,
            }
        llm_payload = llm_client.create_json(
            system_prompt=system_prompt,
            user_prompt=json.dumps(user_payload, ensure_ascii=False, indent=2),
            max_tokens=2800,
            temperature=0.0,
        )
        emit_log(logger, f"[question] {pair.key} {question_label.upper()} | llm json parsed")

        cleaned_question_candidate = sanitize_section_markdown(
            str(llm_payload.get("cleaned_question_markdown", "") or question_text),
            section_name="Question",
        )
        cleaned_answer_candidate = sanitize_section_markdown(
            str(llm_payload.get("cleaned_answer_markdown", "") or answer_text),
            section_name="Answer",
        )

        if (
            cleaned_question_candidate
            and cleanup_is_safe(question_text, cleaned_question_candidate)
            and cleanup_preserves_assets(question_text, cleaned_question_candidate)
        ):
            cleaned_question_text = cleaned_question_candidate.replace("**", "")
        if cleaned_answer_candidate and cleanup_is_safe(answer_text, cleaned_answer_candidate):
            cleaned_answer_text = cleaned_answer_candidate

        if llm_mode == "cleanup-and-tag" and taxonomy is not None:
            final_match = coerce_topic_match_from_llm(llm_payload, taxonomy, heuristic_match)
            if final_match is not None:
                emit_log(
                    logger,
                    f"[question] {pair.key} {question_label.upper()} | final_topic={final_match.topic_id} ({final_match.confidence:.2f}) via {final_match.source}",
                )

        llm_applied = True
    elif heuristic_match is not None:
        emit_log(
            logger,
            f"[question] {pair.key} {question_label.upper()} | final_topic={heuristic_match.topic_id} ({heuristic_match.confidence:.2f}) via heuristic",
        )

    emit_log(logger, f"[question] {pair.key} {question_label.upper()} | done")

    return QuestionRecord(
        question_number=question_number,
        question_label=question_label,
        question_text=cleaned_question_text,
        answer_text=cleaned_answer_text,
        topic_match=final_match,
        llm_applied=llm_applied,
        content_blocks=extracted_question.content_blocks,
        assets=extracted_question.assets,
    )


def build_markdown(pair: PaperPair, record: QuestionRecord) -> str:
    answer_body = record.answer_text.strip() or "_No matching mark scheme text found for this question._"
    lines = [
        f"# {pair.year} {record.question_label.upper()}",
        "",
        f"- Paper key: `{pair.key}`",
        f"- Question paper PDF: `{pair.question_pdf.name}`",
        f"- Mark scheme PDF: `{pair.mark_scheme_pdf.name}`",
    ]

    if record.topic_match is not None:
        keyword_text = ", ".join(record.topic_match.keywords) if record.topic_match.keywords else "n/a"
        lines.extend(
            [
                f"- Chapter: `{record.topic_match.chapter_name}`",
                f"- Topic: `{record.topic_match.topic_name}`",
                f"- Tag confidence: `{record.topic_match.confidence:.2f}`",
                f"- Tag source: `{record.topic_match.source}`",
                f"- Topic keywords: `{keyword_text}`",
            ]
        )

    lines.extend(
        [
            "",
            "## Question",
            "",
            record.question_text.strip(),
            "",
            "## Answer",
            "",
            answer_body,
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(
    output_dir: Path,
    pair: PaperPair,
    records: list[QuestionRecord],
    llm_mode: str,
    llm_provider: str | None,
) -> list[dict[str, Any]]:
    paper_dir = output_dir / pair.year / pair.key
    paper_dir.mkdir(parents=True, exist_ok=True)

    manifest_entries: list[dict[str, Any]] = []
    for record in records:
        target_path = paper_dir / f"{record.question_label}.md"
        target_path.write_text(build_markdown(pair, record), encoding="utf-8")
        blocks_path = paper_dir / f"{record.question_label}.blocks.json"
        blocks_payload = {
            "paper_key": pair.key,
            "year": pair.year,
            "question_label": record.question_label,
            "blocks": list(record.content_blocks),
            "assets": list(record.assets),
        }
        blocks_path.write_text(json.dumps(blocks_payload, indent=2, ensure_ascii=False), encoding="utf-8")

        entry: dict[str, Any] = {
            "year": pair.year,
            "paper_key": pair.key,
            "question_number": str(record.question_number),
            "question_label": record.question_label,
            "markdown_path": str(target_path),
            "blocks_path": str(blocks_path),
            "question_pdf": str(pair.question_pdf),
            "mark_scheme_pdf": str(pair.mark_scheme_pdf),
            "llm_mode": llm_mode,
            "llm_provider": llm_provider,
            "llm_applied": record.llm_applied,
            "asset_count": len(record.assets),
            "assets": list(record.assets),
        }
        if record.topic_match is not None:
            entry.update(
                {
                    "chapter_id": record.topic_match.chapter_id,
                    "chapter_name": record.topic_match.chapter_name,
                    "topic_id": record.topic_match.topic_id,
                    "topic_name": record.topic_match.topic_name,
                    "tag_confidence": record.topic_match.confidence,
                    "tagging_source": record.topic_match.source,
                    "keywords": record.topic_match.keywords,
                    "tagging_rationale": record.topic_match.rationale,
                }
            )
        context_text = normalize_context_text(record.question_text)
        for asset in entry["assets"]:
            asset["context_text"] = context_text
        manifest_entries.append(entry)
    return manifest_entries


def write_topic_indexes(output_dir: Path, manifest: list[dict[str, Any]], subject: str) -> None:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for entry in manifest:
        chapter_name = entry.get("chapter_name") or "Unclassified"
        topic_name = entry.get("topic_name") or "Unclassified"
        grouped[chapter_name][topic_name].append(entry)

    grouped_json: dict[str, Any] = {
        "subject": subject,
        "chapters": [],
    }
    markdown_lines = [f"# Topic Index", "", f"Subject: `{subject}`", ""]

    for chapter_name in sorted(grouped):
        grouped_json["chapters"].append(
            {
                "chapter_name": chapter_name,
                "topics": [
                    {
                        "topic_name": topic_name,
                        "questions": sorted(
                            grouped[chapter_name][topic_name],
                            key=lambda entry: (
                                entry.get("year", ""),
                                entry.get("paper_key", ""),
                                entry.get("question_label", ""),
                            ),
                        ),
                    }
                    for topic_name in sorted(grouped[chapter_name])
                ],
            }
        )
        markdown_lines.append(f"## {chapter_name}")
        markdown_lines.append("")
        for topic_name in sorted(grouped[chapter_name]):
            markdown_lines.append(f"### {topic_name}")
            markdown_lines.append("")
            for entry in sorted(
                grouped[chapter_name][topic_name],
                key=lambda item: (item.get("year", ""), item.get("paper_key", ""), item.get("question_label", "")),
            ):
                markdown_lines.append(
                    f"- {entry['year']} {entry['question_label'].upper()} | {entry['paper_key']} | {entry['markdown_path']}"
                )
            markdown_lines.append("")

    (output_dir / "topic_index.json").write_text(
        json.dumps(grouped_json, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "topic_index.md").write_text("\n".join(markdown_lines).rstrip() + "\n", encoding="utf-8")


def write_asset_manifest(output_dir: Path, manifest: list[dict[str, Any]]) -> Path:
    assets: list[dict[str, Any]] = []
    for entry in manifest:
        for asset in entry.get("assets", []):
            asset_payload = dict(asset)
            asset_payload["paper_key"] = entry.get("paper_key")
            asset_payload["year"] = entry.get("year")
            assets.append(asset_payload)

    asset_manifest_path = output_dir / "asset_manifest.json"
    asset_manifest_path.write_text(json.dumps(assets, indent=2, ensure_ascii=False), encoding="utf-8")
    return asset_manifest_path


def build_embedding_engine(args: argparse.Namespace, logger: Callable[[str], None] | None = None) -> Any | None:
    if getattr(args, "embedding_mode", "off") == "off":
        emit_log(logger, "[embed] disabled")
        return None
    if SentenceTransformer is None or Image is None or np is None:
        emit_log(logger, "[embed] sentence-transformers or PIL or numpy missing, embeddings disabled")
        return None
    emit_log(logger, f"[embed] loading model {args.embedding_model}")
    model = SentenceTransformer(args.embedding_model)
    emit_log(logger, f"[embed] model ready {args.embedding_model}")
    return model


def cosine_similarity_matrix(vectors: np.ndarray) -> np.ndarray:
    return np.matmul(vectors, vectors.T)


def normalize_context_text(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[[ASSET:"):
            continue
        if stripped.startswith("![") and "](" in stripped:
            continue
        lines.append(stripped)
    return "\n".join(lines).strip()


def build_duplicate_groups(
    assets: list[dict[str, Any]],
    image_vectors: np.ndarray,
    threshold: float = 0.985,
) -> list[list[int]]:
    if len(assets) < 2:
        return []
    similarities = cosine_similarity_matrix(image_vectors)
    parent = list(range(len(assets)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a: int, b: int) -> None:
        root_a = find(a)
        root_b = find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    for i in range(len(assets)):
        for j in range(i + 1, len(assets)):
            if float(similarities[i, j]) >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = defaultdict(list)
    for index in range(len(assets)):
        groups[find(index)].append(index)
    return [group for group in groups.values() if len(group) > 1]


def write_embedding_outputs(
    output_dir: Path,
    assets: list[dict[str, Any]],
    args: argparse.Namespace,
    logger: Callable[[str], None] | None = None,
) -> tuple[Path | None, list[dict[str, Any]]]:
    embedding_engine = build_embedding_engine(args, logger=logger)
    if embedding_engine is None or not assets or np is None or Image is None:
        return None, []

    image_inputs = []
    text_inputs = []
    context_inputs = []
    valid_assets: list[dict[str, Any]] = []
    for asset in assets:
        asset_path = Path(asset["path"])
        if not asset_path.exists():
            continue
        valid_assets.append(asset)
        with Image.open(asset_path) as image:
            image_inputs.append(image.convert("RGB").copy())
        combined_text = "\n".join(part for part in [asset.get("asset_text", ""), asset.get("ocr_text", "")] if part).strip()
        text_inputs.append(combined_text or "")
        context_inputs.append(asset.get("context_text", "") or "")

    if not valid_assets:
        return None, []

    emit_log(logger, f"[embed] encoding assets count={len(valid_assets)}")
    image_vectors = embedding_engine.encode(image_inputs, convert_to_numpy=True, normalize_embeddings=True)
    text_vectors = embedding_engine.encode(text_inputs, convert_to_numpy=True, normalize_embeddings=True)
    context_vectors = embedding_engine.encode(context_inputs, convert_to_numpy=True, normalize_embeddings=True)

    embedding_dir = output_dir / "_embeddings"
    embedding_dir.mkdir(parents=True, exist_ok=True)
    np.save(embedding_dir / "image_vectors.npy", image_vectors.astype("float32"))
    np.save(embedding_dir / "ocr_text_vectors.npy", text_vectors.astype("float32"))
    np.save(embedding_dir / "context_vectors.npy", context_vectors.astype("float32"))

    duplicate_groups = build_duplicate_groups(valid_assets, image_vectors)
    duplicate_report: list[dict[str, Any]] = []
    for group_index, group in enumerate(duplicate_groups, start=1):
        duplicate_report.append(
            {
                "group_id": f"dup_{group_index:03d}",
                "asset_ids": [valid_assets[index]["asset_id"] for index in group],
            }
        )

    manifest_entries: list[dict[str, Any]] = []
    for index, asset in enumerate(valid_assets):
        manifest_entries.append(
            {
                "asset_id": asset["asset_id"],
                "image_vector_index": index,
                "ocr_text_vector_index": index,
                "context_vector_index": index,
                "question_label": asset.get("question_label"),
                "paper_key": asset.get("paper_key"),
                "path": asset.get("path"),
            }
        )

    embedding_manifest_path = embedding_dir / "asset_embeddings_manifest.json"
    embedding_manifest_path.write_text(
        json.dumps(
            {
                "model": args.embedding_model,
                "mode": args.embedding_mode,
                "count": len(valid_assets),
                "entries": manifest_entries,
                "duplicate_groups": duplicate_report,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    emit_log(logger, f"[embed] wrote embeddings manifest {embedding_manifest_path}")
    return embedding_manifest_path, duplicate_report


def write_validation_report(
    output_dir: Path,
    manifest: list[dict[str, Any]],
    duplicate_groups: list[dict[str, Any]],
) -> Path:
    questions_total = len(manifest)
    assets_total = sum(int(entry.get("asset_count", 0)) for entry in manifest)
    questions_without_assets = [entry["question_label"] for entry in manifest if int(entry.get("asset_count", 0)) == 0]
    assets_missing_ocr = []
    suspicious_assets = []

    for entry in manifest:
        for asset in entry.get("assets", []):
            ocr_text = str(asset.get("ocr_text", "") or "").strip()
            if not ocr_text:
                assets_missing_ocr.append(asset["asset_id"])
            width = int(asset.get("width", 0) or 0)
            height = int(asset.get("height", 0) or 0)
            if width < 120 or height < 60:
                suspicious_assets.append({"asset_id": asset["asset_id"], "reason": "too_small"})
            if width > 1600 or height > 1600:
                suspicious_assets.append({"asset_id": asset["asset_id"], "reason": "very_large"})

    validation = {
        "questions_total": questions_total,
        "assets_total": assets_total,
        "questions_without_assets": questions_without_assets,
        "assets_missing_ocr_text": assets_missing_ocr,
        "duplicate_groups": duplicate_groups,
        "suspicious_assets": suspicious_assets,
    }

    validation_report_path = output_dir / "validation_report.json"
    validation_report_path.write_text(json.dumps(validation, indent=2, ensure_ascii=False), encoding="utf-8")
    return validation_report_path


def build_minimax_client(args: argparse.Namespace, logger: Callable[[str], None] | None = None) -> MiniMaxClient:
    config = MiniMaxConfig.from_sources(
        api_key=args.minimax_api_key,
        base_url=args.minimax_base_url,
        model=args.minimax_model,
        timeout_ms=args.api_timeout_ms,
    )
    return MiniMaxClient(config, logger=logger)


def maybe_create_minimax_client(
    args: argparse.Namespace,
    logger: Callable[[str], None] | None = None,
    *,
    force: bool = False,
) -> MiniMaxClient | None:
    if args.llm_mode == "off" and not force:
        return None
    return build_minimax_client(args, logger=logger)


def resolve_taxonomy_plan(
    args: argparse.Namespace,
    input_dir: Path,
    profile: ParserProfile,
) -> tuple[str, Path | None, bool, bool]:
    requested_mode = getattr(args, "taxonomy_mode", DEFAULT_TAXONOMY_MODE)
    auto_taxonomy_path = derive_auto_taxonomy_path(input_dir)
    if args.taxonomy_file is not None:
        return requested_mode, resolve_path(args.taxonomy_file), False, True

    if requested_mode == "static":
        return requested_mode, profile.taxonomy_file, False, profile.taxonomy_file is not None

    if requested_mode == "auto-draft":
        if profile.taxonomy_file is not None:
            return requested_mode, profile.taxonomy_file, False, True
        return requested_mode, auto_taxonomy_path, True, False

    if profile.taxonomy_file is not None:
        return requested_mode, profile.taxonomy_file, False, True
    if auto_taxonomy_path.exists():
        return requested_mode, auto_taxonomy_path, False, False
    if args.llm_mode == "cleanup-and-tag":
        return requested_mode, auto_taxonomy_path, True, False
    return requested_mode, None, False, False


def convert_folder(
    args: argparse.Namespace,
    input_dir: Path,
    output_dir: Path,
    logger: Callable[[str], None] | None = None,
) -> ConversionSummary:
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")

    profile_path = resolve_path(args.profile_file)
    profile = load_profile(profile_path)
    set_active_profile(profile)
    emit_log(logger, f"[run] profile={profile.name} | file={profile_path}")

    emit_log(logger, f"[run] scanning pdf folder {input_dir}")
    pairs, skipped_messages = discover_pairs(input_dir, args.paper_filter)
    if args.limit is not None:
        pairs = pairs[: args.limit]
        emit_log(logger, f"[run] applying limit={args.limit}")

    if not pairs:
        raise ValueError("No paired question paper / mark scheme PDFs were found.")

    taxonomy_mode, taxonomy_path, should_generate_taxonomy, missing_taxonomy_is_error = resolve_taxonomy_plan(
        args,
        input_dir,
        profile,
    )
    taxonomy: dict[str, Any] | None
    if taxonomy_path is None:
        taxonomy = None
        emit_log(logger, "[run] taxonomy=none")
    elif taxonomy_path.exists():
        taxonomy = load_taxonomy(taxonomy_path)
        emit_log(logger, f"[run] taxonomy={taxonomy_path}")
    elif should_generate_taxonomy:
        emit_log(logger, f"[run] taxonomy draft target={taxonomy_path}")
        taxonomy_client = maybe_create_minimax_client(args, logger=logger, force=True)
        if taxonomy_client is None:
            raise RuntimeError("Auto-draft taxonomy mode requires a configured MiniMax client.")
        taxonomy = generate_taxonomy_draft(
            input_dir=input_dir,
            taxonomy_path=taxonomy_path,
            pairs=pairs,
            llm_client=taxonomy_client,
            logger=logger,
        )
    elif missing_taxonomy_is_error:
        raise FileNotFoundError(f"Taxonomy file does not exist: {taxonomy_path}")
    else:
        taxonomy = None
        emit_log(logger, "[run] taxonomy=none")

    effective_llm_mode = args.llm_mode
    if taxonomy is None and effective_llm_mode == "cleanup-and-tag":
        effective_llm_mode = "cleanup"
        emit_log(logger, "[run] taxonomy unavailable, downgrading llm_mode from cleanup-and-tag to cleanup")

    runtime_args = argparse.Namespace(**vars(args))
    runtime_args.llm_mode = effective_llm_mode

    emit_log(logger, f"[run] llm_mode={effective_llm_mode}")
    emit_log(logger, f"[run] taxonomy_mode={taxonomy_mode}")
    emit_log(logger, f"[run] ocr_mode={getattr(runtime_args, 'ocr_mode', 'off')}")
    llm_client = maybe_create_minimax_client(runtime_args, logger=logger)
    ocr_engine = build_ocr_engine(runtime_args, logger=logger)

    output_dir.mkdir(parents=True, exist_ok=True)
    emit_log(logger, f"[run] output folder ready {output_dir}")
    emit_log(logger, f"[run] paired papers found={len(pairs)}")

    manifest: list[dict[str, Any]] = []
    processed_count = 0
    for pair_index, pair in enumerate(pairs, start=1):
        emit_log(
            logger,
            f"[paper] {pair_index}/{len(pairs)} | {pair.key} | qp={pair.question_pdf.name} | ms={pair.mark_scheme_pdf.name}",
        )
        emit_log(logger, f"[paper] {pair.key} | extracting question paper")
        extracted_questions = extract_question_paper_with_assets(
            pair,
            output_dir,
            ocr_engine=ocr_engine,
            allow_page_ocr_fallback=getattr(args, "ocr_page_fallback", False),
            logger=logger,
        )
        emit_log(logger, f"[paper] {pair.key} | extracting mark scheme")
        answer_blocks = split_mark_scheme(pair.mark_scheme_pdf)
        emit_log(
            logger,
            f"[paper] {pair.key} | questions={len(extracted_questions)} | answer_blocks={len(answer_blocks)}",
        )
        if not extracted_questions:
            skipped_messages.append(f"No questions extracted from {pair.question_pdf.name}")
            emit_log(logger, f"[paper] {pair.key} | no questions extracted")
            continue

        records: list[QuestionRecord] = []
        for extracted_question in extracted_questions:
            raw_answer_text = answer_blocks.get(extracted_question.question_number, "")
            try:
                record = enrich_question_record(
                    pair=pair,
                    extracted_question=extracted_question,
                    answer_text=raw_answer_text,
                    llm_mode=effective_llm_mode,
                    llm_client=llm_client,
                    taxonomy=taxonomy,
                    logger=logger,
                )
            except Exception as exc:
                skipped_messages.append(
                    f"LLM enrichment failed for {pair.key} question {extracted_question.question_number}: {exc}. Falling back to raw text."
                )
                emit_log(
                    logger,
                    f"[question] {pair.key} {extracted_question.question_label.upper()} | error={exc} | fallback=raw",
                )
                record = QuestionRecord(
                    question_number=extracted_question.question_number,
                    question_label=extracted_question.question_label,
                    question_text=extracted_question.question_text.strip(),
                    answer_text=raw_answer_text.strip(),
                    topic_match=infer_topic_heuristically(extracted_question.question_text, raw_answer_text, taxonomy),
                    llm_applied=False,
                    content_blocks=extracted_question.content_blocks,
                    assets=extracted_question.assets,
                )
            records.append(record)

        manifest.extend(
            write_outputs(
                output_dir=output_dir,
                pair=pair,
                records=records,
                llm_mode=effective_llm_mode,
                llm_provider=args.llm_provider if llm_client else None,
            )
        )
        processed_count += 1
        emit_log(logger, f"[paper] {pair.key} | wrote {len(records)} markdown files")

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    write_topic_indexes(output_dir, manifest, taxonomy.get("subject", profile.name) if taxonomy else profile.name)
    asset_manifest_path = write_asset_manifest(output_dir, manifest)
    embedding_manifest_path, duplicate_groups = write_embedding_outputs(
        output_dir,
        json.loads(asset_manifest_path.read_text(encoding="utf-8")),
        runtime_args,
        logger=logger,
    )
    validation_report_path = write_validation_report(output_dir, manifest, duplicate_groups)
    emit_log(logger, f"[run] manifest written {manifest_path}")
    emit_log(logger, f"[run] topic index written {output_dir / 'topic_index.json'}")
    emit_log(logger, f"[run] asset manifest written {asset_manifest_path}")
    emit_log(logger, f"[run] validation report written {validation_report_path}")
    if embedding_manifest_path is not None:
        emit_log(logger, f"[run] embedding manifest written {embedding_manifest_path}")
    emit_log(logger, f"[run] completed | processed={processed_count} | markdowns={len(manifest)}")

    return ConversionSummary(
        input_dir=input_dir,
        output_dir=output_dir,
        processed_count=processed_count,
        generated_files=len(manifest),
        manifest_path=manifest_path,
        topic_index_path=output_dir / "topic_index.json",
        asset_manifest_path=asset_manifest_path,
        validation_report_path=validation_report_path,
        embedding_manifest_path=embedding_manifest_path,
        skipped_messages=skipped_messages,
    )


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    env_file = DEFAULT_ENV_FILE
    for index, token in enumerate(sys.argv[1:]):
        if token == "--env-file" and index + 2 <= len(sys.argv[1:]):
            env_file = Path(sys.argv[1:][index + 1])
            break
        if token.startswith("--env-file="):
            env_file = Path(token.split("=", 1)[1])
            break
    load_env_file(env_file)

    args = parse_args()
    if args.menu or (is_tty_session() and len(sys.argv) == 1):
        return launch_menu(args)

    runtime = resolve_runtime_options(args)
    input_dir: Path = runtime.input_dir
    output_dir: Path = runtime.output_dir
    args.llm_mode = runtime.llm_mode
    args.profile_file = runtime.profile_file

    summary = convert_folder(args, input_dir, output_dir)
    print(f"Processed paired papers: {summary.processed_count}")
    print(f"Generated markdown files: {summary.generated_files}")
    print(f"Manifest: {summary.manifest_path}")
    print(f"Topic index: {summary.topic_index_path}")
    print(f"Asset manifest: {summary.asset_manifest_path}")
    print(f"Validation report: {summary.validation_report_path}")
    if summary.embedding_manifest_path is not None:
        print(f"Embedding manifest: {summary.embedding_manifest_path}")
    if summary.skipped_messages:
        print("Notes:")
        for message in summary.skipped_messages:
            print(f"- {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
