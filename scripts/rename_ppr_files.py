from pathlib import Path
import fitz
import re
import shutil

def parse_ppr_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    text = doc[0].get_text()
    doc.close()

    info = {}

    # Extract code/component like 7037/1
    code_match = re.search(r'(\d{4})/(\d)', text)
    if code_match:
        info['code'] = code_match.group(1)
        info['component'] = code_match.group(2)

    # Extract subject from line before "Paper"
    subj_match = re.search(r'\n([A-Z][A-Za-z\s]+)\nPaper', text)
    if subj_match:
        info['subject'] = subj_match.group(1).strip().title()

    # Try to extract date from multiple patterns
    # Pattern: "Wednesday 17 May 2023" or just "17 May 2023"
    date_match = re.search(r'(?:Wednesday|Monday|Tuesday|Thursday|Friday)\s+(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})', text)
    if date_match:
        month = date_match.group(2)
        year = date_match.group(3)
        month_map = {'January':'01','February':'02','March':'03','April':'04','May':'05','June':'06',
                     'July':'07','August':'08','September':'09','October':'10','November':'11','December':'12'}
        info['year'] = year
        info['session'] = 'jun' if month in ['May', 'June', 'July'] else 'nov' if month in ['October', 'November', 'December'] else 'mar'

    # Alternative: Try to find "Jun23" or similar in text
    if 'year' not in info:
        session_match = re.search(r'\b(Jun|Nov|Mar)\s*(\d{2})\b', text, re.IGNORECASE)
        if session_match:
            session_map = {'jun': 'jun', 'nov': 'nov', 'mar': 'mar'}
            info['session'] = session_map.get(session_match.group(1).lower(), 'jun')
            info['year'] = '20' + session_match.group(2)

    # Alternative: Look for "G/KL/Jun23/E4" style AQA codes
    if 'year' not in info:
        aqa_match = re.search(r'(Jun|Nov|Mar)/(\d{2})', text)
        if aqa_match:
            session_map = {'Jun': 'jun', 'Nov': 'nov', 'Mar': 'mar'}
            info['session'] = session_map.get(aqa_match.group(1), 'jun')
            info['year'] = '20' + aqa_match.group(2)

    return info

def get_file_type(filename):
    upper = filename.upper()
    if '_INSERT_' in upper:
        return 'in'
    elif '_QUESTION_PAPER_' in upper:
        return 'qp'
    elif '_MARK_SCHEME_' in upper:
        return 'ms'
    return None

def rename_ppr_files(base_path):
    ppr_files = list(base_path.rglob('ppr_*.PDF')) + list(base_path.rglob('ppr_*.pdf'))
    print(f'Found {len(ppr_files)} ppr files')

    renamed = 0
    errors = 0
    skipped = 0

    for pdf_path in ppr_files:
        try:
            info = parse_ppr_pdf(pdf_path)

            missing = [k for k in ['code', 'component', 'year', 'session'] if k not in info]
            if missing:
                print(f'SKIP (missing {missing}): {pdf_path.name}')
                skipped += 1
                continue

            file_type = get_file_type(pdf_path.name)
            if not file_type:
                print(f'SKIP (unknown type): {pdf_path.name}')
                skipped += 1
                continue

            # Get board from parent folder
            parent_folder = pdf_path.parent.name
            board_match = re.search(r'(AQA|CIE|Edexcel|OCR)', parent_folder, re.IGNORECASE)
            board = board_match.group(1).lower() if board_match else 'aqa'

            # Get subject from folder if available
            subj_match = re.search(r'\(([^)]+)\)', parent_folder)
            if subj_match:
                folder_subject = subj_match.group(1).strip()
                if folder_subject.lower() not in ['geography', 'biology', 'chemistry', 'physics', 'mathematics', 'computer science', 'economics', 'business']:
                    info['subject'] = folder_subject.title()

            if 'subject' not in info:
                info['subject'] = 'Unknown'

            new_name = f"{info['year']}-{info['session']}-alevel-{info['subject'].lower().replace(' ', '-')}-{board}-{info['code']}-{info['component']}-n-{file_type}.pdf"
            new_path = pdf_path.parent / new_name

            if new_path.exists() and new_path != pdf_path:
                new_path = new_path.with_name(f"{new_name[:-4]}_2.pdf")

            if new_path != pdf_path:
                shutil.move(str(pdf_path), str(new_path))
                renamed += 1
            else:
                skipped += 1

        except Exception as e:
            print(f'ERROR: {pdf_path.name}: {e}')
            errors += 1

    print(f'\nResult: Renamed={renamed}, Skipped={skipped}, Errors={errors}')
    return renamed, skipped, errors

if __name__ == '__main__':
    base_path = Path(r'C:\Users\gmhome\SynologyDrive\Ragmaterials\exam\a-level\Geography')
    rename_ppr_files(base_path)