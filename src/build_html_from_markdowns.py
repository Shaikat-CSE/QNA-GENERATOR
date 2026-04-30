from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
from dataclasses import dataclass
from html import escape, unescape
from pathlib import Path
from typing import Any


SITE_ASSETS_DIR = Path(__file__).resolve().parent / "site_assets"
DEFAULT_SITE_ASSETS_SUBDIR = "_site_assets"
ASSET_PLACEHOLDER_RE = re.compile(r"^\[\[ASSET:[^\]]+\]\]\s*$")
IMAGE_LINE_RE = re.compile(r"^!\[(?P<alt>[^\]]*)\]\((?P<src>[^)]+)\)\s*$")
ORDERED_LIST_RE = re.compile(r"^(?P<number>\d+)[.)]\s+(?P<body>.+)$")
UNORDERED_LIST_RE = re.compile(r"^[-*•]\s+(?P<body>.+)$")
THEMATIC_BREAK_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")
BLOCKQUOTE_RE = re.compile(r"^>\s?(?P<body>.*)$")
CODE_FENCE_RE = re.compile(r"^```")
QUESTION_OPTION_RE = re.compile(r"^(?P<label>[A-H])(?P<body>[A-Z0-9].+)$")
QUESTION_SUBPART_RE = re.compile(r"^(?P<label>\((?:[a-z]|[ivx]+)\))\s*(?P<body>.+)?$", re.IGNORECASE)
MAJOR_SUBPART_RE = re.compile(r"^\((?P<label>[a-z])\)\s*(?P<body>.+)?$", re.IGNORECASE)
QUESTION_MARKS_RE = re.compile(r"^\((?P<marks>\d+)\)$")
QUESTION_RESPONSE_LINE_RE = re.compile(r"^(?P<label>\d+)\.{8,}$")
TOP_LEVEL_QUESTION_RE = re.compile(r"^(?P<number>\d{1,2})\s+(?P<body>.+)$")
ANSWER_PART_RE = re.compile(r"^(?P<label>\d+\((?:[a-z]|[ivx]+)\))\s*(?P<body>.+)?$", re.IGNORECASE)
ANSWER_GROUP_LABEL_RE = re.compile(r"^(?P<label>[A-Z][A-Za-z0-9'’/() -]{1,40}):$")
INLINE_CODE_RE = re.compile(r"`([^`]+)`")
INLINE_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
INLINE_ITALIC_RE = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)|_([^_]+)_")
INLINE_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
QUESTION_LABEL_RE = re.compile(r"^q(?P<number>\d+)(?P<part>[a-z]?)$", re.IGNORECASE)
PSEUDOCODE_LINE_RE = re.compile(
    r"^(?:WHILE|IF|ELSE|ELSEIF|END IF|END WHILE|END FOR|FOR|REPEAT|UNTIL|CASE|SET|SEND|PRINT|INPUT|OUTPUT|RETURN|FUNCTION|PROCEDURE|DECLARE|OPENFILE|READFILE|WRITEFILE|CLOSEFILE)\b",
    re.IGNORECASE,
)
METADATA_LINE_RE = re.compile(r"^- (?P<label>[^:]+):\s*(?P<value>.+)$")
NUMBER_WORDS_RE = r"(?:one|two|three|four|five|six|seven|eight|nine|ten)"
COMMAND_WORDS_RE = r"(?:State|Name|Give|Write|Identify|Complete|Describe|Explain|Justify|Compare|Calculate|Construct|Define|Suggest|Choose)"


@dataclass(frozen=True)
class ParsedMarkdown:
    title: str
    question_markdown: str
    answer_markdown: str


@dataclass(frozen=True)
class SiteQuestion:
    entry: dict[str, Any]
    title: str
    question_html: str
    answer_html: str
    preview_text: str
    markdown_path: Path
    html_path: Path
    paper_index_path: Path
    year_index_path: Path
    chapter_name: str
    topic_name: str
    topic_slug: str
    chapter_slug: str
    search_text: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a static HTML site from converted exam markdown output."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Converted markdown output directory containing manifest.json and generated markdown files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for generated HTML site. Default: <input-dir>_site",
    )
    parser.add_argument(
        "--site-title",
        type=str,
        default=None,
        help="Optional site title override.",
    )
    parser.add_argument(
        "--image-mode",
        choices=("linked", "embed"),
        default="linked",
        help="Use copied image files by default, or embed figures inline as base64 data URIs.",
    )
    parser.add_argument(
        "--html-theme",
        choices=("modern", "pdf"),
        default="modern",
        help="HTML theme: modern (default, web-friendly) or pdf (compact exam paper style).",
    )
    return parser.parse_args()


def resolve_output_dir(input_dir: Path, output_dir: Path | None) -> Path:
    if output_dir is not None:
        return output_dir
    return input_dir.parent / f"{input_dir.name}_site"


def resolve_manifest_path(input_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = [
        input_dir / path,
        input_dir.parent / path,
        Path.cwd() / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return (input_dir / path).resolve()


def question_sort_key(entry: dict[str, Any]) -> tuple[int, str]:
    label = str(entry.get("question_label", "")).lower()
    match = QUESTION_LABEL_RE.match(label)
    if match:
        part = match.group("part") or ""
        return int(match.group("number")), part
    try:
        return int(entry.get("question_number", 0)), label
    except (TypeError, ValueError):
        return 0, label


def slugify(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    return lowered.strip("-") or "untitled"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def escape_text(text: str) -> str:
    return escape(text, quote=False)


def mime_type_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".gif":
        return "image/gif"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".svg":
        return "image/svg+xml"
    return "application/octet-stream"


def path_to_data_uri(path: Path) -> str:
    mime_type = mime_type_for_path(path)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def parse_metadata_value(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("`") and stripped.endswith("`") and len(stripped) >= 2:
        return stripped[1:-1]
    return stripped


def repair_display_artifacts(text: str) -> str:
    text = text.replace("\ufffc", " ").replace("\u02c7", "'")
    text = re.sub(r"[\ue000-\uf8ff]", " ", text)
    text = re.sub(rf"\b({COMMAND_WORDS_RE})(?={NUMBER_WORDS_RE}\b)", r"\1 ", text)
    text = re.sub(rf"\bto(?={NUMBER_WORDS_RE}\b)", "to ", text)
    text = re.sub(rf"\bthese(?={NUMBER_WORDS_RE}\b)", "these ", text, flags=re.IGNORECASE)
    text = re.sub(rf"\bthe(?={NUMBER_WORDS_RE}\b)", "the ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bdo ?not ?need\b", "do not need", text, flags=re.IGNORECASE)
    text = re.sub(r"\bin(?=Figure\s*\d+\b)", "in ", text)
    return text


def parse_markdown_header_metadata(path: Path) -> dict[str, str]:
    metadata: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "## Question":
            break
        match = METADATA_LINE_RE.match(stripped)
        if not match:
            continue
        label = match.group("label").strip().lower().replace(" ", "_")
        metadata[label] = parse_metadata_value(match.group("value"))
    return metadata


def maybe_resolve_pdf_path(input_dir: Path, filename: str) -> str:
    if not filename:
        return ""
    sibling_past_papers = input_dir.parent / "past-papers" / filename
    if sibling_past_papers.exists():
        return str(sibling_past_papers.resolve())
    return filename


def split_table_cells(line: str) -> list[str]:
    trimmed = line.strip().strip("|")
    return [cell.strip() for cell in trimmed.split("|")]


def is_table_row(line: str) -> bool:
    stripped = line.strip()
    return "|" in stripped and not IMAGE_LINE_RE.match(stripped)


def is_pseudocode_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if PSEUDOCODE_LINE_RE.match(stripped):
        return True
    return bool(re.search(r"\b(?:THEN|DO|TRUE|FALSE)\b|\[[^\]]+\]|\bLENGTH\s*\(", stripped, re.IGNORECASE))


def is_question_task_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("(") or stripped.startswith("[[ASSET:") or stripped.startswith("!["):
        return False
    if stripped.startswith("Figure "):
        return False
    if QUESTION_OPTION_RE.match(stripped):
        return False
    return stripped[0].islower()


def render_question_options_html(option_lines: list[str]) -> str:
    items: list[str] = []
    for line in option_lines:
        match = QUESTION_OPTION_RE.match(line.strip())
        assert match is not None
        label = match.group("label")
        body = match.group("body").strip()
        items.append(
            '<li class="question-option-item">'
            f'<span class="question-option-label">{escape(label)}</span>'
            f'<span class="question-option-body">{render_inline_markdown(body)}</span>'
            "</li>"
        )
    return '<ul class="question-option-list">' + "".join(items) + "</ul>"


def subpart_level(label: str) -> str:
    inner = label.strip()[1:-1].lower()
    if re.fullmatch(r"[ivx]+", inner):
        return "minor"
    return "major"


def collect_question_task_lines(lines: list[str], start_index: int) -> tuple[list[str], int]:
    collected: list[str] = []
    index = start_index
    while index < len(lines):
        candidate = lines[index].strip()
        if not candidate:
            index += 1
            continue
        if is_question_task_line(candidate):
            collected.append(candidate)
            index += 1
            continue
        break
    return collected, index


def looks_like_question_field_label(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("(") or stripped.startswith("Figure "):
        return False
    if QUESTION_OPTION_RE.match(stripped):
        return False
    if QUESTION_MARKS_RE.match(stripped):
        return False
    if len(stripped) > 40:
        return False
    if stripped.endswith(".") or stripped.endswith(":"):
        return False
    words = stripped.split()
    if not words:
        return False
    if len(words) > 6:
        return False
    capitalized_words = sum(1 for word in words if word[:1].isupper() or word.isupper())
    return capitalized_words >= 1


def render_question_fields_html(labels: list[str]) -> str:
    items = []
    for label in labels:
        items.append(
            '<div class="question-field-card">'
            f'<div class="question-field-label">{render_inline_markdown(label.strip())}</div>'
            '<div class="question-field-blank"></div>'
            "</div>"
        )
    return '<div class="question-field-grid">' + "".join(items) + "</div>"


def collect_question_label_cluster(lines: list[str], start_index: int) -> tuple[list[str], int]:
    labels: list[str] = []
    index = start_index
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        if looks_like_question_field_label(stripped):
            combined = stripped
            cursor = index + 1
            while cursor < len(lines):
                continuation = lines[cursor].strip()
                if not continuation:
                    break
                if (
                    continuation.startswith("(")
                    or continuation.startswith("Figure ")
                    or QUESTION_OPTION_RE.match(continuation)
                    or QUESTION_MARKS_RE.match(continuation)
                    or looks_like_question_field_label(continuation)
                ):
                    break
                combined += " " + continuation
                cursor += 1
            labels.append(combined)
            index = cursor
            continue
        break
    return labels, index


def looks_like_matrix_header_label(label: str) -> bool:
    words = label.split()
    return 1 <= len(words) <= 3 and all(len(word) <= 16 for word in words)


def looks_like_matrix_row_label(label: str) -> bool:
    return len(label) <= 80 and len(label.split()) >= 2


def render_question_matrix_html(headers: list[str], row_labels: list[str]) -> str:
    body_html = []
    for row_label in row_labels:
        cells = "<td>" + render_inline_markdown(row_label) + "</td>" + "".join(
            '<td><div class="question-matrix-blank"></div></td>' for _ in headers
        )
        body_html.append(f"<tr>{cells}</tr>")
    header_html = "<th></th>" + "".join(f"<th>{render_inline_markdown(cell)}</th>" for cell in headers)
    return (
        '<div class="table-wrap"><table class="markdown-table question-matrix-table">'
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(body_html)}</tbody>"
        "</table></div>"
    )


def render_table_html(table_lines: list[str]) -> str:
    header_cells = split_table_cells(table_lines[0])
    body_lines = table_lines[2:] if len(table_lines) >= 2 and TABLE_SEPARATOR_RE.match(table_lines[1]) else table_lines[1:]
    header_html = "".join(f"<th>{render_inline_markdown(cell)}</th>" for cell in header_cells)
    body_rows: list[str] = []
    for line in body_lines:
        row_cells = split_table_cells(line)
        body_rows.append("<tr>" + "".join(f"<td>{render_inline_markdown(cell)}</td>" for cell in row_cells) + "</tr>")
    return (
        '<div class="table-wrap"><table class="markdown-table">'
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table></div>"
    )


def parse_question_markdown(path: Path) -> ParsedMarkdown:
    lines = path.read_text(encoding="utf-8").splitlines()
    title = path.stem.upper()
    question_index: int | None = None
    answer_index: int | None = None

    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("# ") and index == 0:
            title = stripped[2:].strip()
        elif stripped == "## Question":
            question_index = index
        elif stripped == "## Answer":
            answer_index = index

    if question_index is None:
        raise ValueError(f"Question section not found in {path}")
    if answer_index is None or answer_index <= question_index:
        raise ValueError(f"Answer section not found in {path}")

    question_markdown = "\n".join(lines[question_index + 1 : answer_index]).strip()
    answer_markdown = "\n".join(lines[answer_index + 1 :]).strip()
    return ParsedMarkdown(title=title, question_markdown=question_markdown, answer_markdown=answer_markdown)




def build_entries_from_filesystem(input_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for markdown_path in sorted(input_dir.rglob("*.md")):
        if markdown_path.name.lower() == "topic_index.md":
            continue
        relative_parts = markdown_path.relative_to(input_dir).parts
        if len(relative_parts) < 3:
            continue
        year = relative_parts[0]
        paper_key = relative_parts[1]
        question_label = markdown_path.stem
        blocks_path = markdown_path.with_suffix(".blocks.json")
        metadata = parse_markdown_header_metadata(markdown_path)
        blocks_payload: dict[str, Any] = {}
        if blocks_path.exists():
            blocks_payload = read_json(blocks_path)

        question_pdf_name = metadata.get("question_paper_pdf", "")
        mark_scheme_pdf_name = metadata.get("mark_scheme_pdf", "")
        confidence_value = metadata.get("tag_confidence")
        try:
            tag_confidence: float | None = float(confidence_value) if confidence_value not in {None, "", "n/a"} else None
        except ValueError:
            tag_confidence = None

        entries.append(
            {
                "year": blocks_payload.get("year", year),
                "paper_key": blocks_payload.get("paper_key", paper_key),
                "question_number": metadata.get("question_number", ""),
                "question_label": blocks_payload.get("question_label", question_label),
                "markdown_path": str(markdown_path),
                "blocks_path": str(blocks_path) if blocks_path.exists() else "",
                "question_pdf": maybe_resolve_pdf_path(input_dir, question_pdf_name),
                "mark_scheme_pdf": maybe_resolve_pdf_path(input_dir, mark_scheme_pdf_name),
                "llm_mode": None,
                "llm_provider": None,
                "llm_applied": None,
                "asset_count": len(blocks_payload.get("assets", [])),
                "assets": list(blocks_payload.get("assets", [])),
                "chapter_name": metadata.get("chapter", "Unclassified"),
                "topic_name": metadata.get("topic", "Unclassified"),
                "tag_confidence": tag_confidence,
                "tagging_source": metadata.get("tag_source"),
                "keywords": [item.strip() for item in metadata.get("topic_keywords", "").split(",") if item.strip()],
            }
        )
    if not entries:
        raise FileNotFoundError(f"No question markdown files found under: {input_dir}")
    return entries


def render_inline_markdown(text: str) -> str:
    rendered = escape_text(text)
    rendered = INLINE_CODE_RE.sub(lambda match: f"<code>{escape_text(unescape(match.group(1)))}</code>", rendered)
    rendered = INLINE_BOLD_RE.sub(lambda match: f"<strong>{escape_text(unescape(match.group(1)))}</strong>", rendered)
    rendered = INLINE_ITALIC_RE.sub(
        lambda match: f"<em>{escape_text(unescape(match.group(1) or match.group(2) or ''))}</em>",
        rendered,
    )
    rendered = INLINE_LINK_RE.sub(
        lambda match: f'<a href="{escape(unescape(match.group(2)), quote=True)}">{escape_text(unescape(match.group(1)))}</a>',
        rendered,
    )
    return rendered


def normalize_markdown_text(text: str) -> str:
    kept_lines: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if ASSET_PLACEHOLDER_RE.match(stripped):
            continue
        if stripped.startswith("!["):
            kept_lines.append(raw_line.rstrip())
        else:
            kept_lines.append(repair_display_artifacts(raw_line.rstrip()))
    return "\n".join(kept_lines).strip()


def markdown_to_plain_text(text: str) -> str:
    lines: list[str] = []
    for raw_line in normalize_markdown_text(text).splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        image_match = IMAGE_LINE_RE.match(stripped)
        if image_match:
            continue
        bullet_match = re.match(r"^[-*•]\s+(.+)$", stripped)
        if bullet_match:
            stripped = bullet_match.group(1)
        stripped = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", stripped)
        stripped = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", stripped)
        stripped = stripped.replace("**", "").replace("*", "").replace("`", "")
        if stripped:
            lines.append(stripped)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def preview_text(text: str, limit: int = 180) -> str:
    normalized = markdown_to_plain_text(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def render_markdown_fragment(text: str, asset_lookup: dict[str, dict[str, Any]], *, mode: str = "default") -> str:
    html_parts: list[str] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []
    list_tag: str | None = None
    blockquote_lines: list[str] = []
    code_lines: list[str] = []
    in_fenced_code = False
    lines = normalize_markdown_text(text).splitlines()
    index = 0
    rendered_question_stem = False

    def flush_paragraph() -> None:
        nonlocal rendered_question_stem
        if not paragraph_lines:
            return
        body = "<br>".join(render_inline_markdown(line) for line in paragraph_lines)
        first_line = paragraph_lines[0].strip()
        top_level_match = TOP_LEVEL_QUESTION_RE.match(first_line)
        if mode == "question" and not rendered_question_stem and top_level_match:
            remainder_lines = [top_level_match.group("body"), *paragraph_lines[1:]]
            remainder_body = "<br>".join(render_inline_markdown(line) for line in remainder_lines if line)
            html_parts.append(
                '<div class="question-heading">'
                f'<span class="question-number-chip">{escape(top_level_match.group("number"))}</span>'
                f'<div class="question-primary-stem-text">{remainder_body}</div>'
                "</div>"
            )
            rendered_question_stem = True
        else:
            html_parts.append(f"<p>{body}</p>")
        paragraph_lines.clear()

    def flush_list() -> None:
        nonlocal list_tag
        if not list_items or list_tag is None:
            list_items.clear()
            list_tag = None
            return
        html_parts.append(f"<{list_tag}>" + "".join(f"<li>{item}</li>" for item in list_items) + f"</{list_tag}>")
        list_items.clear()
        list_tag = None

    def flush_blockquote() -> None:
        if not blockquote_lines:
            return
        body = "<br>".join(render_inline_markdown(line) for line in blockquote_lines)
        html_parts.append(f"<blockquote>{body}</blockquote>")
        blockquote_lines.clear()

    def flush_code() -> None:
        if not code_lines:
            return
        html_parts.append(f"<pre class=\"code-block\"><code>{escape(chr(10).join(code_lines))}</code></pre>")
        code_lines.clear()

    while index < len(lines):
        raw_line = lines[index]
        stripped = raw_line.strip()

        if in_fenced_code:
            if CODE_FENCE_RE.match(stripped):
                in_fenced_code = False
                flush_code()
            else:
                code_lines.append(raw_line.rstrip())
            index += 1
            continue

        if not stripped:
            flush_paragraph()
            flush_list()
            flush_blockquote()
            flush_code()
            index += 1
            continue

        if CODE_FENCE_RE.match(stripped):
            flush_paragraph()
            flush_list()
            flush_blockquote()
            flush_code()
            in_fenced_code = True
            index += 1
            continue

        image_match = IMAGE_LINE_RE.match(stripped)
        if image_match:
            flush_paragraph()
            flush_list()
            flush_blockquote()
            flush_code()
            alt = image_match.group("alt").strip()
            src = image_match.group("src").strip()
            asset = asset_lookup.get(alt)
            caption = ""
            html_src = src
            if asset is not None:
                caption = str(asset.get("asset_text") or asset.get("ocr_text") or "").strip()
                html_src = str(asset.get("html_src") or src)
            figure_parts = [
                '<figure class="question-figure">',
                f'<img src="{escape(html_src, quote=True)}" alt="{escape(alt)}" loading="lazy">',
            ]
            if caption:
                figure_parts.append(f"<figcaption>{render_inline_markdown(caption)}</figcaption>")
            figure_parts.append("</figure>")
            html_parts.append("".join(figure_parts))
            index += 1
            continue

        if THEMATIC_BREAK_RE.match(stripped):
            flush_paragraph()
            flush_list()
            flush_blockquote()
            flush_code()
            html_parts.append("<hr>")
            index += 1
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            flush_paragraph()
            flush_list()
            flush_blockquote()
            flush_code()
            level = min(6, len(heading_match.group(1)))
            html_parts.append(f"<h{level}>{render_inline_markdown(heading_match.group(2))}</h{level}>")
            index += 1
            continue

        if mode == "question":
            marks_match = QUESTION_MARKS_RE.match(stripped)
            if marks_match:
                flush_paragraph()
                flush_list()
                flush_blockquote()
                flush_code()
                marks = marks_match.group("marks")
                label = "mark" if marks == "1" else "marks"
                html_parts.append(f'<div class="question-marks-badge">{escape(marks)} {label}</div>')
                index += 1
                continue

            subpart_match = QUESTION_SUBPART_RE.match(stripped)
            if subpart_match:
                flush_paragraph()
                flush_list()
                flush_blockquote()
                flush_code()
                label = subpart_match.group("label")
                body = (subpart_match.group("body") or "").strip()
                level = subpart_level(label)
                html_parts.append(
                    '<div class="question-subpart question-subpart-' + level + '">'
                    f'<span class="question-subpart-label">{escape(label)}</span>'
                    '</div>'
                )
                if body:
                    html_parts.append(f'<p class="question-subpart-text">{render_inline_markdown(body)}</p>')
                index += 1
                continue

            if re.match(rf"^(?:{COMMAND_WORDS_RE})\b", stripped):
                flush_paragraph()
                flush_list()
                flush_blockquote()
                flush_code()
                html_parts.append(f'<p class="question-instruction-line">{render_inline_markdown(stripped)}</p>')
                index += 1
                continue

            response_match = QUESTION_RESPONSE_LINE_RE.match(stripped)
            if response_match:
                flush_paragraph()
                flush_list()
                flush_blockquote()
                flush_code()
                html_parts.append(
                    '<div class="question-response-line">'
                    f'<span class="question-response-index">{escape(response_match.group("label"))}</span>'
                    '<span class="question-response-blank"></span>'
                    "</div>"
                )
                index += 1
                continue

        if mode == "answer":
            answer_part_match = ANSWER_PART_RE.match(stripped)
            if answer_part_match:
                flush_paragraph()
                flush_list()
                flush_blockquote()
                flush_code()
                label = answer_part_match.group("label")
                body = (answer_part_match.group("body") or "").strip()
                html_parts.append(
                    '<div class="answer-part-header">'
                    f'<span class="answer-part-label">{escape(label)}</span>'
                    + (
                        f'<div class="answer-part-body">{render_inline_markdown(body)}</div>'
                        if body
                        else '<div class="answer-part-body"></div>'
                    )
                    + "</div>"
                )
                index += 1
                continue

            answer_group_match = ANSWER_GROUP_LABEL_RE.match(stripped)
            if answer_group_match:
                flush_paragraph()
                flush_list()
                flush_blockquote()
                flush_code()
                html_parts.append(f'<div class="answer-group-label">{render_inline_markdown(stripped)}</div>')
                index += 1
                continue

        if (
            index + 1 < len(lines)
            and is_table_row(stripped)
            and TABLE_SEPARATOR_RE.match(lines[index + 1].strip())
        ):
            flush_paragraph()
            flush_list()
            flush_blockquote()
            flush_code()
            table_lines = [stripped, lines[index + 1].strip()]
            index += 2
            while index < len(lines):
                table_candidate = lines[index].strip()
                if not table_candidate or not is_table_row(table_candidate):
                    break
                table_lines.append(table_candidate)
                index += 1
            html_parts.append(render_table_html(table_lines))
            continue

        if mode == "question" and QUESTION_OPTION_RE.match(stripped):
            flush_paragraph()
            flush_list()
            flush_blockquote()
            flush_code()
            option_lines = [stripped]
            cursor = index + 1
            while cursor < len(lines):
                candidate = lines[cursor].strip()
                if not candidate:
                    cursor += 1
                    continue
                if QUESTION_OPTION_RE.match(candidate):
                    option_lines.append(candidate)
                    cursor += 1
                    continue
                break
            if len(option_lines) >= 2:
                html_parts.append(render_question_options_html(option_lines))
                index = cursor
                continue

        if is_pseudocode_line(stripped):
            code_block_lines = [raw_line.rstrip()]
            cursor = index + 1
            while cursor < len(lines):
                candidate = lines[cursor].rstrip()
                candidate_stripped = candidate.strip()
                if not candidate_stripped or not is_pseudocode_line(candidate_stripped):
                    break
                code_block_lines.append(candidate)
                cursor += 1
            if len(code_block_lines) >= 3:
                flush_paragraph()
                flush_list()
                flush_blockquote()
                flush_code()
                code_lines.extend(code_block_lines)
                flush_code()
                index = cursor
                continue

        if mode == "question" and stripped.endswith(":"):
            task_lines, next_index = collect_question_task_lines(lines, index + 1)
            if len(task_lines) >= 2:
                flush_paragraph()
                flush_list()
                flush_blockquote()
                flush_code()
                html_parts.append(f'<p class="question-lead">{render_inline_markdown(stripped)}</p>')
                html_parts.append(
                    '<ul class="question-task-list">'
                    + "".join(f"<li>{render_inline_markdown(item)}</li>" for item in task_lines)
                    + "</ul>"
                )
                index = next_index
                continue

        if mode == "question" and stripped.startswith("Figure "):
            flush_paragraph()
            flush_list()
            flush_blockquote()
            flush_code()
            html_parts.append(f'<div class="question-figure-label">{render_inline_markdown(stripped)}</div>')
            index += 1
            continue

        if mode == "question":
            label_cluster, next_index = collect_question_label_cluster(lines, index)
            if len(label_cluster) == 4 and all(looks_like_matrix_header_label(item) for item in label_cluster[:2]) and all(
                looks_like_matrix_row_label(item) for item in label_cluster[2:]
            ):
                flush_paragraph()
                flush_list()
                flush_blockquote()
                flush_code()
                html_parts.append(render_question_matrix_html(label_cluster[:2], label_cluster[2:]))
                index = next_index
                continue
            if len(label_cluster) >= 2:
                flush_paragraph()
                flush_list()
                flush_blockquote()
                flush_code()
                html_parts.append(render_question_fields_html(label_cluster))
                index = next_index
                continue

        ordered_match = ORDERED_LIST_RE.match(stripped)
        unordered_match = UNORDERED_LIST_RE.match(stripped)
        if ordered_match or unordered_match:
            flush_paragraph()
            flush_blockquote()
            flush_code()
            next_list_tag = "ol" if ordered_match else "ul"
            if list_tag not in {None, next_list_tag}:
                flush_list()
            list_tag = next_list_tag
            list_items.append(render_inline_markdown((ordered_match or unordered_match).group("body")))
            index += 1
            continue

        blockquote_match = BLOCKQUOTE_RE.match(stripped)
        if blockquote_match:
            flush_paragraph()
            flush_list()
            flush_code()
            blockquote_lines.append(blockquote_match.group("body"))
            index += 1
            continue

        flush_list()
        flush_blockquote()
        flush_code()
        paragraph_lines.append(stripped)
        index += 1

    flush_paragraph()
    flush_list()
    flush_blockquote()
    flush_code()
    return "\n".join(html_parts)


def file_uri(path: Path) -> str:
    return path.resolve().as_uri()


def rel_href(from_path: Path, to_path: Path) -> str:
    return Path(os.path.relpath(to_path, from_path.parent)).as_posix()


def site_subject(input_dir: Path, site_title_override: str | None) -> str:
    if site_title_override:
        return site_title_override
    topic_index_path = input_dir / "topic_index.json"
    if topic_index_path.exists():
        try:
            topic_index = read_json(topic_index_path)
            subject = str(topic_index.get("subject", "")).strip()
            if subject:
                return subject
        except Exception:
            pass
    if input_dir.name.lower() == "markdowns" and input_dir.parent.name:
        return input_dir.parent.name
    return input_dir.name


def build_site_questions(
    input_dir: Path,
    output_dir: Path,
    *,
    image_mode: str = "linked",
) -> list[SiteQuestion]:
    manifest_path = input_dir / "manifest.json"
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        if not isinstance(manifest, list):
            raise ValueError(f"Manifest must be a JSON array: {manifest_path}")
    else:
        manifest = build_entries_from_filesystem(input_dir)

    site_questions: list[SiteQuestion] = []
    for entry in sorted(
        manifest,
        key=lambda item: (
            str(item.get("year", "")),
            str(item.get("paper_key", "")),
            question_sort_key(item),
        ),
    ):
        markdown_path = resolve_manifest_path(input_dir, str(entry["markdown_path"]))
        parsed = parse_question_markdown(markdown_path)
        asset_lookup: dict[str, dict[str, Any]] = {}
        for raw_asset in entry.get("assets", []):
            asset = dict(raw_asset)
            asset_id = str(asset.get("asset_id"))
            asset_path_value = str(asset.get("path", "")).strip()
            if asset_path_value:
                asset_path = resolve_manifest_path(input_dir, asset_path_value)
                if asset_path.exists():
                    if image_mode == "embed":
                        asset["html_src"] = path_to_data_uri(asset_path)
                    else:
                        try:
                            relative_asset = asset_path.resolve().relative_to((input_dir / "_assets").resolve())
                            output_asset_path = output_dir / "_assets" / relative_asset
                            asset["html_src"] = rel_href(html_path, output_asset_path)
                        except Exception:
                            asset["html_src"] = path_to_data_uri(asset_path)
            asset_lookup[asset_id] = asset
        chapter_name = str(entry.get("chapter_name") or "Unclassified")
        topic_name = str(entry.get("topic_name") or "Unclassified")
        topic_slug = slugify(f"{chapter_name}-{topic_name}")
        chapter_slug = slugify(chapter_name)
        relative_markdown_path = markdown_path.relative_to(input_dir)
        html_path = output_dir / relative_markdown_path.with_suffix(".html")
        paper_index_path = html_path.parent / "index.html"
        year_index_path = output_dir / str(entry.get("year", "unknown-year")) / "index.html"
        question_html = render_markdown_fragment(parsed.question_markdown, asset_lookup, mode="question")
        answer_html = render_markdown_fragment(parsed.answer_markdown, asset_lookup, mode="answer")
        search_text = " ".join(
            part
            for part in [
                str(entry.get("year", "")),
                str(entry.get("paper_key", "")),
                str(entry.get("question_label", "")),
                chapter_name,
                topic_name,
                preview_text(parsed.question_markdown, limit=280),
                preview_text(parsed.answer_markdown, limit=220),
            ]
            if part
        )
        site_questions.append(
            SiteQuestion(
                entry=entry,
                title=parsed.title,
                question_html=question_html,
                answer_html=answer_html,
                preview_text=preview_text(parsed.question_markdown),
                markdown_path=markdown_path,
                html_path=html_path,
                paper_index_path=paper_index_path,
                year_index_path=year_index_path,
                chapter_name=chapter_name,
                topic_name=topic_name,
                topic_slug=topic_slug,
                chapter_slug=chapter_slug,
                search_text=search_text,
            )
        )

    return site_questions


def grouped_by_year(site_questions: list[SiteQuestion]) -> dict[str, list[SiteQuestion]]:
    grouped: dict[str, list[SiteQuestion]] = {}
    for question in site_questions:
        year = str(question.entry.get("year", "unknown-year"))
        grouped.setdefault(year, []).append(question)
    return grouped


def grouped_by_paper(site_questions: list[SiteQuestion]) -> dict[tuple[str, str], list[SiteQuestion]]:
    grouped: dict[tuple[str, str], list[SiteQuestion]] = {}
    for question in site_questions:
        key = (str(question.entry.get("year", "unknown-year")), str(question.entry.get("paper_key", "")))
        grouped.setdefault(key, []).append(question)
    return grouped


def grouped_by_topic(site_questions: list[SiteQuestion]) -> dict[tuple[str, str, str], list[SiteQuestion]]:
    grouped: dict[tuple[str, str, str], list[SiteQuestion]] = {}
    for question in site_questions:
        key = (question.chapter_name, question.topic_name, question.topic_slug)
        grouped.setdefault(key, []).append(question)
    return grouped


def render_layout(
    *,
    page_title: str,
    site_title: str,
    page_path: Path,
    output_dir: Path,
    body_html: str,
    description: str | None = None,
    theme: str = "modern",
) -> str:
    css_filename = "site-pdf.css" if theme == "pdf" else "site.css"
    css_href = rel_href(page_path, output_dir / DEFAULT_SITE_ASSETS_SUBDIR / css_filename)
    js_href = rel_href(page_path, output_dir / DEFAULT_SITE_ASSETS_SUBDIR / "site.js")
    home_href = rel_href(page_path, output_dir / "index.html")
    meta_description = escape(description or f"{page_title} | {site_title}", quote=True)
    full_title = escape(f"{page_title} | {site_title}")
    font_link = "" if theme == "pdf" else """
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Anek+Bangla:wght@400;500;600;700;800&display=swap" rel="stylesheet">"""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{full_title}</title>
  <meta name="description" content="{meta_description}">{font_link}
  <link rel="stylesheet" href="{css_href}">
</head>
<body>
  <div class="page-shell">
    <header class="site-header">
      <a class="site-mark" href="{home_href}"><span>QNA</span><span>HTML</span></a>
      <div class="site-heading">
        <h1>{escape(site_title)}</h1>
        <p>Static rebuild from converted markdowns.</p>
      </div>
    </header>
    <main class="site-main">
      {body_html}
    </main>
  </div>
  <script src="{js_href}"></script>
</body>
</html>
"""


def render_breadcrumbs(page_path: Path, output_dir: Path, items: list[tuple[str, Path | None]]) -> str:
    del output_dir
    parts = ['<nav class="breadcrumbs" aria-label="Breadcrumbs">']
    rendered_items: list[str] = []
    for label, target in items:
        if target is None:
            rendered_items.append(f"<span>{escape(label)}</span>")
        else:
            rendered_items.append(f'<a href="{rel_href(page_path, target)}">{escape(label)}</a>')
    parts.append(" / ".join(rendered_items))
    parts.append("</nav>")
    return "".join(parts)


def render_question_card(question: SiteQuestion, page_path: Path) -> str:
    year = str(question.entry.get("year", ""))
    paper_key = str(question.entry.get("paper_key", ""))
    question_label = str(question.entry.get("question_label", "")).upper()
    href = rel_href(page_path, question.html_path)
    search = escape(question.search_text.lower(), quote=True)
    return f"""
<article class="question-card" data-search-item data-search="{search}">
  <div class="question-card-meta">
    <span>{escape(year)}</span>
    <span>{escape(paper_key)}</span>
    <span>{escape(question_label)}</span>
  </div>
  <h3><a href="{href}">{escape(question.title)}</a></h3>
  <p class="question-card-tags">{escape(question.chapter_name)} / {escape(question.topic_name)}</p>
  <p>{escape(question.preview_text)}</p>
</article>
"""


def write_question_pages(site_questions: list[SiteQuestion], output_dir: Path, site_title: str, theme: str = "modern") -> None:
    paper_groups = grouped_by_paper(site_questions)
    topic_groups = grouped_by_topic(site_questions)

    for question in site_questions:
        question.html_path.parent.mkdir(parents=True, exist_ok=True)
        year = str(question.entry.get("year", ""))
        paper_key = str(question.entry.get("paper_key", ""))
        breadcrumbs = render_breadcrumbs(
            question.html_path,
            output_dir,
            [
                ("Home", output_dir / "index.html"),
                (year, question.year_index_path),
                (paper_key, question.paper_index_path),
                (str(question.entry.get("question_label", "")).upper(), None),
            ],
        )
        topic_page = output_dir / "topics" / f"{question.topic_slug}.html"
        metadata_lines = [
            ("Paper key", paper_key),
            ("Year", year),
            ("Chapter", question.chapter_name),
            ("Topic", question.topic_name),
            ("Tag source", str(question.entry.get("tagging_source") or "none")),
            ("Tag confidence", str(question.entry.get("tag_confidence") or "n/a")),
            ("Question PDF", str(Path(str(question.entry.get("question_pdf", ""))).name)),
            ("Mark scheme PDF", str(Path(str(question.entry.get("mark_scheme_pdf", ""))).name)),
        ]
        metadata_html = "".join(
            f"<div><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>" for label, value in metadata_lines
        )
        pdf_links = [
            ("Question PDF", file_uri(Path(str(question.entry.get("question_pdf", ""))))),
            ("Mark Scheme PDF", file_uri(Path(str(question.entry.get("mark_scheme_pdf", ""))))),
            ("Markdown Source", file_uri(question.markdown_path)),
        ]
        resource_links = "".join(
            f'<a class="pill-link" href="{escape(href, quote=True)}">{escape(label)}</a>'
            for label, href in pdf_links
        )
        question_list = paper_groups[(year, paper_key)]
        nav_links: list[str] = []
        for index, item in enumerate(question_list):
            if item.html_path == question.html_path:
                if index > 0:
                    nav_links.append(
                        f'<a class="nav-link" href="{rel_href(question.html_path, question_list[index - 1].html_path)}">Previous</a>'
                    )
                if index + 1 < len(question_list):
                    nav_links.append(
                        f'<a class="nav-link" href="{rel_href(question.html_path, question_list[index + 1].html_path)}">Next</a>'
                    )
                break

        # Build topic question selector
        topic_questions = topic_groups.get((question.chapter_name, question.topic_name, question.topic_slug), [])
        topic_selector_items = []
        for tq in topic_questions:
            is_current = tq.html_path == question.html_path
            css_class = "topic-question-item active" if is_current else "topic-question-item"
            label = str(tq.entry.get("question_label", "")).upper()
            topic_selector_items.append(
                f'<a class="{css_class}" href="{rel_href(question.html_path, tq.html_path)}">{escape(label)}</a>'
            )
        topic_selector_html = "".join(topic_selector_items) if topic_selector_items else "<p>No related questions</p>"

        grid_class = "content-grid pdf-layout" if theme == "pdf" else "content-grid"
        page_body = f"""
{breadcrumbs}
<section class="hero-card">
  <div>
    <p class="eyebrow">{escape(year)} / {escape(paper_key)}</p>
    <h2>{escape(question.title)}</h2>
    <p class="hero-tags"><a href="{rel_href(question.html_path, topic_page)}">{escape(question.chapter_name)} / {escape(question.topic_name)}</a></p>
  </div>
  <div class="hero-actions">{resource_links}</div>
</section>
<section class="{grid_class}">
  <aside class="meta-panel">
    <h3>Topic Questions</h3>
    <div class="topic-question-list">{topic_selector_html}</div>
    <h3>Metadata</h3>
    <dl>{metadata_html}</dl>
    <div class="page-nav">{''.join(nav_links)}</div>
  </aside>
  <div class="question-panel">
    <section class="content-panel">
      <div class="panel-header">
        <h3>Question</h3>
      </div>
      <div class="markdown-body">{question.question_html}</div>
    </section>
    <section class="content-panel">
      <div class="panel-header panel-header-split">
        <h3>Answer</h3>
        <button class="toggle-button" type="button" data-toggle-target="#answer-panel">Toggle</button>
      </div>
      <div id="answer-panel" class="markdown-body">{question.answer_html}</div>
    </section>
  </div>
</section>
"""
        html = render_layout(
            page_title=question.title,
            site_title=site_title,
            page_path=question.html_path,
            output_dir=output_dir,
            body_html=page_body,
            description=question.preview_text,
            theme=theme,
        )
        question.html_path.write_text(html, encoding="utf-8")


def write_year_pages(site_questions: list[SiteQuestion], output_dir: Path, site_title: str, theme: str = "modern") -> None:
    for year, questions in sorted(grouped_by_year(site_questions).items()):
        page_path = output_dir / year / "index.html"
        page_path.parent.mkdir(parents=True, exist_ok=True)
        paper_groups = grouped_by_paper(questions)
        cards: list[str] = []
        for (_paper_year, paper_key), paper_questions in sorted(paper_groups.items()):
            cards.append(
                f"""
<article class="paper-card">
  <p class="eyebrow">{escape(year)}</p>
  <h3><a href="{rel_href(page_path, paper_questions[0].paper_index_path)}">{escape(paper_key)}</a></h3>
  <p>{len(paper_questions)} questions</p>
</article>
"""
            )
        body = f"""
{render_breadcrumbs(page_path, output_dir, [('Home', output_dir / 'index.html'), (year, None)])}
<section class="hero-card">
  <div>
    <p class="eyebrow">Year</p>
    <h2>{escape(year)}</h2>
    <p>{len(questions)} question pages across {len(paper_groups)} papers.</p>
  </div>
</section>
<section class="section-block">
  <h3>Papers</h3>
  <div class="card-grid">
    {''.join(cards)}
  </div>
</section>
"""
        page_path.write_text(
            render_layout(
                page_title=f"{year}",
                site_title=site_title,
                page_path=page_path,
                output_dir=output_dir,
                body_html=body,
                theme=theme,
            ),
            encoding="utf-8",
        )


def write_paper_pages(site_questions: list[SiteQuestion], output_dir: Path, site_title: str, theme: str = "modern") -> None:
    for (year, paper_key), questions in sorted(grouped_by_paper(site_questions).items()):
        page_path = output_dir / year / paper_key / "index.html"
        page_path.parent.mkdir(parents=True, exist_ok=True)
        cards = "".join(render_question_card(question, page_path) for question in questions)
        body = f"""
{render_breadcrumbs(page_path, output_dir, [('Home', output_dir / 'index.html'), (year, output_dir / year / 'index.html'), (paper_key, None)])}
<section class="hero-card">
  <div>
    <p class="eyebrow">Paper</p>
    <h2>{escape(paper_key)}</h2>
    <p>{len(questions)} questions</p>
  </div>
</section>
<section class="section-block">
  <div class="section-toolbar">
    <h3>Questions</h3>
    <input class="search-input" type="search" placeholder="Filter questions" data-search-input>
  </div>
  <div class="stack-list" data-search-container>
    {cards}
  </div>
</section>
"""
        page_path.write_text(
            render_layout(
                page_title=paper_key,
                site_title=site_title,
                page_path=page_path,
                output_dir=output_dir,
                body_html=body,
                theme=theme,
            ),
            encoding="utf-8",
        )


def write_topic_pages(site_questions: list[SiteQuestion], output_dir: Path, site_title: str, theme: str = "modern") -> None:
    topics_dir = output_dir / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    for (chapter_name, topic_name, topic_slug), questions in sorted(grouped_by_topic(site_questions).items()):
        page_path = topics_dir / f"{topic_slug}.html"
        cards = "".join(render_question_card(question, page_path) for question in questions)
        body = f"""
{render_breadcrumbs(page_path, output_dir, [('Home', output_dir / 'index.html'), (topic_name, None)])}
<section class="hero-card">
  <div>
    <p class="eyebrow">{escape(chapter_name)}</p>
    <h2>{escape(topic_name)}</h2>
    <p>{len(questions)} linked questions</p>
  </div>
</section>
<section class="section-block">
  <div class="section-toolbar">
    <h3>Questions</h3>
    <input class="search-input" type="search" placeholder="Filter this topic" data-search-input>
  </div>
  <div class="stack-list" data-search-container>
    {cards}
  </div>
</section>
"""
        page_path.write_text(
            render_layout(
                page_title=topic_name,
                site_title=site_title,
                page_path=page_path,
                output_dir=output_dir,
                body_html=body,
                theme=theme,
            ),
            encoding="utf-8",
        )


def write_home_page(site_questions: list[SiteQuestion], output_dir: Path, site_title: str, theme: str = "modern") -> None:
    page_path = output_dir / "index.html"
    years = grouped_by_year(site_questions)
    topics = grouped_by_topic(site_questions)
    year_cards = "".join(
        f"""
<article class="year-card">
  <p class="eyebrow">Year</p>
  <h3><a href="{rel_href(page_path, output_dir / year / 'index.html')}">{escape(year)}</a></h3>
  <p>{len(questions)} questions</p>
</article>
"""
        for year, questions in sorted(years.items())
    )
    topic_cards = "".join(
        f"""
<article class="topic-card" data-search-item data-search="{escape((chapter_name + ' ' + topic_name).lower(), quote=True)}">
  <p class="eyebrow">{escape(chapter_name)}</p>
  <h3><a href="{rel_href(page_path, output_dir / 'topics' / f'{topic_slug}.html')}">{escape(topic_name)}</a></h3>
  <p>{len(questions)} questions</p>
</article>
"""
        for (chapter_name, topic_name, topic_slug), questions in sorted(topics.items())
    )
    question_cards = "".join(render_question_card(question, page_path) for question in site_questions)
    body = f"""
<section class="hero-card hero-card-home">
  <div>
    <p class="eyebrow">Static HTML rebuild</p>
    <h2>{escape(site_title)}</h2>
    <p>{len(site_questions)} question pages across {len(years)} years and {len(topics)} topics.</p>
  </div>
</section>
<section class="section-block">
  <h3>Years</h3>
  <div class="card-grid">
    {year_cards}
  </div>
</section>
<section class="section-block">
  <div class="section-toolbar">
    <h3>Topics</h3>
    <input class="search-input" type="search" placeholder="Filter topics" data-search-input>
  </div>
  <div class="card-grid" data-search-container>
    {topic_cards}
  </div>
</section>
<section class="section-block">
  <div class="section-toolbar">
    <h3>All Questions</h3>
    <input class="search-input" type="search" placeholder="Search questions, papers, topics" data-search-input>
  </div>
  <div class="stack-list" data-search-container>
    {question_cards}
  </div>
</section>
"""
    page_path.write_text(
        render_layout(
            page_title=site_title,
            site_title=site_title,
            page_path=page_path,
            output_dir=output_dir,
            body_html=body,
            theme=theme,
        ),
        encoding="utf-8",
    )


def copy_static_assets(input_dir: Path, output_dir: Path, theme: str = "modern") -> None:
    if SITE_ASSETS_DIR.exists():
        css_filename = "site-pdf.css" if theme == "pdf" else "site.css"
        css_source = SITE_ASSETS_DIR / css_filename
        if css_source.exists():
            target_dir = output_dir / DEFAULT_SITE_ASSETS_SUBDIR
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(css_source, target_dir / css_filename)
        js_source = SITE_ASSETS_DIR / "site.js"
        if js_source.exists():
            target_dir = output_dir / DEFAULT_SITE_ASSETS_SUBDIR
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(js_source, target_dir / "site.js")
    assets_dir = input_dir / "_assets"
    if assets_dir.exists():
        shutil.copytree(assets_dir, output_dir / "_assets", dirs_exist_ok=True)


def build_site(
    input_dir: Path,
    output_dir: Path,
    site_title_override: str | None = None,
    *,
    image_mode: str = "linked",
    theme: str = "modern",
) -> tuple[int, int, Path]:
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")

    site_questions = build_site_questions(input_dir, output_dir, image_mode=image_mode)
    site_title = site_subject(input_dir, site_title_override)
    output_dir.mkdir(parents=True, exist_ok=True)
    copy_static_assets(input_dir, output_dir, theme=theme)
    write_question_pages(site_questions, output_dir, site_title, theme=theme)
    write_year_pages(site_questions, output_dir, site_title, theme=theme)
    write_paper_pages(site_questions, output_dir, site_title, theme=theme)
    write_topic_pages(site_questions, output_dir, site_title, theme=theme)
    write_home_page(site_questions, output_dir, site_title, theme=theme)
    return len(site_questions), len(grouped_by_topic(site_questions)), output_dir / "index.html"


def main() -> int:
    args = parse_args()
    input_dir = args.input_dir.resolve()
    output_dir = resolve_output_dir(input_dir, args.output_dir.resolve() if args.output_dir else None)
    question_count, topic_count, index_path = build_site(
        input_dir, output_dir, args.site_title, image_mode=args.image_mode, theme=args.html_theme
    )
    print(f"Built HTML site: {output_dir}")
    print(f"Question pages : {question_count}")
    print(f"Topic pages    : {topic_count}")
    print(f"Home page      : {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
