"""Rename unknown files by inferring session from availability matrix and PDF content."""

import os
import re
import json
import csv
import shutil
from pathlib import Path
import PyPDF2


def load_availability_matrix(csv_path):
    """Load the availability matrix to see what papers exist."""
    matrix = {}
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row['Year'], row['Subject'], row['Syllabus'], row['Paper'])
            matrix[key] = row
    return matrix


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


def detect_session_from_content(pdf_data):
    """Detect session from PDF content."""
    if not pdf_data:
        return None

    combined = f"{pdf_data['title']} {pdf_data['subject']} {pdf_data['text']}".lower()

    # Check for specimen
    if 'specimen' in combined or 'sample' in combined:
        return 's'

    # Check for months
    if 'june' in combined or 'may' in combined:
        return 's'
    if 'november' in combined or 'october' in combined:
        return 'w'
    if 'march' in combined or 'february' in combined:
        return 'm'

    return None


def parse_unknown_filename(filename):
    """Parse components from unknown filename."""
    # Pattern 1: 0610-er-2023-unknown-1-1.pdf
    match = re.match(r'(\d{4})-([a-z]+)-(\d{4})-unknown-(\d)-(\d)\.pdf', filename, re.IGNORECASE)
    if match:
        return {
            'code': match.group(1),
            'type': match.group(2),
            'year': match.group(3),
            'paper': match.group(4),
            'variant': match.group(5),
            'session': None
        }

    # Pattern 2: 0460-qp-unknown-1-1.pdf (no year)
    match = re.match(r'(\d{4})-([a-z]+)-unknown-(\d)-(\d+)\.pdf', filename, re.IGNORECASE)
    if match:
        return {
            'code': match.group(1),
            'type': match.group(2),
            'year': None,
            'paper': match.group(3),
            'variant': match.group(4),
            'session': None
        }

    # Pattern 3: 0455_qp_Unknown_unknown_p1.pdf
    match = re.match(r'(\d{4})_([a-z]+)_Unknown_unknown_p(\d)\.pdf', filename, re.IGNORECASE)
    if match:
        return {
            'code': match.group(1),
            'type': match.group(2),
            'year': None,
            'paper': match.group(3),
            'variant': '1',
            'session': None
        }

    # Pattern 3b: 0610_er_2023_unknown_p1.pdf
    match = re.match(r'(\d{4})_([a-z]+)_(\d{4})_unknown_p(\d)\.pdf', filename, re.IGNORECASE)
    if match:
        return {
            'code': match.group(1),
            'type': match.group(2),
            'year': match.group(3),
            'paper': match.group(4),
            'variant': '1',
            'session': None
        }

    # Pattern 4: 4et1-qp-2024-unknown-1-1.pdf (Edexcel)
    match = re.match(r'([a-z0-9]+)-([a-z]+)-(\d{4})-unknown-(\d)-(\d)\.pdf', filename, re.IGNORECASE)
    if match:
        return {
            'code': match.group(1),
            'type': match.group(2),
            'year': match.group(3),
            'paper': match.group(4),
            'variant': match.group(5),
            'session': None
        }

    return None


def infer_session_from_matrix(components, matrix, subject_name):
    """Infer session by checking what exists in the matrix."""
    if not components['year']:
        return None

    year = components['year']
    code = components['code']
    paper = components['paper']
    variant = components['variant']

    # Try different sessions
    for session_code, session_name in [('s', 'jun'), ('w', 'nov'), ('m', 'mar')]:
        # Build paper identifier
        paper_id = f"{year}-{session_code}-igcse-{subject_name.lower()}-cambridge-{code}-{paper}-{variant}"

        # Check if this combination exists in matrix
        for key in matrix.keys():
            if paper_id in key[3].lower():
                return session_code

    return None


def build_new_filename(components, session_code, subject_slug, board='cie'):
    """Build standardized filename."""
    year = components['year'] or '2023'  # Default to 2023 if no year

    # Map session codes
    session_map = {'s': 's', 'w': 'w', 'm': 'm', 'jun': 's', 'nov': 'w', 'mar': 'm'}
    session = session_map.get(session_code, session_code)

    code = components['code']
    paper = components['paper']
    variant = components['variant']
    doc_type = components['type']

    # Format: YYYY-session-igcse-subject-board-code-paper-variant-type.pdf
    return f"{year}-{session}-igcse-{subject_slug}-{board}-{code}-{paper}-{variant}-{doc_type}.pdf"


def get_subject_from_path(filepath):
    """Extract subject name from file path."""
    path_parts = Path(filepath).parts

    # Look for subject folder (usually contains the code in parentheses)
    for part in path_parts:
        if '(' in part and ')' in part:
            # Extract subject name before parentheses
            subject = part.split('(')[0].strip()
            return subject

    return None


def rename_unknown_files(base_dir, matrix_csv, dry_run=True):
    """Rename all unknown files."""
    matrix = load_availability_matrix(matrix_csv)
    results = []

    # Find all unknown files
    unknown_files = []
    for root, dirs, files in os.walk(base_dir):
        for filename in files:
            if ('unknown' in filename.lower() or 'Unknown' in filename.lower()) and filename.endswith('.pdf'):
                filepath = os.path.join(root, filename)
                unknown_files.append(filepath)

    print(f"Found {len(unknown_files)} files with 'unknown' in filename\n")

    for filepath in unknown_files:
        filename = os.path.basename(filepath)
        print(f"Processing: {filename}")

        # Parse filename
        components = parse_unknown_filename(filename)
        if not components:
            print(f"  [X] Could not parse filename format")
            results.append({
                'original': filepath,
                'status': 'failed',
                'reason': 'Could not parse filename'
            })
            continue

        print(f"  Code: {components['code']}, Year: {components['year']}, Paper: {components['paper']}-{components['variant']}")

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

        # Try to detect session from PDF content
        pdf_data = extract_pdf_metadata(filepath)
        session_from_pdf = detect_session_from_content(pdf_data)

        # Try to infer session from matrix
        subject_slug = subject.lower().replace(' ', '-')
        session_from_matrix = infer_session_from_matrix(components, matrix, subject)

        # Use detected session or default to 's' (summer)
        session = session_from_pdf or session_from_matrix or 's'

        print(f"  Session from PDF: {session_from_pdf}")
        print(f"  Session from matrix: {session_from_matrix}")
        print(f"  Using session: {session}")

        # Build new filename
        board = 'edexcel' if components['code'].startswith('4') else 'cie'
        new_filename = build_new_filename(components, session, subject_slug, board)
        new_filepath = os.path.join(os.path.dirname(filepath), new_filename)

        print(f"  [OK] New filename: {new_filename}")

        # Rename file
        if not dry_run:
            if os.path.exists(new_filepath):
                print(f"  [SKIP]  File already exists, skipping")
                results.append({
                    'original': filepath,
                    'new': new_filepath,
                    'status': 'skipped',
                    'reason': 'File already exists'
                })
            else:
                shutil.move(filepath, new_filepath)
                print(f"  [DONE] Renamed successfully")
                results.append({
                    'original': filepath,
                    'new': new_filepath,
                    'status': 'success'
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
    base_dir = r"C:\Users\gmhome\SynologyDrive\Ragmaterials\exam\igcse"
    matrix_csv = r"C:\Users\gmhome\SynologyDrive\Ragmaterials\exam\igcse\availability_report.csv"

    print("=" * 80)
    print("IGCSE Unknown Files Renamer")
    print("=" * 80)
    print()

    # Run with actual renaming
    print("Running ACTUAL RENAME...\n")
    results = rename_unknown_files(base_dir, matrix_csv, dry_run=False)

    # Save results
    output_file = "unknown_files_renamed_report.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 80)
    print("Summary:")
    print(f"  Total files: {len(results)}")
    print(f"  Successfully renamed: {sum(1 for r in results if r['status'] == 'success')}")
    print(f"  Skipped (already exists): {sum(1 for r in results if r['status'] == 'skipped')}")
    print(f"  Failed: {sum(1 for r in results if r['status'] == 'failed')}")
    print(f"\nResults saved to: {output_file}")


if __name__ == "__main__":
    main()
