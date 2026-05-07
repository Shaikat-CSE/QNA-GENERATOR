"""Selenium-based PDF scraper that downloads PDFs from a webpage."""

import os
import re
import time
import json
import shutil
from urllib.parse import urljoin, urlparse
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

KNOWN_DP_SUBJECT_ALIASES = {
    "biology": "Biology",
    "business management": "Business Management",
    "business": "Business Management",
    "chemistry": "Chemistry",
    "chinese b mandarin": "Chinese B Mandarin",
    "computer science": "Computer Science",
    "design technology": "Design Technology",
    "digital societies": "Digital Societies",
    "economics": "Economics",
    "english a language literature": "English A Language Literature",
    "english a language and literature": "English A Language Literature",
    "english literature": "English A Language Literature",
    "environmental systems and societies ess": "Environmental Systems Societies",
    "environmental systems societies": "Environmental Systems Societies",
    "environmental systems and societies": "Environmental Systems Societies",
    "ess": "Environmental Systems Societies",
    "food science and technology": "Food Science and Technology",
    "geography": "Geography",
    "global politics": "Global Politics",
    "history": "History",
    "mathematics aa": "Mathematics AA",
    "mathematics ai": "Mathematics AI",
    "maths aa": "Mathematics AA",
    "maths ai": "Mathematics AI",
    "music": "Music",
    "philosophy": "Philosophy",
    "physics": "Physics",
    "psychology": "Psychology",
    "social and cultural anthropology": "Social and Cultural Anthropology",
    "sports exercise health science": "Sports Exercise Health Science",
    "visual arts": "Visual Arts",
}


def _make_logger(logger=None):
    """Return a logger that prints and optionally forwards messages."""

    def log(msg):
        print(msg)
        if logger:
            logger(msg)

    return log


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _canonicalize_subject_name(name: str) -> str:
    slug = _slugify(name)
    return KNOWN_DP_SUBJECT_ALIASES.get(slug, " ".join(part.capitalize() for part in slug.split()))


def _slug_filename(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "paper"


def _detect_ib_level(*texts: str) -> str | None:
    combined = " ".join(text for text in texts if text).lower()
    if not combined:
        return None
    if re.search(r"\bhl\s*[-/]\s*sl\b|\bsl\s*[-/]\s*hl\b|\bhl\s+sl\b|\bsl\s+hl\b", combined):
        return "both"
    if re.search(r"\bhl\b|\bhigher level\b", combined):
        return "hl"
    if re.search(r"\bsl\b|\bstandard level\b", combined):
        return "sl"
    return None


def _detect_ib_level_from_filename(filename: str) -> str | None:
    stem = os.path.splitext(os.path.basename(filename))[0].lower()
    tokens = [token for token in re.split(r"[^a-z0-9]+", stem) if token]

    has_hl = "hl" in tokens
    has_sl = "sl" in tokens
    if has_hl and has_sl:
        return "both"
    if has_hl:
        return "hl"
    if has_sl:
        return "sl"
    return None


def _ib_level_from_path(path: str) -> str | None:
    parts = [part.lower() for part in os.path.normpath(path).split(os.sep)]
    if "past-papers" not in parts:
        return None

    past_index = parts.index("past-papers")
    if past_index == 0:
        return None

    parent = parts[past_index - 1]
    if parent in {"sl", "hl"}:
        return parent
    return None


def _move_file_without_overwrite(source: str, destination: str) -> str:
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    if not os.path.exists(destination):
        shutil.move(source, destination)
        return destination

    src_size = os.path.getsize(source)
    dst_size = os.path.getsize(destination)
    if src_size == dst_size:
        os.remove(source)
        return destination

    base, ext = os.path.splitext(destination)
    counter = 1
    candidate = f"{base}_{counter}{ext}"
    while os.path.exists(candidate):
        counter += 1
        candidate = f"{base}_{counter}{ext}"

    shutil.move(source, candidate)
    return candidate


def cleanup_ib_level_placements(base_dir: str, dry_run: bool = True, logger=None) -> dict:
    """Move IB PDFs whose filename level marker conflicts with their sl/hl folder."""
    log = _make_logger(logger)
    moved = []
    skipped = []

    for current_dir, _, filenames in os.walk(base_dir):
        current_level = _ib_level_from_path(current_dir)
        if current_level not in {"sl", "hl"}:
            continue

        for filename in filenames:
            if not filename.lower().endswith(".pdf"):
                continue

            detected_level = _detect_ib_level_from_filename(filename)
            if detected_level in {None, "both", current_level}:
                continue

            source = os.path.join(current_dir, filename)
            subject_dir = os.path.dirname(os.path.dirname(current_dir))
            target_dir = os.path.join(subject_dir, detected_level, "past-papers")

            if not os.path.isdir(os.path.dirname(target_dir)):
                skipped.append((source, f"missing {detected_level} folder"))
                log(f"SKIP - missing {detected_level} folder: {source}")
                continue

            destination = os.path.join(target_dir, filename)
            if dry_run:
                moved.append((source, destination))
                log(f"DRY RUN - move {source} -> {destination}")
            else:
                final_destination = _move_file_without_overwrite(source, destination)
                moved.append((source, final_destination))
                log(f"MOVED - {source} -> {final_destination}")

    log(f"Cleanup {'would move' if dry_run else 'moved'} {len(moved)} files")
    if skipped:
        log(f"Cleanup skipped {len(skipped)} files")

    return {"moved": moved, "skipped": skipped, "dry_run": dry_run}


def _normalize_dp_path_parts(parts: list[str]) -> list[str]:
    normalized = []
    for part in parts:
        if part == "maths":
            normalized.append("mathematics")
        else:
            normalized.append(part.replace("-", " "))
    return normalized


def _parse_dp_subject_from_href(href: str) -> tuple[str | None, str | None]:
    parsed = urlparse(href)
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if "dp" not in parts or "past-papers" not in parts:
        return None, None

    dp_index = parts.index("dp")
    past_index = parts.index("past-papers")
    middle_parts = parts[dp_index + 1 : past_index]
    if not middle_parts:
        return None, None

    if "ib" in middle_parts:
        ib_index = middle_parts.index("ib")
        subject_parts = middle_parts[:ib_index]
        course_parts = middle_parts[ib_index + 1 :]
    else:
        subject_parts = middle_parts
        course_parts = []

    candidate_names = []
    combined_parts = subject_parts + course_parts
    if combined_parts:
        candidate_names.append(" ".join(_normalize_dp_path_parts(combined_parts)))
    if course_parts:
        candidate_names.append(" ".join(_normalize_dp_path_parts(course_parts)))
    if subject_parts:
        candidate_names.append(" ".join(_normalize_dp_path_parts(subject_parts)))

    subject_name = None
    for candidate in candidate_names:
        slug = _slugify(candidate)
        if slug in KNOWN_DP_SUBJECT_ALIASES:
            subject_name = KNOWN_DP_SUBJECT_ALIASES[slug]
            break

    if subject_name is None:
        fallback = candidate_names[0] if candidate_names else ""
        subject_name = _canonicalize_subject_name(fallback)

    return subject_name, "ib"


def _is_savemyexams_dp_past_papers(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    return "savemyexams.com" in parsed.netloc.lower() and "/dp/" in path and "/past-papers" in path


def _extract_next_data(html: str) -> dict | None:
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _collect_past_paper_entries(node) -> list[dict]:
    found = []
    seen = set()

    def walk(value):
        if isinstance(value, dict):
            if value.get("type") == "past_paper" and isinstance(value.get("attributes"), dict):
                paper_id = value.get("id") or id(value)
                if paper_id not in seen:
                    seen.add(paper_id)
                    found.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(node)
    return found


def _collect_structured_entities(node) -> dict[tuple[str, str], dict]:
    entities = {}

    def walk(value):
        if isinstance(value, dict):
            entity_type = value.get("type")
            entity_id = value.get("id")
            attributes = value.get("attributes")
            if entity_type and entity_id and isinstance(attributes, dict):
                entities[(entity_type, entity_id)] = value
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(node)
    return entities


def _is_savemyexams_dp_root(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/").lower()
    return "savemyexams.com" in parsed.netloc.lower() and path == "/dp"


def _discover_savemyexams_dp_subjects(base_url: str, logger=None) -> dict[str, dict]:
    log = _make_logger(logger)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    response = requests.get(base_url, headers=headers, timeout=30)
    response.raise_for_status()

    next_data = _extract_next_data(response.text)
    if not next_data:
        raise ValueError("Could not extract SaveMyExams DP metadata")

    page_props = next_data.get("props", {}).get("pageProps", {})
    entities = _collect_structured_entities(page_props)
    subject_data = {}

    for course in page_props.get("courses", []):
        attrs = course.get("attributes", {})
        if not (attrs.get("has_published_past_papers") or attrs.get("has_published_practice_papers")):
            continue

        relationships = course.get("relationships", {})
        subject_ref = relationships.get("subject", {}).get("data") or {}
        board_ref = relationships.get("board", {}).get("data") or {}
        subject_entity = entities.get((subject_ref.get("type"), subject_ref.get("id")), {})
        board_entity = entities.get((board_ref.get("type"), board_ref.get("id")), {})

        subject_slug = subject_entity.get("attributes", {}).get("slug")
        board_slug = board_entity.get("attributes", {}).get("slug") or "ib"
        course_slug = attrs.get("slug")
        if not subject_slug:
            continue

        path_parts = ["dp", subject_slug, board_slug]
        if course_slug:
            path_parts.append(course_slug)
        path_parts.append("past-papers")
        subject_url = f"https://www.savemyexams.com/{'/'.join(path_parts)}/"

        subject_name, _ = _parse_dp_subject_from_href(subject_url)
        if not subject_name:
            continue

        subject_data[subject_name] = {
            "subject": subject_name,
            "board": "IB",
            "level": "IB",
            "url": subject_url,
        }

    log(f"Found {len(subject_data)} DP subjects from page metadata")
    return subject_data


def _download_file(url: str, filepath: str, headers: dict[str, str], referer: str | None = None) -> None:
    request_headers = dict(headers)
    if referer:
        request_headers["Referer"] = referer

    parsed = urlparse(url)
    is_ibo = "ibo.org" in parsed.netloc.lower()

    try:
        response = requests.get(url, headers=request_headers, allow_redirects=True, stream=True, timeout=30)
    except requests.exceptions.SSLError:
        if not is_ibo:
            raise
        response = requests.get(
            url,
            headers=request_headers,
            allow_redirects=True,
            stream=True,
            timeout=30,
            verify=False,
        )

    if response.status_code == 403 and is_ibo:
        raise RuntimeError("Protected external IBO PDF blocked direct download")

    response.raise_for_status()
    with open(filepath, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)


def _download_file_if_missing(url: str, filepath: str, headers: dict[str, str], referer: str | None = None) -> bool:
    if os.path.exists(filepath):
        return False

    _download_file(url, filepath, headers, referer=referer)
    return True


def _download_savemyexams_dp_papers(
    url: str,
    output_dir: str,
    target_subject: str | None,
    target_level: str | None,
    logger=None,
) -> int:
    log = _make_logger(logger)
    os.makedirs(output_dir, exist_ok=True)

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    next_data = _extract_next_data(response.text)
    if not next_data:
        raise ValueError("Could not extract SaveMyExams page metadata")

    entries = _collect_past_paper_entries(next_data)
    log(f"Found {len(entries)} structured paper entries")

    downloaded = 0
    skipped = 0

    page_subject, _ = _parse_dp_subject_from_href(url)

    for index, entry in enumerate(entries, 1):
        attrs = entry.get("attributes", {})
        paper_name = attrs.get("name", "") or attrs.get("description", "") or "practice paper"
        paper_level = _detect_ib_level(paper_name, attrs.get("description", ""), attrs.get("exam_paper", ""))
        effective_subject = target_subject or page_subject or "unknown"

        if target_subject and page_subject and _slugify(target_subject) not in _slugify(page_subject) and _slugify(page_subject) not in _slugify(target_subject):
            log(f"[{index}/{len(entries)}] SKIP - Subject mismatch: expected '{target_subject}', page is '{page_subject}'")
            skipped += 1
            continue

        if target_level and paper_level not in {target_level.lower(), "both"}:
            log(f"[{index}/{len(entries)}] SKIP - Level mismatch: expected '{target_level}', found '{paper_level or 'unknown'}'")
            skipped += 1
            continue

        slug_base = _slug_filename(f"{effective_subject}-{paper_name}")
        resources = [
            ("qp", attrs.get("exam_paper")),
            ("ms", attrs.get("mark_scheme") or attrs.get("model_answers")),
        ]
        seen_resource_urls = set()

        downloaded_any = False
        for kind, file_url in resources:
            if not file_url:
                continue
            if file_url in seen_resource_urls:
                continue
            seen_resource_urls.add(file_url)

            filename = os.path.basename(urlparse(file_url).path)
            if not filename.lower().endswith(".pdf"):
                filename = f"{slug_base}-{kind}.pdf"
            elif "practice-paper" in filename.lower() or filename.lower().startswith(tuple(str(n) for n in range(10))):
                filename = f"{slug_base}-{kind}.pdf"

            filepath = os.path.join(output_dir, filename)
            try:
                if _download_file_if_missing(file_url, filepath, headers, referer=url):
                    downloaded += 1
                    log(f"[{index}/{len(entries)}] DOWNLOADED - {os.path.basename(filepath)}")
                else:
                    log(f"[{index}/{len(entries)}] EXISTS - {os.path.basename(filepath)}")
                downloaded_any = True
            except Exception as e:
                log(f"[{index}/{len(entries)}] ERROR - {e}")

        if not downloaded_any:
            log(f"[{index}/{len(entries)}] SKIP - No downloadable resources")
            skipped += 1

    log(f"\nDownloaded {downloaded} PDFs to {output_dir}")
    if skipped:
        log(f"Skipped {skipped} paper entries")
    return downloaded


def _get_subject_info_from_code(code: str):
    """Look up subject info from code using subject_rules.json."""
    import json
    from pathlib import Path

    config_path = Path(__file__).parent.parent / "config" / "subject_rules.json"
    if not config_path.exists():
        return None, None, None

    with open(config_path) as f:
        rules = json.load(f)

    code_lower = code.lower()
    for key, rule in rules.items():
        rule_code = rule.get("code", "").lower()
        if rule_code == code_lower or rule_code.split("/")[0].lower() == code_lower:
            subject = rule.get("subject", "unknown")
            syllabus = rule.get("syllabus", "unknown")
            board = rule.get("board", "")
            return subject, syllabus, board
    return None, None, None


def parse_filename_to_standard(filename: str):
    """Parse various filename formats to standard format.

    Supports:
    - CIE: 9700_w22_ms_22.pdf
    - Edexcel: 4BI1_msc_01_que.pdf
    - AQA: 7402-1-MS-QP.docx (converted to pdf)
    - Generic: any descriptive name
    """
    original = filename

    # Try CIE format: NNNN_Xnn_type_NN.pdf
    match = re.match(r'(\d{4})_([smwy])(\d{2})_(qp|ms|in|er|sm|sp|prm|pm)_(\d{1,2})\.pdf', filename, re.IGNORECASE)
    if match:
        code, session_code, year, type_, variant = match.groups()

        subject, syllabus, board = _get_subject_info_from_code(code)

        if not subject:
            level = "alevel" if code.startswith("9") else "igcse"
            subject = "unknown"
            syllabus = level
            board = "cie"

        # Clean subject name
        if "(" in subject:
            subject = subject.split("(")[0].strip().split()[-1]
        subject = subject.replace(" ", "-").lower()

        # Map session codes
        session_map = {'s': 'jun', 'm': 'mar', 'w': 'nov', 'y': 'specimen'}
        session = session_map.get(session_code.lower(), session_code.lower())

        year = f"20{year}"
        board = board.lower()

        # Parse paper and variant
        if len(variant) == 1:
            paper_num = f"p{variant}"
            variant_str = "n"
        else:
            paper_num = f"p{variant[0]}"
            variant_str = variant[1]

        return f"{year}-{session}-{syllabus}-{subject}-{board}-{code}-{paper_num}-{variant_str}-{type_.lower()}.pdf"

    # Try Edexcel format: 4BI1_msc_01_que.pdf or similar
    # Pattern: CODE_type_XX_que.pdf or CODE_msc_XX.pdf etc
    match = re.match(r'([a-z0-9]+)_(?:msc|que|qp|ms|in|er)[\w]*\.pdf', filename, re.IGNORECASE)
    if match:
        code = match.group(1)
        type_map = {'msc': 'ms', 'que': 'qp', 'ms': 'ms', 'qp': 'qp', 'in': 'in', 'er': 'er'}

        # Find the type in filename
        type_ = 'qp'
        for t in ['msc', 'que', 'ms', 'qp', 'in', 'er']:
            if t in filename.lower():
                type_ = type_map.get(t, 'qp')
                break

        subject, syllabus, board = _get_subject_info_from_code(code)

        if not subject:
            return original  # Can't parse, return original

        return f"unknown-date-{syllabus}-{subject}-{board}-{code}-p1-n-{type_}.pdf"

    # Return original if no pattern matched
    return original


def _extract_code_from_filename(filename: str) -> str | None:
    """Extract syllabus code from filename."""
    import re

    # CIE format: 9700_w22_ms_22.pdf
    match = re.match(r'(\d{4})_([smwy])(\d{2})_(qp|ms|in|er|sm|sp|prm|pm)_(\d+)', filename, re.IGNORECASE)
    if match:
        return match.group(1)

    # Edexcel format: 4BI1_msc_01.pdf
    match = re.match(r'([a-z0-9]+)_(?:msc|que|qp|ms|in|er)[\w]*\.pdf', filename, re.IGNORECASE)
    if match:
        return match.group(1)

    return None


def _verify_pdf_belongs_to(
    filename: str,
    target_subject: str,
    target_board: str = None,
    target_level: str | None = None,
    context_text: str = "",
) -> tuple[bool, str]:
    """Verify if a PDF belongs to the target subject/board.

    Returns (is_valid, reason)
    """
    code = _extract_code_from_filename(filename)
    detected_level = _detect_ib_level(filename, context_text)

    if not code:
        if target_level:
            if detected_level is None:
                return False, f"Cannot determine IB level for '{filename}'"
            if detected_level != target_level.lower():
                return False, f"Level mismatch: expected '{target_level}', found '{detected_level}'"
        return True, f"Accepted by page context: {target_subject}"

    subject, syllabus, board = _get_subject_info_from_code(code)

    if not subject:
        return False, f"Unknown syllabus code: {code}"

    # Normalize for comparison
    target_subject_lower = target_subject.lower().replace(" ", "-").replace("_", "-")
    subject_lower = subject.lower().replace(" ", "-").replace("_", "-")

    # Extract just the subject name without board prefix
    # e.g., "Cie Biology" -> "biology", "Edexcel Biology" -> "biology"
    for part in subject.split():
        part_lower = part.lower().replace("-", "")
        if part_lower in ["biology", "chemistry", "physics", "mathematics", "maths",
                         "business", "accounting", "economics", "history", "geography",
                         "psychology", "sociology", "english", "chinese", "french",
                         "spanish", "german", "computing", "computerscience", "ict",
                         "design", "technology", "art", "music", "pe", "physicaleducation",
                         "environment", "environmental"]:
            subject_lower = part_lower.replace("-", "")
            break

    # Check subject match
    if target_subject_lower not in subject_lower and subject_lower not in target_subject_lower:
        return False, f"Subject mismatch: expected '{target_subject}', found '{subject}' (code {code})"

    # Check board if specified
    if target_board:
        target_board_lower = target_board.lower()
        board_lower = board.lower() if board else ""

        # Handle board name variations
        board_match = False
        if target_board_lower in board_lower or board_lower in target_board_lower:
            board_match = True
        # Handle short codes
        if target_board_lower in ["cie", "cambridge"] and "cie" in board_lower:
            board_match = True
        if target_board_lower in ["edexcel", "edx"] and "edexcel" in board_lower:
            board_match = True
        if target_board_lower in ["aqa"] and "aqa" in board_lower:
            board_match = True

        if not board_match:
            return False, f"Board mismatch: expected '{target_board}', found '{board}' (code {code})"

    if target_level:
        if detected_level is None:
            return False, f"Cannot determine level for '{filename}'"
        if detected_level not in {target_level.lower(), "both"}:
            return False, f"Level mismatch: expected '{target_level}', found '{detected_level}'"

    return True, f"Valid: {subject} ({code})"


def scrape_pdfs(
    url,
    output_dir="downloaded_pdfs",
    target_subject=None,
    target_board=None,
    target_level=None,
    logger=None,
):
    """Download all PDFs from a webpage.

    Args:
        url: Target webpage URL
        output_dir: Directory to save PDFs (default: downloaded_pdfs)
        target_subject: Subject name to use if not detectable (e.g., "biology")
        target_board: Board name to use if not detectable (e.g., "cie", "edexcel")
        target_level: Optional IB level filter ("sl" or "hl")
        logger: Optional callback function for logging (e.g., lambda msg: log_text.insert('end', msg))
    """
    log = _make_logger(logger)
    os.makedirs(output_dir, exist_ok=True)

    if _is_savemyexams_dp_past_papers(url):
        return _download_savemyexams_dp_papers(
            url,
            output_dir,
            target_subject=target_subject,
            target_level=target_level,
            logger=logger,
        )

    # Setup Chrome
    options = Options()
    options.add_argument("--headless")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    try:
        driver.get(url)
        time.sleep(2)

        # Find all links
        links = driver.find_elements(By.TAG_NAME, "a")
        pdf_urls = []

        for link in links:
            href = link.get_attribute("href")
            if not href:
                continue

            # Check if URL has ?pdf= parameter
            if "?pdf=" in href or "&pdf=" in href:
                from urllib.parse import parse_qs
                parsed = urlparse(href)
                params = parse_qs(parsed.query)
                if "pdf" in params:
                    actual_pdf_url = params["pdf"][0]

                    # Extract descriptive name from multiple sources
                    text = link.text.strip()
                    title = link.get_attribute("title") or ""
                    aria_label = link.get_attribute("aria-label") or ""

                    # Try to get parent container text for context
                    try:
                        parent = link.find_element(By.XPATH, "./ancestor::*[contains(@class, 'card') or contains(@class, 'item') or contains(@class, 'paper')]")
                        parent_text = parent.text.strip()
                    except:
                        parent_text = ""

                    # Get the actual filename from PDF URL
                    pdf_filename = os.path.basename(urlparse(actual_pdf_url).path)

                    # Combine info for better naming
                    name = text or title or aria_label or parent_text or pdf_filename

                    pdf_urls.append({
                        "url": actual_pdf_url,
                        "name": name,
                        "original_filename": pdf_filename
                    })
            elif href.lower().endswith(".pdf"):
                # Direct PDF links
                text = link.text.strip()
                title = link.get_attribute("title") or ""
                aria_label = link.get_attribute("aria-label") or ""
                parent_text = ""
                try:
                    parent = link.find_element(By.XPATH, "..")
                    parent_text = parent.text.strip()
                except:
                    pass
                name = text or title or aria_label or parent_text
                pdf_urls.append({
                    "url": urljoin(url, href),
                    "name": name,
                    "original_filename": os.path.basename(urlparse(href).path)
                })

        log(f"Found {len(pdf_urls)} PDFs\n")

        # Show all PDFs found
        for idx, item in enumerate(pdf_urls, 1):
            log(f"[{idx}] {item['name'][:80]}")

        # Download each PDF
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        downloaded = 0
        skipped_wrong_subject = 0

        for i, item in enumerate(pdf_urls, 1):
            pdf_url = item["url"]
            name = item["name"]
            original_filename = item["original_filename"]

            # Verify PDF belongs to target subject/board before downloading
            if target_subject:
                is_valid, reason = _verify_pdf_belongs_to(
                    original_filename,
                    target_subject,
                    target_board,
                    target_level=target_level,
                    context_text=name,
                )
                if not is_valid:
                    log(f"[{i}/{len(pdf_urls)}] SKIP - {reason}")
                    skipped_wrong_subject += 1
                    continue
                log(f"[{i}/{len(pdf_urls)}] VERIFIED - {reason}")

            try:
                response = requests.get(pdf_url, headers=headers, allow_redirects=True, stream=True, timeout=30)

                # Check if it's actually a PDF
                content_type = response.headers.get("Content-Type", "")
                if "pdf" not in content_type.lower() and not pdf_url.lower().endswith(".pdf"):
                    log(f"[{i}/{len(pdf_urls)}] SKIP - Not a PDF")
                    continue

                response.raise_for_status()

                # Try to parse and convert filename to standard format
                filename = parse_filename_to_standard(original_filename)

                # If still original and we have a descriptive name, use that
                if filename == original_filename and name and name != original_filename:
                    clean_name = name[:150].replace("/", "-").replace("\\", "-").replace(":", "-").replace("?", "").replace("*", "").replace("|", "").replace('"', "").replace("<", "").replace(">", "")
                    if not clean_name.endswith(".pdf"):
                        clean_name += ".pdf"
                    filename = clean_name

                log(f"[{i}/{len(pdf_urls)}] DOWNLOADING - {filename}")
                filepath = os.path.join(output_dir, filename)

                # Avoid overwriting existing files
                if os.path.exists(filepath):
                    base, ext = os.path.splitext(filename)
                    counter = 1
                    while os.path.exists(filepath):
                        filepath = os.path.join(output_dir, f"{base}_{counter}{ext}")
                        counter += 1

                with open(filepath, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                downloaded += 1

            except Exception as e:
                log(f"[{i}/{len(pdf_urls)}] ERROR - {str(e)}")

        log(f"\nDownloaded {downloaded} PDFs to {output_dir}")
        if skipped_wrong_subject > 0:
            log(f"Skipped {skipped_wrong_subject} PDFs (wrong subject/board)")
        return downloaded

    finally:
        driver.quit()


def scrape_for_specific_files(url, output_dir, target_patterns):
    """Download PDFs matching specific patterns.

    Args:
        url: Target webpage URL
        output_dir: Directory to save PDFs
        target_patterns: List of patterns to search for (e.g., ['9700_s18', '0620_w22'])
                        Can include wildcards like '*_s18_*'

    Returns:
        dict with 'downloaded', 'skipped', 'not_found' counts
    """
    import fnmatch

    log = _make_logger()

    os.makedirs(output_dir, exist_ok=True)

    options = Options()
    options.add_argument("--headless")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    results = {"downloaded": 0, "skipped": 0, "not_found": [], "errors": []}

    try:
        driver.get(url)
        time.sleep(2)

        links = driver.find_elements(By.TAG_NAME, "a")
        pdf_urls = []

        for link in links:
            href = link.get_attribute("href")
            if not href:
                continue

            if "?pdf=" in href or "&pdf=" in href:
                from urllib.parse import parse_qs
                parsed = urlparse(href)
                params = parse_qs(parsed.query)
                if "pdf" in params:
                    actual_pdf_url = params["pdf"][0]
                    pdf_filename = os.path.basename(urlparse(actual_pdf_url).path)
                    text = link.text.strip()
                    title = link.get_attribute("title") or ""
                    name = text or title or pdf_filename
                    pdf_urls.append({
                        "url": actual_pdf_url,
                        "name": name,
                        "original_filename": pdf_filename
                    })
            elif href.lower().endswith(".pdf"):
                text = link.text.strip()
                title = link.get_attribute("title") or ""
                name = text or title
                pdf_urls.append({
                    "url": urljoin(url, href),
                    "name": name,
                    "original_filename": os.path.basename(urlparse(href).path)
                })

        log(f"Found {len(pdf_urls)} PDFs on page")
        log(f"Looking for patterns: {target_patterns}")

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        matched_patterns = set()
        for i, item in enumerate(pdf_urls, 1):
            pdf_url = item["url"]
            original_filename = item["original_filename"]

            matched = False
            for pattern in target_patterns:
                if fnmatch.fnmatch(original_filename.lower(), pattern.lower()):
                    matched = True
                    break

            if not matched:
                for pattern in target_patterns:
                    pattern_base = pattern.lower().replace("_", "").replace("-", "")
                    filename_base = original_filename.lower().replace("_", "").replace("-", "")
                    if pattern_base in filename_base or fnmatch.fnmatch(filename_base, f"*{pattern_base}*"):
                        matched = True
                        break

            if not matched:
                log(f"[{i}/{len(pdf_urls)}] SKIP - No pattern match: {original_filename}")
                results["skipped"] += 1
                continue

            matched_patterns.add(original_filename)
            log(f"[{i}/{len(pdf_urls)}] MATCHED: {original_filename}")

            try:
                response = requests.get(pdf_url, headers=headers, allow_redirects=True, stream=True, timeout=30)
                content_type = response.headers.get("Content-Type", "")
                if "pdf" not in content_type.lower() and not pdf_url.lower().endswith(".pdf"):
                    log("  SKIP - Not a PDF")
                    results["skipped"] += 1
                    continue

                response.raise_for_status()

                filename = parse_filename_to_standard(original_filename)
                if filename == original_filename:
                    clean_name = original_filename[:150]
                    filename = clean_name

                filepath = os.path.join(output_dir, filename)
                if os.path.exists(filepath):
                    log(f"  SKIP - Already exists: {filename}")
                    results["skipped"] += 1
                    continue

                with open(filepath, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                results["downloaded"] += 1
                log(f"  DOWNLOADED: {filename}")

            except Exception as e:
                log(f"  ERROR: {str(e)}")
                results["errors"].append(f"{original_filename}: {str(e)}")

        for pattern in target_patterns:
            if pattern not in matched_patterns:
                results["not_found"].append(pattern)

        log(f"\nResults: Downloaded={results['downloaded']}, Skipped={results['skipped']}")
        if results["not_found"]:
            log(f"Not found: {results['not_found']}")
        return results

    finally:
        driver.quit()


def scrape_all_subjects(base_url, subject_folders):
    """Scrape PDFs for multiple subjects from a single page or multiple pages.

    Args:
        base_url: URL or list of URLs to scrape
        subject_folders: dict mapping subject -> output_dir

    Returns:
        dict mapping subject -> results
    """
    results = {}

    for subject, output_dir in subject_folders.items():
        if isinstance(base_url, dict):
            url = base_url.get(subject, "")
        else:
            url = base_url

        if not url:
            results[subject] = {"error": "No URL configured for this subject"}
            continue

        print(f"\n{'='*50}")
        print(f"Scraping {subject}...")
        print(f"URL: {url}")
        print(f"Output: {output_dir}")

        try:
            result = scrape_pdfs(url, output_dir, target_subject=subject)
            results[subject] = {"downloaded": result}
        except Exception as e:
            print(f"Error: {str(e)}")
            results[subject] = {"error": str(e)}

    return results


def discover_subjects_from_url(base_url, logger=None):
    """Discover all subjects from a URL without downloading anything.

    Args:
        base_url: URL to scrape (e.g., https://www.savemyexams.com/igcse)
        logger: Optional callback for logging

    Returns:
        dict mapping subject_key -> {"subject": str, "board": str, "level": str, "url": str}
    """
    log = _make_logger(logger)

    if _is_savemyexams_dp_root(base_url):
        return _discover_savemyexams_dp_subjects(base_url, logger=logger)

    from selenium.webdriver.common.by import By
    options = Options()
    options.add_argument("--headless")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    subject_data = {}

    try:
        log(f"Discovering subjects from: {base_url}")
        driver.get(base_url)
        time.sleep(2)

        last_height = driver.execute_script("return document.body.scrollHeight")
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        driver.execute_script("window.scrollTo(0, 0)")

        base_url_lower = base_url.lower().rstrip("/")
        is_dp = "/dp" in base_url_lower

        links = driver.find_elements(By.TAG_NAME, "a")
        for link in links:
            href = link.get_attribute("href")
            if not href:
                continue

            href_lower = href.lower().strip()

            if href_lower.startswith("http") and base_url_lower in href_lower:
                if is_dp and "past-papers" in href_lower:
                    subject, board = _parse_dp_subject_from_href(href_lower)
                    if subject:
                        key = subject
                        subject_data[key] = {
                            "subject": subject,
                            "board": board.upper() if board else "IB",
                            "level": "IB",
                            "url": href,
                        }
                    continue

                if "past-papers" in href_lower or "pastpapers" in href_lower:
                    parts = href_lower.split("/")
                    level = None
                    subject = None
                    board = None

                    for i, part in enumerate(parts):
                        if part in ["a-level", "alevel", "as", "igcse", "gcse"]:
                            level = part.replace("-", " ").title()
                            if i + 1 < len(parts):
                                subject = parts[i + 1].replace("-", " ").title()
                            if i + 2 < len(parts):
                                board = parts[i + 2].replace("-", " ").upper()
                            break

                    if subject and level:
                        key = f"{subject} - {board}" if board else subject
                        if key not in subject_data:
                            subject_data[key] = {"subject": subject, "board": board, "level": level, "url": href}
                elif href_lower != base_url_lower:
                    parts = href_lower.split("/")
                    for i, part in enumerate(parts):
                        if part in ["a-level", "alevel", "as", "igcse", "gcse"]:
                            level = part.replace("-", " ").title()
                            if i + 1 < len(parts) and parts[i + 1]:
                                subject = parts[i + 1].replace("-", " ").title()
                                if i + 2 < len(parts):
                                    possible_board = parts[i + 2]
                                    if possible_board.lower() in ["cie", "edexcel", "oxford-aqa", "aqa", "ocr", "wjec"]:
                                        continue
                                if subject and 1 < len(subject) < 40:
                                    subject_lower = subject.lower()
                                    has_board_variant = any(
                                        v["subject"].lower() == subject_lower and v["board"]
                                        for v in subject_data.values()
                                    )
                                    if not has_board_variant:
                                        key = subject
                                        if key not in subject_data:
                                            subject_data[key] = {"subject": subject, "board": None, "level": level, "url": href.rstrip("/") + "/past-papers/"}
                            break

        return subject_data

    finally:
        driver.quit()


def scrape_all_subjects_from_url(base_url, output_dir, logger=None):
    """Auto-discover all subjects from a URL and download their past papers.

    Args:
        base_url: URL to scrape (e.g., https://www.savemyexams.com/igcse)
        output_dir: Base output directory
        logger: Optional callback for logging

    Returns:
        dict mapping subject -> download results
    """
    log = _make_logger(logger)

    from selenium.webdriver.common.by import By
    options = Options()
    options.add_argument("--headless")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    results = {}

    try:
        log(f"Discovering subjects from: {base_url}")
        driver.get(base_url)
        time.sleep(2)

        last_height = driver.execute_script("return document.body.scrollHeight")
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        driver.execute_script("window.scrollTo(0, 0)")

        subject_data = {}
        base_url_lower = base_url.lower().rstrip("/")
        is_dp = "/dp" in base_url_lower

        links = driver.find_elements(By.TAG_NAME, "a")
        for link in links:
            href = link.get_attribute("href")
            if not href:
                continue

            href_lower = href.lower().strip()

            if href_lower.startswith("http") and base_url_lower in href_lower:
                if is_dp and "past-papers" in href_lower:
                    subject, board = _parse_dp_subject_from_href(href_lower)
                    if subject:
                        key = subject
                        subject_data[key] = {
                            "subject": subject,
                            "board": board.upper() if board else "IB",
                            "level": "IB",
                            "url": href,
                        }
                    continue

                if "past-papers" in href_lower or "pastpapers" in href_lower:
                    parts = href_lower.split("/")
                    level = None
                    subject = None
                    board = None

                    for i, part in enumerate(parts):
                        if part in ["a-level", "alevel", "as", "igcse", "gcse"]:
                            level = part.replace("-", " ").title()
                            if i + 1 < len(parts):
                                subject = parts[i + 1].replace("-", " ").title()
                            if i + 2 < len(parts):
                                board = parts[i + 2].replace("-", " ").upper()
                            break

                    if subject and level:
                        key = f"{subject} - {board}" if board else subject
                        if key not in subject_data:
                            subject_data[key] = {"subject": subject, "board": board, "level": level, "url": href}
                elif href_lower != base_url_lower:
                    parts = href_lower.split("/")
                    for i, part in enumerate(parts):
                        if part in ["a-level", "alevel", "as", "igcse", "gcse"]:
                            level = part.replace("-", " ").title()
                            if i + 1 < len(parts) and parts[i + 1]:
                                subject = parts[i + 1].replace("-", " ").title()
                                if subject and 1 < len(subject) < 40:
                                    key = subject
                                    if key not in subject_data:
                                        subject_data[key] = {"subject": subject, "board": None, "level": level, "url": href.rstrip("/") + "/past-papers/"}
                            break

        log(f"Found {len(subject_data)} subject links")
        for k, v in subject_data.items():
            log(f"  - {k}: {v['url']}")

        if not subject_data:
            log("No past-papers links found on this page")
            return {"error": "No past-papers links found"}

        for key, data in sorted(subject_data.items()):
            subject = data["subject"]
            board = data["board"]
            level = data.get("level", "")
            url = data["url"]

            if "past-papers" not in url.lower():
                url = url.rstrip("/") + "/past-papers/"

            if level:
                folder_name = f"{level}/{subject} ({board})" if board else f"{level}/{subject}"
            else:
                folder_name = f"{subject} ({board})" if board else subject

            subject_dir = os.path.join(output_dir, folder_name, "past-papers")
            os.makedirs(subject_dir, exist_ok=True)

            log(f"\n{'='*50}")
            log(f"Subject: {folder_name}")
            log(f"URL: {url}")
            log(f"Output: {subject_dir}")

            try:
                result = scrape_pdfs(url, subject_dir, target_subject=subject, target_board=board, logger=logger)
                results[key] = {"downloaded": result, "url": url}
            except Exception as e:
                log(f"Error scraping {key}: {e}")
                results[key] = {"error": str(e), "url": url}

        log(f"\n{'='*50}")
        log("=== FINAL RESULTS ===")
        total = 0
        for subj, res in sorted(results.items()):
            if "downloaded" in res:
                total += res["downloaded"]
                log(f"{subj}: {res['downloaded']} files")
            elif "error" in res:
                log(f"{subj}: ERROR - {res['error']}")
        log(f"Total: {total} files downloaded")

        return results

    finally:
        driver.quit()


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python pdf_scraper.py <url> [output_dir]")
        sys.exit(1)

    url = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "downloaded_pdfs"

    scrape_pdfs(url, output_dir)
