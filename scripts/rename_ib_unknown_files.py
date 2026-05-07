"""Rename IB unknown year files by analyzing PDF content and applying standard naming."""

import os
import re
import json
import shutil
from pathlib import Path
import PyPDF2


def extract_pdf_metadata(pdf_path):
    """Extract metadata and first page text from PDF."""
    try:
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            metadata = reader.metadata or {}
            text = ""
            if len(reader.pages) > 0:
                text = reader.pages[0].extract_text()
            return {
                'title': metadata.get('/Title', ''),
                'subject': metadata.get('/Subject', ''),
                'creator': metadata.get('/Creator', ''),
                'producer': metadata.get('/Producer', ''),
                'text': text[:2000]
            }
    except Exception as e:
        print(f"  Error reading PDF: {e}")
        return None


def detect_year_from_content(pdf_data):
    """Detect year from PDF content."""
    if not pdf_data:
        return None

    combined = f"{pdf_data['title']} {pdf_data['subject']} {pdf_data['text']}".lower()

    # Look for year patterns
    patterns = [
        r'(?:©|copyright)\s+(?:ibo|international\s+baccalaureate)\s+(\d{4})',
        r'(?:may|november)\s+(\d{4})',
        r'(\d{4})\s+(?:may|november)',
        r'\b(20\d{2})\b',
    ]

    years = []
    for pattern in patterns:
        matches = re.findall(pattern, combined, re.IGNORECASE)
        for match in matches:
            year = int(match)
            if 2000 <= year <= 2030:
                years.append(year)

    if years:
        return max(set(years), key=years.count)
    return None


def detect_session_from_content(pdf_data):
    """Detect session from PDF content."""
    if not pdf_data:
        return None

    combined = f"{pdf_data['title']} {pdf_data['subject']} {pdf_data['text']}".lower()

    # Check for specimen/practice
    if 'specimen' in combined or 'sample' in combined or 'practice' in combined:
        return 'spec'

    # Check for months
    if 'may' in combined:
        return 'may'
    if 'november' in combined or 'nov' in combined:
        return 'nov'

    return None


def parse_ib_filename(filename):
    """Parse IB filename to extract components."""
    components = {
        'subject': None,
        'level': None,
        'paper': None,
        'variant': None,
        'type': None,
        'is_practice': False,
        'is_specimen': False,
    }

    filename_lower = filename.lower()

    # Check if practice paper
    if 'practice' in filename_lower:
        components['is_practice'] = True

    # Check if specimen/SME
    if 'sme' in filename_lower or 'specimen' in filename_lower:
        components['is_specimen'] = True

    # Extract level (hl/sl)
    if '-hl-' in filename_lower or filename_lower.endswith('-hl-qp.pdf') or filename_lower.endswith('-hl-ms.pdf'):
        components['level'] = 'hl'
    elif '-sl-' in filename_lower or filename_lower.endswith('-sl-qp.pdf') or filename_lower.endswith('-sl-ms.pdf'):
        components['level'] = 'sl'

    # Extract type (qp/ms)
    if filename_lower.endswith('-qp.pdf'):
        components['type'] = 'qp'
    elif filename_lower.endswith('-ms.pdf'):
        components['type'] = 'ms'

    # Extract paper number
    paper_match = re.search(r'paper[-_]?(\d+[a-z]?)', filename_lower)
    if paper_match:
        components['paper'] = paper_match.group(1)

    # Extract variant
    variant_match = re.search(r'[-_]v(\d+)', filename_lower)
    if variant_match:
        components['variant'] = variant_match.group(1)

    # Extract subject from path
    return components


def get_subject_from_path(filepath):
    """Extract subject from file path."""
    path_parts = Path(filepath).parts

    # Subject is usually 2 levels up from the file
    if len(path_parts) >= 3:
        subject = path_parts[-3]
        return subject.lower().replace(' ', '-')

    return None


def build_ib_filename(components, year, session, subject):
    """Build standardized IB filename."""
    level = components['level'] or 'sl'
    paper = components['paper'] or '1'
    variant = components['variant'] or '1'
    doc_type = components['type'] or 'qp'

    # Clean paper number (remove letters if present)
    paper_clean = re.sub(r'[a-z]', '', paper)

    # Format: YYYY-session-ib-subject-level-paper{N}-tz{variant}-type.pdf
    # For specimen: YYYY-spec-ib-subject-level-paper{N}-v{variant}-type.pdf
    if components['is_specimen'] or session == 'spec':
        return f"{year}-spec-ib-{subject}-{level}-paper{paper_clean}-v{variant}-{doc_type}.pdf"
    elif components['is_practice']:
        # Practice papers: practice-ib-subject-level-set{X}-paper{N}-{type}.pdf
        set_match = re.search(r'set[-_]([a-z])', subject)
        set_letter = set_match.group(1) if set_match else 'a'
        return f"practice-ib-{subject.split('-set-')[0]}-{level}-set{set_letter}-paper{paper}-{doc_type}.pdf"
    else:
        return f"{year}-{session}-ib-{subject}-{level}-paper{paper_clean}-tz{variant}-{doc_type}.pdf"


def rename_ib_unknown_files(base_dir, dry_run=True):
    """Rename all IB files with unknown years."""

    # Load the unknown year report
    report_path = os.path.join(base_dir, 'unknown_year_renaming_report.json')
    if not os.path.exists(report_path):
        print(f"Report not found: {report_path}")
        return []

    with open(report_path, 'r', encoding='utf-8') as f:
        unknown_files = json.load(f)

    results = []
    print(f"Found {len(unknown_files)} files with unknown years\n")

    for item in unknown_files:
        filepath = item['path']
        filename = os.path.basename(filepath)

        print(f"Processing: {filename}")

        # Parse filename
        components = parse_ib_filename(filename)

        # Get subject from path
        subject = get_subject_from_path(filepath)
        if not subject:
            print(f"  [X] Could not determine subject from path")
            results.append({
                'original': filepath,
                'status': 'failed',
                'reason': 'Could not determine subject'
            })
            continue

        print(f"  Subject: {subject}")
        print(f"  Level: {components['level']}")
        print(f"  Type: {components['type']}")
        print(f"  Practice: {components['is_practice']}")
        print(f"  Specimen: {components['is_specimen']}")

        # For practice papers, use a default naming
        if components['is_practice']:
            year = 2024
            session = 'practice'
        else:
            # Try to detect year from PDF content
            pdf_data = extract_pdf_metadata(filepath)
            year = detect_year_from_content(pdf_data)
            session = detect_session_from_content(pdf_data)

            # Default values if not detected
            if not year:
                year = 2024  # Default to recent year
            if not session:
                session = 'spec' if components['is_specimen'] else 'may'

        print(f"  Year: {year}")
        print(f"  Session: {session}")

        # Build new filename
        new_filename = build_ib_filename(components, year, session, subject)
        new_filepath = os.path.join(os.path.dirname(filepath), new_filename)

        print(f"  [OK] New filename: {new_filename}")

        # Rename file
        if not dry_run:
            if os.path.exists(new_filepath):
                print(f"  [SKIP] File already exists")
                results.append({
                    'original': filepath,
                    'new': new_filepath,
                    'status': 'skipped',
                    'reason': 'File already exists'
                })
            else:
                try:
                    shutil.move(filepath, new_filepath)
                    print(f"  [DONE] Renamed successfully")
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
            print(f"  [DRY RUN] Would rename to: {new_filename}")
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
    print("IB Unknown Year Files Renamer")
    print("=" * 80)
    print()

    # Run with actual renaming
    print("Running ACTUAL RENAME...\n")
    results = rename_ib_unknown_files(base_dir, dry_run=False)

    # Save results
    output_file = "ib_files_renamed_report.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 80)
    print("Summary:")
    print(f"  Total files: {len(results)}")
    print(f"  Successfully renamed: {sum(1 for r in results if r['status'] == 'success')}")
    print(f"  Skipped (already exists): {sum(1 for r in results if r['status'] == 'skipped')}")
    print(f"  Failed: {sum(1 for r in results if r['status'] == 'failed')}")
    print(f"  Errors: {sum(1 for r in results if r['status'] == 'error')}")
    print(f"\nResults saved to: {output_file}")


if __name__ == "__main__":
    main()
