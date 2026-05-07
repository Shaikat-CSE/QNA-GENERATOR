# Batch rename PDFs using LLM-generated subject-specific rules.

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.minimax_client import MiniMaxClient, MiniMaxConfig
from src.pdf_availability_scanner import ReviewItem, extract_subject_syllabus_from_folder, scan_pdf_directory_report
from src.renamer_engine import PDFRenamer, RenamingSuggestion, RuleGenerator, SubjectRule
from src.rule_manager import RuleManager

DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _load_env() -> None:
    if DEFAULT_ENV_FILE.exists():
        try:
            from src.convert_pdfs_to_markdown import load_env_file
        except ImportError:
            from convert_pdfs_to_markdown import load_env_file
        load_env_file(DEFAULT_ENV_FILE, overwrite=True)


@dataclass
class FolderResult:
    folder: Path
    subject: str
    syllabus: str
    processed: int
    renamed: int
    low_confidence: int
    errors: list[str]


async def generate_rules_for_folder(
    folder: Path,
    subject: str,
    syllabus: str,
    client: MiniMaxClient,
    rule_manager: RuleManager,
    logger: callable | None = None,
    max_concurrency: int = 5,
) -> tuple[int, list[str]]:
    def log(msg: str) -> None:
        if logger:
            logger(msg)
        else:
            print(msg)

    pdfs = list(folder.glob("*.pdf"))
    if not pdfs:
        return 0, []

    generator = RuleGenerator(client)
    errors = []
    count = 0

    sample_pdfs = pdfs[:5]

    async def process_pdf(pdf: Path) -> tuple[bool, str | None, str | None]:
        def run_sync():
            return generator.generate_rules_for_pdf(pdf, subject, syllabus)

        try:
            rule = await asyncio.to_thread(run_sync)
            if rule.code != "unknown":
                rule_manager.add_rule(rule)
                return True, f"  Rule: {subject}/{syllabus} -> {rule.code}", None
            return False, None, None
        except Exception as e:
            return False, None, f"{pdf.name}: {e}"

    semaphore = asyncio.Semaphore(max_concurrency)

    async def bounded_process_pdf(pdf: Path) -> tuple[bool, str | None, str | None]:
        async with semaphore:
            return await process_pdf(pdf)

    results = await asyncio.gather(*[bounded_process_pdf(pdf) for pdf in sample_pdfs])

    for success, msg, err in results:
        if success and msg:
            count += 1
            log(msg)
        elif err:
            errors.append(err)
            log(f"  ERROR: {err}")

    return count, errors


async def process_folder(
    folder: Path,
    subject: str,
    syllabus: str,
    client: MiniMaxClient,
    rule_manager: RuleManager,
    logger: callable | None = None,
    max_concurrency: int = 5,
) -> FolderResult:
    def log(msg: str) -> None:
        if logger:
            logger(msg)
        else:
            print(msg)

    renamer = PDFRenamer(client)
    pdfs = list(folder.glob("*.pdf"))
    candidates = [pdf for pdf in pdfs if renamer.needs_rename(pdf)]
    semaphore = asyncio.Semaphore(max_concurrency)

    async def get_suggestion(pdf: Path):
        def run_sync():
            return renamer.suggest_rename(pdf, rule_manager.rules)

        try:
            return await asyncio.to_thread(run_sync)
        except Exception as e:
            return None, pdf.name, str(e)

    async def bounded_get_suggestion(pdf: Path):
        async with semaphore:
            return await get_suggestion(pdf)

    suggestions = await asyncio.gather(*[bounded_get_suggestion(pdf) for pdf in candidates])

    renamed = 0
    low_conf = 0
    errors = []
    results_key = []

    for i, pdf in enumerate(candidates):
        suggestion = suggestions[i]
        if suggestion is None:
            errors.append(f"{pdf.name}: Unknown error")
            continue

        if isinstance(suggestion, tuple):
            _, name, err = suggestion
            errors.append(f"{name}: {err}")
            log(f"  ERROR: {name}: {err}")
            continue

        results_key.append({
            "original": pdf.name,
            "suggested": suggestion.suggested_name,
            "confidence": suggestion.confidence,
            "reason": suggestion.reason,
            "matched_rule": suggestion.matched_rule,
        })

        if suggestion.confidence > 0.7:
            final_name = suggestion.suggested_name
            if not final_name.lower().endswith(".pdf"):
                final_name = f"{final_name}.pdf"
            new_path, should_rename = _resolve_rename_target(pdf, final_name, renamer)
            if new_path == pdf:
                log(f"  Already standardized: {pdf.name}")
                continue
            if should_rename:
                pdf.rename(new_path)
                renamed += 1
                log(f"  Renamed: {pdf.name} -> {new_path.name}")
        else:
            low_conf += 1
            log(f"  Low conf ({suggestion.confidence:.2f}): {pdf.name}")

    report_file = folder / "renaming_report.json"
    with report_file.open("w", encoding="utf-8") as f:
        f.write(json.dumps(results_key, indent=2, ensure_ascii=False))

    return FolderResult(
        folder=folder,
        subject=subject,
        syllabus=syllabus,
        processed=len(pdfs),
        renamed=renamed,
        low_confidence=low_conf,
        errors=errors,
    )


def _find_pdf_folders(base_path: Path) -> list[Path]:
    """Recursively find all folders containing PDFs."""
    results = []
    for item in base_path.iterdir():
        if item.is_dir():
            if (item / "resources").is_dir():
                continue
            pdfs = list(item.glob("*.pdf"))
            if pdfs:
                results.append(item)
            results.extend(_find_pdf_folders(item))
    return results


def _find_all_pdfs(base_path: Path) -> list[Path]:
    """Recursively find all PDF files."""
    return list(base_path.glob("**/*.pdf"))


def _looks_like_duplicate_artifact(path: Path) -> bool:
    stem = path.stem.lower()
    return bool(
        "(" in stem
        or "_duplicate" in stem
        or re.search(r"_[1-9]\d*$", stem)
        or re.search(r"-(qp|ms|in|er|transcript|sqp|sm|sp|prm|pm|te|gt)-[a-f0-9]{8,}(?:-\d+)?$", stem)
    )


def _find_unmapped_review_items(base_path: Path) -> list[ReviewItem]:
    report = scan_pdf_directory_report(base_path)
    used_paths: set[str] = set()
    for paper in report.papers:
        for value in (
            paper.qp_path,
            paper.ms_path,
            paper.er_path,
            paper.in_path,
            paper.transcript_path,
        ):
            if value and value != "-":
                used_paths.add(value)
    return [item for item in report.review_items if item.path not in used_paths]


def _find_unknown_year_file_items(base_path: Path) -> list[ReviewItem]:
    report = scan_pdf_directory_report(base_path)
    items: list[ReviewItem] = []
    seen: set[str] = set()
    for paper in report.papers:
        if paper.year != "unknown":
            continue
        for value, label in (
            (paper.qp_path, "Unknown-year QP"),
            (paper.ms_path, "Unknown-year MS"),
            (paper.er_path, "Unknown-year ER"),
            (paper.in_path, "Unknown-year IN"),
            (paper.transcript_path, "Unknown-year Transcript"),
        ):
            if not value or value == "-" or value in seen:
                continue
            seen.add(value)
            items.append(
                ReviewItem(
                    filename=Path(value).name,
                    path=value,
                    reason=f"{label}: {paper.paper_key}",
                    suggestion="",
                )
            )
    return items


def _resolve_rename_target(pdf: Path, final_name: str, renamer: PDFRenamer) -> tuple[Path, bool]:
    target = pdf.parent / final_name
    if target == pdf:
        return target, False
    if not target.exists():
        return target, True
    duplicate_index = 1
    while True:
        duplicate_name = renamer.build_duplicate_name(final_name.removesuffix(".pdf"), duplicate_index)
        duplicate_target = pdf.parent / f"{duplicate_name}.pdf"
        if duplicate_target == pdf:
            return duplicate_target, False
        if not duplicate_target.exists():
            return duplicate_target, True
        duplicate_index += 1


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _apply_rename_or_dedupe(
    pdf: Path,
    final_name: str,
    renamer: PDFRenamer,
) -> tuple[str, Path]:
    direct_target = pdf.parent / final_name
    if direct_target == pdf:
        return "already", direct_target
    if direct_target.exists():
        try:
            if _file_sha256(pdf) == _file_sha256(direct_target):
                pdf.unlink()
                return "deleted_duplicate", direct_target
        except OSError:
            pass
    new_path, should_rename = _resolve_rename_target(pdf, final_name, renamer)
    if new_path == pdf:
        return "already", new_path
    if should_rename:
        pdf.rename(new_path)
        return "renamed", new_path
    return "unresolved", new_path


def _infer_folder_metadata(base_path: Path, folder: Path) -> tuple[str, str]:
    level_name = base_path.name.lower()
    if "a-level" in level_name or "alevel" in level_name:
        syllabus = "a-level"
    elif "igcse" in level_name:
        syllabus = "igcse"
    elif "ib" in level_name:
        syllabus = "ib"
    else:
        syllabus = "unknown"

    current = folder
    subject = "unknown"
    for _ in range(4):
        inferred_subject, _ = extract_subject_syllabus_from_folder(current)
        if inferred_subject != "unknown":
            subject = inferred_subject
            break
        if current.parent == current:
            break
        current = current.parent

    if subject == "unknown":
        try:
            relative_parts = folder.relative_to(base_path).parts
            if relative_parts:
                subject = relative_parts[0]
        except ValueError:
            subject = folder.parent.name

    return subject, syllabus


def _find_rule_sample_folders(base_path: Path) -> list[tuple[Path, str, str]]:
    folders = _find_pdf_folders(base_path)
    results: list[tuple[Path, str, str]] = []
    seen: set[str] = set()
    for folder in folders:
        key = str(folder.resolve())
        if key in seen:
            continue
        seen.add(key)
        subject, syllabus = _infer_folder_metadata(base_path, folder)
        results.append((folder, subject, syllabus))
    return results


def _find_past_paper_folders(base_path: Path, subject: str = "") -> list[tuple[Path, str]]:
    """Recursively find past-papers folders and their subject name."""
    results = []
    for item in base_path.iterdir():
        if not item.is_dir():
            continue
        if item.name == "resources":
            continue
        if item.name == "past-papers":
            results.append((item, subject if subject else base_path.name))
        else:
            results.extend(_find_past_paper_folders(item, item.name))
    return results


async def batch_generate_rules(
    base_path: Path,
    client: MiniMaxClient,
    rule_manager: RuleManager,
    logger: callable | None = None,
    max_concurrency: int = 3,
) -> dict[str, int]:
    """Generate rules from representative PDFs across the folder tree."""
    results: dict[str, int] = {}

    def log(msg: str) -> None:
        if logger:
            logger(msg)
        else:
            print(msg)

    folders = _find_rule_sample_folders(base_path)
    if not folders:
        log(f"No PDFs found in {base_path}")
        return results

    total_pdfs = sum(len(list(folder.glob("*.pdf"))) for folder, _, _ in folders)
    log(f"Found {total_pdfs} PDFs across {len(folders)} folders, generating rules...")

    generator = RuleGenerator(client)
    counts: dict[str, int] = {}

    async def process_pdf(pdf: Path, subject: str, syllabus: str) -> tuple[bool, str | None, str | None, str | None]:
        def run_sync():
            return generator.generate_rules_for_pdf(pdf, subject, syllabus)

        try:
            rule = await asyncio.to_thread(run_sync)
            if rule.code != "unknown":
                rule_manager.add_rule(rule)
                return True, f"  Rule: {rule.subject}/{rule.code}", None, rule.code.lower()
            return False, None, None, None
        except Exception as e:
            return False, None, f"{pdf.name}: {e}", None

    semaphore = asyncio.Semaphore(max_concurrency)
    tasks = []
    for folder, subject, syllabus in folders:
        folder_pdfs = sorted(folder.glob("*.pdf"))[:3]
        if not folder_pdfs:
            continue
        log(f"[rules] {folder} :: {subject} / {syllabus} :: {len(folder_pdfs)} sample(s)")
        for pdf in folder_pdfs:
            async def bounded_process_pdf(
                pdf_path: Path = pdf,
                subject_name: str = subject,
                syllabus_name: str = syllabus,
            ) -> tuple[bool, str | None, str | None, str | None]:
                async with semaphore:
                    return await process_pdf(pdf_path, subject_name, syllabus_name)

            tasks.append(bounded_process_pdf())

    batch_results = await asyncio.gather(*tasks)

    total = 0
    for success, msg, err, code in batch_results:
        if success and msg and code:
            total += 1
            counts[code] = counts.get(code, 0) + 1
            log(msg)
        elif err:
            log(f"  ERROR: {err}")

    results["all"] = total
    for code, count in sorted(counts.items()):
        results[code] = count
    return results


async def batch_process(
    base_path: Path,
    client: MiniMaxClient,
    rule_manager: RuleManager,
    logger: callable | None = None,
    max_concurrency: int = 3,
) -> list[FolderResult]:
    """Scan base_path for all PDFs recursively and process them."""

    def log(msg: str) -> None:
        if logger:
            logger(msg)
        else:
            print(msg)

    pdfs = _find_all_pdfs(base_path)
    if not pdfs:
        log(f"No PDFs found in {base_path}")
        return []

    renamer = PDFRenamer(client)
    candidates = [pdf for pdf in pdfs if renamer.needs_rename(pdf)]
    if not candidates:
        log(f"Found {len(pdfs)} PDFs, nothing needs renaming.")
        return [FolderResult(
            folder=base_path,
            subject="all",
            syllabus="all",
            processed=0,
            renamed=0,
            low_confidence=0,
            errors=[],
        )]

    log(f"Found {len(pdfs)} PDFs, processing {len(candidates)} rename candidate(s)...")
    semaphore = asyncio.Semaphore(max_concurrency)

    async def get_suggestion(pdf: Path):
        def run_sync():
            return renamer.suggest_rename(pdf, rule_manager.rules)

        try:
            return await asyncio.to_thread(run_sync)
        except Exception as e:
            return None, pdf.name, str(e)

    async def bounded_get_suggestion(pdf: Path):
        async with semaphore:
            return pdf, await get_suggestion(pdf)

    suggestions_by_path: dict[Path, object] = {}
    tasks = [asyncio.create_task(bounded_get_suggestion(pdf)) for pdf in candidates]
    completed = 0
    total = len(tasks)
    for task in asyncio.as_completed(tasks):
        pdf, suggestion = await task
        suggestions_by_path[pdf] = suggestion
        completed += 1
        log(f"  Progress: {completed}/{total}")

    renamed = 0
    low_conf = 0
    errors = []
    results_key = []

    for i, pdf in enumerate(candidates):
        suggestion = suggestions_by_path.get(pdf)
        if suggestion is None:
            errors.append(f"{pdf.name}: Unknown error")
            continue

        if isinstance(suggestion, tuple):
            _, name, err = suggestion
            errors.append(f"{name}: {err}")
            log(f"  ERROR: {name}: {err}")
            continue

        results_key.append({
            "original": pdf.name,
            "suggested": suggestion.suggested_name,
            "confidence": suggestion.confidence,
            "reason": suggestion.reason,
            "matched_rule": suggestion.matched_rule,
        })

        if suggestion.confidence > 0.7:
            final_name = suggestion.suggested_name
            if not final_name.lower().endswith(".pdf"):
                final_name = f"{final_name}.pdf"
            action, new_path = _apply_rename_or_dedupe(pdf, final_name, renamer)
            if action == "already":
                log(f"  Already standardized: {pdf.name}")
            elif action == "deleted_duplicate":
                renamed += 1
                log(f"  Deleted duplicate: {pdf.name} (matches {new_path.name})")
            elif action == "renamed":
                renamed += 1
                log(f"  Renamed: {pdf.name} -> {new_path.name}")
            else:
                low_conf += 1
                log(f"  Could not resolve target: {pdf.name} -> {final_name}")
        else:
            low_conf += 1
            log(f"  Low conf ({suggestion.confidence:.2f}): {pdf.name}")

    report_file = base_path / "renaming_report.json"
    with report_file.open("w", encoding="utf-8") as f:
        f.write(json.dumps(results_key, indent=2, ensure_ascii=False))

    return [FolderResult(
        folder=base_path,
        subject="all",
        syllabus="all",
        processed=len(candidates),
        renamed=renamed,
        low_confidence=low_conf,
        errors=errors,
    )]


async def batch_process_duplicate_cleanup(
    base_path: Path,
    client: MiniMaxClient,
    rule_manager: RuleManager,
    logger: callable | None = None,
) -> list[FolderResult]:
    def log(msg: str) -> None:
        if logger:
            logger(msg)
        else:
            print(msg)

    renamer = PDFRenamer(client)
    candidates = [pdf for pdf in _find_all_pdfs(base_path) if _looks_like_duplicate_artifact(pdf)]
    if not candidates:
        log(f"No duplicate-artifact files found in {base_path}")
        return [FolderResult(
            folder=base_path,
            subject="duplicate-cleanup",
            syllabus="duplicate-cleanup",
            processed=0,
            renamed=0,
            low_confidence=0,
            errors=[],
        )]

    log(f"Found {len(candidates)} duplicate-artifact file(s), cleaning up...")
    renamed = 0
    unresolved = 0
    errors: list[str] = []

    for index, pdf in enumerate(candidates, start=1):
        log(f"  Duplicate cleanup progress: {index}/{len(candidates)}")
        try:
            final_name = f"{renamer._normalize_name(pdf.name)}.pdf"
            if final_name.lower() == pdf.name.lower():
                continue
            action, new_path = _apply_rename_or_dedupe(pdf, final_name, renamer)
            if action == "already":
                continue
            if action == "deleted_duplicate":
                renamed += 1
                log(f"  Deleted duplicate: {pdf.name} (matches {new_path.name})")
            elif action == "renamed":
                renamed += 1
                log(f"  Renamed: {pdf.name} -> {new_path.name}")
            else:
                unresolved += 1
                log(f"  Could not resolve target: {pdf.name} -> {final_name}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{pdf.name}: {exc}")
            log(f"  ERROR: {pdf.name}: {exc}")

    return [FolderResult(
        folder=base_path,
        subject="duplicate-cleanup",
        syllabus="duplicate-cleanup",
        processed=len(candidates),
        renamed=renamed,
        low_confidence=unresolved,
        errors=errors,
    )]


def _review_item_direct_suggestion(
    renamer: PDFRenamer,
    pdf_path: Path,
    review_item: ReviewItem,
) -> RenamingSuggestion | None:
    suggestion_text = review_item.suggestion.strip()
    if not suggestion_text:
        return None
    normalized = renamer._normalize_name(suggestion_text)
    if not normalized:
        return None
    if not renamer._is_well_named(normalized):
        return None
    if renamer._contains_placeholder_tokens(normalized):
        return None
    return RenamingSuggestion(
        original_path=pdf_path,
        suggested_name=normalized,
        confidence=0.98,
        reason=f"Scanner suggestion: {review_item.reason}",
        matched_rule="review-suggestion",
    )


async def batch_process_review_only(
    base_path: Path,
    client: MiniMaxClient,
    rule_manager: RuleManager,
    logger: callable | None = None,
    max_concurrency: int = 3,
    limit: int | None = None,
    force_all: bool = False,
) -> list[FolderResult]:
    """Rename only scanner review files that are not currently mapped into the availability matrix."""

    def log(msg: str) -> None:
        if logger:
            logger(msg)
        else:
            print(msg)

    review_items = _find_unmapped_review_items(base_path)
    if limit is not None:
        review_items = review_items[: max(0, limit)]
    if not review_items:
        log(f"No unmapped review files found in {base_path}")
        return [FolderResult(
            folder=base_path,
            subject="review",
            syllabus="review",
            processed=0,
            renamed=0,
            low_confidence=0,
            errors=[],
        )]

    log(f"Found {len(review_items)} unmapped review file(s), processing...")
    renamer = PDFRenamer(client)
    semaphore = asyncio.Semaphore(max_concurrency)

    async def get_suggestion(review_item: ReviewItem):
        pdf = Path(review_item.path)
        if not pdf.exists():
            return None, review_item.filename, "File no longer exists"

        direct = _review_item_direct_suggestion(renamer, pdf, review_item)
        if direct is not None:
            return pdf, review_item, direct

        def run_sync():
            # Review-only mode relies on scanner hints and MiniMax analysis,
            # not the looser subject regex rules.
            if force_all:
                return renamer.force_suggest_rename(pdf, {})
            return renamer.suggest_rename(pdf, {})

        try:
            suggestion = await asyncio.to_thread(run_sync)
            return pdf, review_item, suggestion
        except Exception as e:
            return None, review_item.filename, str(e)

    async def bounded_get_suggestion(review_item: ReviewItem):
        async with semaphore:
            return await get_suggestion(review_item)

    suggestions = []
    tasks = [asyncio.create_task(bounded_get_suggestion(item)) for item in review_items]
    completed = 0
    total = len(tasks)
    for task in asyncio.as_completed(tasks):
        result = await task
        suggestions.append(result)
        completed += 1
        log(f"  Review progress: {completed}/{total}")

    renamed = 0
    low_conf = 0
    errors: list[str] = []
    results_key = []

    for result in suggestions:
        if result is None:
            continue
        if isinstance(result, tuple) and len(result) == 3 and result[0] is None:
            _, name, err = result
            errors.append(f"{name}: {err}")
            log(f"  ERROR: {name}: {err}")
            continue

        pdf, review_item, suggestion = result
        results_key.append({
            "original": pdf.name,
            "path": str(pdf),
            "review_reason": review_item.reason,
            "review_suggestion": review_item.suggestion,
            "suggested": suggestion.suggested_name,
            "confidence": suggestion.confidence,
            "reason": suggestion.reason,
            "matched_rule": suggestion.matched_rule,
        })

        if suggestion.confidence > 0.7:
            final_name = suggestion.suggested_name
            if not final_name.lower().endswith(".pdf"):
                final_name = f"{final_name}.pdf"
            action, new_path = _apply_rename_or_dedupe(pdf, final_name, renamer)
            if action == "already":
                log(f"  Already standardized: {pdf.name}")
                continue
            if action == "deleted_duplicate":
                renamed += 1
                log(f"  Deleted duplicate: {pdf.name} (matches {new_path.name})")
                continue
            if action == "unresolved":
                low_conf += 1
                log(f"  Could not resolve target: {pdf.name} -> {final_name}")
                continue
            renamed += 1
            log(f"  Renamed: {pdf.name} -> {new_path.name}")
        else:
            low_conf += 1
            log(f"  Low conf ({suggestion.confidence:.2f}): {pdf.name}")

    report_file = base_path / "review_renaming_report.json"
    with report_file.open("w", encoding="utf-8") as f:
        f.write(json.dumps(results_key, indent=2, ensure_ascii=False))

    return [FolderResult(
        folder=base_path,
        subject="review",
        syllabus="review",
        processed=len(review_items),
        renamed=renamed,
        low_confidence=low_conf,
        errors=errors,
    )]


async def batch_process_unknown_years(
    base_path: Path,
    client: MiniMaxClient,
    rule_manager: RuleManager,
    logger: callable | None = None,
    max_concurrency: int = 3,
    limit: int | None = None,
    force_all: bool = True,
) -> list[FolderResult]:
    """Rename files attached to unknown-year paper rows so they can re-enter the availability matrix."""

    def log(msg: str) -> None:
        if logger:
            logger(msg)
        else:
            print(msg)

    unknown_items = _find_unknown_year_file_items(base_path)
    if limit is not None:
        unknown_items = unknown_items[: max(0, limit)]
    if not unknown_items:
        log(f"No unknown-year files found in {base_path}")
        return [FolderResult(
            folder=base_path,
            subject="unknown-year",
            syllabus="unknown-year",
            processed=0,
            renamed=0,
            low_confidence=0,
            errors=[],
        )]

    log(f"Found {len(unknown_items)} unknown-year file(s), processing...")
    renamer = PDFRenamer(client)
    semaphore = asyncio.Semaphore(max_concurrency)

    async def get_suggestion(item: ReviewItem):
        pdf = Path(item.path)
        if not pdf.exists():
            return None, item.filename, "File no longer exists"

        def run_sync():
            if force_all:
                return renamer.force_suggest_rename(pdf, {})
            return renamer.suggest_rename(pdf, {})

        try:
            suggestion = await asyncio.to_thread(run_sync)
            return pdf, item, suggestion
        except Exception as e:
            return None, item.filename, str(e)

    async def bounded_get_suggestion(item: ReviewItem):
        async with semaphore:
            return await get_suggestion(item)

    suggestions = []
    tasks = [asyncio.create_task(bounded_get_suggestion(item)) for item in unknown_items]
    completed = 0
    total = len(tasks)
    for task in asyncio.as_completed(tasks):
        result = await task
        suggestions.append(result)
        completed += 1
        log(f"  Unknown-year progress: {completed}/{total}")

    renamed = 0
    low_conf = 0
    errors: list[str] = []
    results_key = []

    for result in suggestions:
        if result is None:
            continue
        if isinstance(result, tuple) and len(result) == 3 and result[0] is None:
            _, name, err = result
            errors.append(f"{name}: {err}")
            log(f"  ERROR: {name}: {err}")
            continue

        pdf, item, suggestion = result
        results_key.append({
            "original": pdf.name,
            "path": str(pdf),
            "reason": item.reason,
            "suggested": suggestion.suggested_name,
            "confidence": suggestion.confidence,
            "rename_reason": suggestion.reason,
            "matched_rule": suggestion.matched_rule,
        })

        if suggestion.confidence > 0.7:
            final_name = suggestion.suggested_name
            if not final_name.lower().endswith(".pdf"):
                final_name = f"{final_name}.pdf"
            action, new_path = _apply_rename_or_dedupe(pdf, final_name, renamer)
            if action == "already":
                log(f"  Already standardized: {pdf.name}")
                continue
            if action == "deleted_duplicate":
                renamed += 1
                log(f"  Deleted duplicate: {pdf.name} (matches {new_path.name})")
                continue
            if action == "unresolved":
                low_conf += 1
                log(f"  Could not resolve target: {pdf.name} -> {final_name}")
                continue
            renamed += 1
            log(f"  Renamed: {pdf.name} -> {new_path.name}")
        else:
            low_conf += 1
            log(f"  Low conf ({suggestion.confidence:.2f}): {pdf.name}")

    report_file = base_path / "unknown_year_renaming_report.json"
    with report_file.open("w", encoding="utf-8") as f:
        f.write(json.dumps(results_key, indent=2, ensure_ascii=False))

    return [FolderResult(
        folder=base_path,
        subject="unknown-year",
        syllabus="unknown-year",
        processed=len(unknown_items),
        renamed=renamed,
        low_confidence=low_conf,
        errors=errors,
    )]


async def main_async(args: argparse.Namespace) -> None:
    _load_env()
    config = MiniMaxConfig.from_sources()
    client = MiniMaxClient(config)
    rule_manager = RuleManager()

    base_path = Path(args.base) if args.base else None

    if args.mode == "generate-rules":
        if not base_path:
            print("--base required for generate-rules mode")
            return
        print(f"Generating rules from {base_path}...")
        results = await batch_generate_rules(base_path, client, rule_manager)
        print(f"\nGenerated rules: {sum(results.values())} total")
        for k, v in sorted(results.items()):
            print(f"  {k}: {v} rules")

    elif args.mode == "rename":
        if not base_path:
            print("--base required for rename mode")
            return
        print(f"Processing PDFs in {base_path}...")
        batch_results = await batch_process(base_path, client, rule_manager)

        total_renamed = sum(r.renamed for r in batch_results)
        total_low = sum(r.low_confidence for r in batch_results)
        total_errors = sum(len(r.errors) for r in batch_results)

        print(f"\n=== Summary ===")
        print(f"  Folders: {len(batch_results)}")
        print(f"  Renamed: {total_renamed}")
        print(f"  Low confidence: {total_low}")
        print(f"  Errors: {total_errors}")

    elif args.mode == "rename-duplicate-cleanup":
        if not base_path:
            print("--base required for rename-duplicate-cleanup mode")
            return
        print(f"Cleaning duplicate-artifact PDFs in {base_path}...")
        batch_results = await batch_process_duplicate_cleanup(
            base_path,
            client,
            rule_manager,
        )

        total_renamed = sum(r.renamed for r in batch_results)
        total_low = sum(r.low_confidence for r in batch_results)
        total_errors = sum(len(r.errors) for r in batch_results)

        print(f"\n=== Summary ===")
        print(f"  Folders: {len(batch_results)}")
        print(f"  Renamed: {total_renamed}")
        print(f"  Unresolved: {total_low}")
        print(f"  Errors: {total_errors}")

    elif args.mode == "rename-review-only":
        if not base_path:
            print("--base required for rename-review-only mode")
            return
        print(f"Processing unmapped review PDFs in {base_path}...")
        batch_results = await batch_process_review_only(
            base_path,
            client,
            rule_manager,
            limit=args.limit,
            force_all=True,
        )

        total_renamed = sum(r.renamed for r in batch_results)
        total_low = sum(r.low_confidence for r in batch_results)
        total_errors = sum(len(r.errors) for r in batch_results)

        print(f"\n=== Summary ===")
        print(f"  Folders: {len(batch_results)}")
        print(f"  Renamed: {total_renamed}")
        print(f"  Low confidence: {total_low}")
        print(f"  Errors: {total_errors}")

    elif args.mode == "rename-unknown-years":
        if not base_path:
            print("--base required for rename-unknown-years mode")
            return
        print(f"Processing unknown-year PDFs in {base_path}...")
        batch_results = await batch_process_unknown_years(
            base_path,
            client,
            rule_manager,
            limit=args.limit,
            force_all=True,
        )

        total_renamed = sum(r.renamed for r in batch_results)
        total_low = sum(r.low_confidence for r in batch_results)
        total_errors = sum(len(r.errors) for r in batch_results)

        print(f"\n=== Summary ===")
        print(f"  Folders: {len(batch_results)}")
        print(f"  Renamed: {total_renamed}")
        print(f"  Low confidence: {total_low}")
        print(f"  Errors: {total_errors}")


def main():
    parser = argparse.ArgumentParser(description="Batch PDF renaming with LLM-generated rules")
    parser.add_argument(
        "--mode",
        choices=["generate-rules", "rename", "rename-duplicate-cleanup", "rename-review-only", "rename-unknown-years"],
        default="rename",
        help="Mode: generate-rules, rename, rename-duplicate-cleanup, rename-review-only, or rename-unknown-years",
    )
    parser.add_argument(
        "--base",
        help="Base folder containing PDFs (scans recursively)",
    )
    parser.add_argument(
        "--rules-file", help="Custom rules file path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional cap on the number of files processed in this run",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
