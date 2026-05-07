"""Analyze PDFs with 'unknown' in filename and extract year/session from content."""

import os
import re
import json
import PyPDF2
from pathlib import Path


def extract_text_from_pdf(pdf_path, max_pages=3):
    """Extract text from first few pages of PDF."""
    try:
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = ""
            for i in range(min(max_pages, len(reader.pages))):
                text += reader.pages[i].extract_text()
            return text
    except Exception as e:
        print(f"Error reading {pdf_path}: {e}")
        return ""


def detect_year_from_text(text):
    """Detect year from PDF text content."""
    # Look for common patterns
    patterns = [
        r'(?:May|June|November|October|March|February)\s+(\d{4})',  # Month YYYY
        r'(\d{4})\s+(?:May|June|November|October|March|February)',  # YYYY Month
        r'(?:©|Copyright)\s+(?:UCLES|Cambridge|Edexcel|Pearson)\s+(\d{4})',  # Copyright YYYY
        r'(?:©|Copyright)\s+(\d{4})',  # Copyright YYYY
        r'\b(20\d{2})\b',  # Any 20XX year
        r'\b(19\d{2})\b',  # Any 19XX year
    ]

    years = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            year = int(match)
            if 1990 <= year <= 2030:  # Reasonable range for exam papers
                years.append(year)

    # Return most common year
    if years:
        return max(set(years), key=years.count)
    return None


def detect_session_from_text(text):
    """Detect session (jun/nov/mar/specimen) from PDF text."""
    text_lower = text.lower()

    # Check for specimen first
    if 'specimen' in text_lower or 'sample' in text_lower:
        return 'spec'

    # Check for specific months
    if 'june' in text_lower or 'may' in text_lower:
        return 'jun'
    if 'november' in text_lower or 'october' in text_lower:
        return 'nov'
    if 'march' in text_lower or 'february' in text_lower:
        return 'mar'
    if 'january' in text_lower:
        return 'jan'

    # Check for session codes
    if re.search(r'\bs\d{2}\b', text_lower):  # s23, s22, etc.
        return 'jun'
    if re.search(r'\bw\d{2}\b', text_lower):  # w23, w22, etc.
        return 'nov'
    if re.search(r'\bm\d{2}\b', text_lower):  # m23, m22, etc.
        return 'mar'

    return None


def parse_filename_components(filename):
    """Extract known components from filename."""
    components = {
        'code': None,
        'paper': None,
        'variant': None,
        'type': None,
        'board': None,
    }

    # Extract syllabus code (e.g., 0460, 0500, 0610)
    code_match = re.search(r'\b(0\d{3}|4[A-Z]{2}\d)\b', filename, re.IGNORECASE)
    if code_match:
        components['code'] = code_match.group(1)

    # Extract paper number
    paper_match = re.search(r'[-_](\d)[-_]', filename)
    if paper_match:
        components['paper'] = paper_match.group(1)

    # Extract variant
    variant_match = re.search(r'[-_]\d[-_](\d)', filename)
    if variant_match:
        components['variant'] = variant_match.group(1)

    # Extract type (qp, ms, er, in)
    if '-qp' in filename.lower() or '_qp_' in filename.lower():
        components['type'] = 'qp'
    elif '-ms' in filename.lower() or '_ms_' in filename.lower():
        components['type'] = 'ms'
    elif '-er' in filename.lower() or '_er_' in filename.lower():
        components['type'] = 'er'
    elif '-in' in filename.lower() or '_in_' in filename.lower():
        components['type'] = 'in'

    # Extract board
    if 'cie' in filename.lower() or 'cambridge' in filename.lower():
        components['board'] = 'cie'
    elif 'edexcel' in filename.lower():
        components['board'] = 'edexcel'

    return components


def build_new_filename(original_filename, year, session, components):
    """Build new filename with detected year and session."""
    # Get file extension
    ext = os.path.splitext(original_filename)[1]

    # Determine subject from code
    code = components['code']
    if not code:
        return None

    # Map codes to subjects (simplified)
    code_to_subject = {
        '0460': 'geography',
        '0500': 'english-language',
        '0455': 'economics',
        '0610': 'biology',
        '0620': 'chemistry',
        '0625': 'physics',
        '4ET1': 'english-literature',
    }

    subject = code_to_subject.get(code, 'unknown')
    board = components['board'] or 'cie'
    paper = components['paper'] or '1'
    variant = components['variant'] or '1'
    doc_type = components['type'] or 'qp'

    # Build filename: YYYY-session-igcse-subject-board-code-paper-variant-type.pdf
    new_filename = f"{year}-{session}-igcse-{subject}-{board}-{code}-{paper}-{variant}-{doc_type}{ext}"

    return new_filename


def analyze_unknown_files(base_dir):
    """Analyze all files with 'unknown' in their names."""
    results = []

    # Find all unknown files
    for root, dirs, files in os.walk(base_dir):
        for filename in files:
            if ('unknown' in filename.lower() or 'Unknown' in filename.lower()) and filename.endswith('.pdf'):
                filepath = os.path.join(root, filename)

                print(f"\nAnalyzing: {filename}")

                # Extract text from PDF
                text = extract_text_from_pdf(filepath)

                # Detect year and session
                year = detect_year_from_text(text)
                session = detect_session_from_text(text)

                # Parse filename components
                components = parse_filename_components(filename)

                # Build new filename if we have year and session
                new_filename = None
                if year and session:
                    new_filename = build_new_filename(filename, year, session, components)

                result = {
                    'original_path': filepath,
                    'original_filename': filename,
                    'detected_year': year,
                    'detected_session': session,
                    'components': components,
                    'suggested_filename': new_filename,
                    'text_sample': text[:500] if text else None,
                }

                results.append(result)

                print(f"  Year: {year}")
                print(f"  Session: {session}")
                print(f"  Code: {components['code']}")
                print(f"  Suggested: {new_filename}")

    return results


def main():
    base_dir = r"C:\Users\gmhome\SynologyDrive\Ragmaterials\exam\igcse"

    print("Analyzing PDFs with 'unknown' in filename...")
    results = analyze_unknown_files(base_dir)

    # Save results
    output_file = "unknown_pdf_analysis.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n\nAnalysis complete. Results saved to {output_file}")
    print(f"Total files analyzed: {len(results)}")

    # Summary
    with_year = sum(1 for r in results if r['detected_year'])
    with_session = sum(1 for r in results if r['detected_session'])
    with_both = sum(1 for r in results if r['detected_year'] and r['detected_session'])

    print(f"\nSummary:")
    print(f"  Files with detected year: {with_year}/{len(results)}")
    print(f"  Files with detected session: {with_session}/{len(results)}")
    print(f"  Files ready to rename: {with_both}/{len(results)}")


if __name__ == "__main__":
    main()
