# Batch rename PDFs using LLM-generated subject-specific rules.

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.minimax_client import MiniMaxClient, MiniMaxConfig
from src.renamer_engine import PDFRenamer, RuleGenerator, SubjectRule
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

    semaphore = asyncio.Semaphore(max_concurrency)

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

    results = await asyncio.gather(*[process_pdf(pdf) for pdf in sample_pdfs])

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

    semaphore = asyncio.Semaphore(max_concurrency)

    async def get_suggestion(pdf: Path):
        def run_sync():
            return renamer.suggest_rename(pdf, rule_manager.rules)

        try:
            return await asyncio.to_thread(run_sync)
        except Exception as e:
            return None, pdf.name, str(e)

    suggestions = await asyncio.gather(*[get_suggestion(pdf) for pdf in pdfs])

    renamed = 0
    low_conf = 0
    errors = []
    results_key = []

    for i, pdf in enumerate(pdfs):
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
            new_path = pdf.parent / final_name
            if new_path != pdf and not new_path.exists():
                pdf.rename(new_path)
                renamed += 1
                log(f"  Renamed: {pdf.name} -> {final_name}")
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


def _find_past_paper_folders(base_path: Path, subject: str = "") -> list[tuple[Path, str]]:
    """Recursively find past-papers folders and their subject name."""
    results = []
    for item in base_path.iterdir():
        if not item.is_dir():
            continue
        # Skip resources folders
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
    """Scan base_path for subject folders and generate rules for each."""
    results: dict[str, int] = {}
    folders_seen = set()
    folder_tasks: list[tuple[str, Path, str, str]] = []

    for syllabus_folder in base_path.iterdir():
        if not syllabus_folder.is_dir():
            continue
        syllabus = syllabus_folder.name

        for folder, subject in _find_past_paper_folders(syllabus_folder, syllabus):
            key = f"{syllabus}/{subject}"

            if key in folders_seen:
                continue
            folders_seen.add(key)
            folder_tasks.append((key, folder, subject, syllabus))

    async def process_folder(key: str, folder: Path, subject: str, syllabus: str) -> tuple[str, int]:
        count, _ = await generate_rules_for_folder(folder, subject, syllabus, client, rule_manager, logger, max_concurrency=5)
        return key, count

    folder_results = await asyncio.gather(*[process_folder(k, f, s, syl) for k, f, s, syl in folder_tasks])

    for key, count in folder_results:
        results[key] = count

    return results


async def batch_process(
    base_path: Path,
    client: MiniMaxClient,
    rule_manager: RuleManager,
    logger: callable | None = None,
    max_concurrency: int = 3,
) -> list[FolderResult]:
    """Scan base_path for subject folders and process PDFs in each."""
    folders_seen = set()
    folder_tasks: list[tuple[Path, str, str]] = []

    for syllabus_folder in base_path.iterdir():
        if not syllabus_folder.is_dir():
            continue
        syllabus = syllabus_folder.name

        for folder, subject in _find_past_paper_folders(syllabus_folder, syllabus):
            key = f"{syllabus}/{subject}"

            if key in folders_seen:
                continue
            folders_seen.add(key)
            folder_tasks.append((folder, subject, syllabus))

    async def process_one(folder: Path, subject: str, syllabus: str) -> FolderResult:
        def log(msg: str) -> None:
            if logger:
                logger(msg)
            else:
                print(msg)

        log(f"\nProcessing {syllabus}/{subject}...")
        return await process_folder(folder, subject, syllabus, client, rule_manager, logger, max_concurrency=5)

    folder_results = await asyncio.gather(*[process_one(f, s, syl) for f, s, syl in folder_tasks])

    return list(folder_results)


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


def main():
    parser = argparse.ArgumentParser(description="Batch PDF renaming with LLM-generated rules")
    parser.add_argument(
        "--mode",
        choices=["generate-rules", "rename"],
        default="rename",
        help="Mode: generate-rules or rename",
    )
    parser.add_argument(
        "--base",
        help="Base folder containing syllabus/subject/past-papers structure",
    )
    parser.add_argument(
        "--rules-file", help="Custom rules file path",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
