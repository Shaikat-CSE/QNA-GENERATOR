"""Rename remaining IB practice papers to standard format."""

import os
import re
import json
import shutil
from pathlib import Path


def find_practice_papers(base_dir):
    """Find all practice papers that need renaming."""
    practice_files = []

    for root, dirs, files in os.walk(base_dir):
        for filename in files:
            if not filename.endswith('.pdf'):
                continue

            # Skip already renamed files
            if filename.startswith('practice-ib-') or filename.startswith('20'):
                continue

            # Find practice papers with old naming
            if '-set-' in filename.lower() and 'practice' in filename.lower():
                filepath = os.path.join(root, filename)
                practice_files.append(filepath)

    return practice_files


def parse_practice_filename(filename, filepath):
    """Parse practice paper filename."""
    # Pattern: {subject}-set-{letter}-practice-paper-{number}{letter?}-{level}-{type}.pdf
    # Example: biology-set-b-practice-paper-1a-hl-qp.pdf

    match = re.match(r'([a-z-]+)-set-([a-z])-practice-paper-(\d+[a-z]?)-([hs]l)-(qp|ms)\.pdf',
                     filename, re.IGNORECASE)

    if match:
        subject = match.group(1)
        set_letter = match.group(2)
        paper = match.group(3)
        level = match.group(4).lower()
        doc_type = match.group(5).lower()

        return {
            'subject': subject,
            'set': set_letter,
            'paper': paper,
            'level': level,
            'type': doc_type
        }

    return None


def build_practice_filename(components):
    """Build standardized practice paper filename."""
    # Format: practice-ib-{subject}-{level}-set{letter}-paper{number}-{type}.pdf
    subject = components['subject']
    level = components['level']
    set_letter = components['set']
    paper = components['paper']
    doc_type = components['type']

    return f"practice-ib-{subject}-{level}-set{set_letter}-paper{paper}-{doc_type}.pdf"


def rename_practice_papers(base_dir, dry_run=True):
    """Rename all practice papers."""
    practice_files = find_practice_papers(base_dir)

    print(f"Found {len(practice_files)} practice papers to rename\n")

    results = []

    for filepath in practice_files:
        filename = os.path.basename(filepath)
        print(f"Processing: {filename}")

        # Parse filename
        components = parse_practice_filename(filename, filepath)

        if not components:
            print(f"  [X] Could not parse filename")
            results.append({
                'original': filepath,
                'status': 'failed',
                'reason': 'Could not parse filename'
            })
            continue

        print(f"  Subject: {components['subject']}")
        print(f"  Set: {components['set']}")
        print(f"  Paper: {components['paper']}")
        print(f"  Level: {components['level']}")

        # Build new filename
        new_filename = build_practice_filename(components)
        new_filepath = os.path.join(os.path.dirname(filepath), new_filename)

        print(f"  [OK] New: {new_filename}")

        # Rename
        if not dry_run:
            if os.path.exists(new_filepath):
                print(f"  [SKIP] Already exists")
                results.append({
                    'original': filepath,
                    'new': new_filepath,
                    'status': 'skipped'
                })
            else:
                try:
                    shutil.move(filepath, new_filepath)
                    print(f"  [DONE] Renamed")
                    results.append({
                        'original': filepath,
                        'new': new_filepath,
                        'status': 'success'
                    })
                except Exception as e:
                    print(f"  [ERROR] {e}")
                    results.append({
                        'original': filepath,
                        'new': new_filepath,
                        'status': 'error',
                        'reason': str(e)
                    })
        else:
            print(f"  [DRY RUN]")
            results.append({
                'original': filepath,
                'new': new_filepath,
                'status': 'dry_run'
            })

        print()

    return results


def main():
    base_dir = r"C:\Users\gmhome\SynologyDrive\Ragmaterials\exam\ib"

    print("=" * 80)
    print("IB Practice Papers Renamer")
    print("=" * 80)
    print()

    # Run actual rename
    print("Running ACTUAL RENAME...\n")
    results = rename_practice_papers(base_dir, dry_run=False)

    # Save results
    output_file = "ib_practice_papers_renamed.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 80)
    print("Summary:")
    print(f"  Total files: {len(results)}")
    print(f"  Successfully renamed: {sum(1 for r in results if r['status'] == 'success')}")
    print(f"  Skipped: {sum(1 for r in results if r['status'] == 'skipped')}")
    print(f"  Failed: {sum(1 for r in results if r['status'] == 'failed')}")
    print(f"  Errors: {sum(1 for r in results if r['status'] == 'error')}")
    print(f"\nResults saved to: {output_file}")


if __name__ == "__main__":
    main()
