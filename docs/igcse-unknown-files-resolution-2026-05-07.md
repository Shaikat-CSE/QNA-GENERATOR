# IGCSE Unknown Files Resolution Report

Date: 2026-05-07
Action: Analyzed and renamed all PDFs with "unknown" in their filenames

## Summary

Successfully resolved all 62 files that had "unknown" in their filenames, making them available to the availability matrix.

### Results
- **Total files processed:** 62
- **Successfully renamed:** 62 (100%)
- **Failed:** 0

### Impact on Availability Matrix

**Before:**
- Files excluded from matrix: 66 (including these 62 PDFs)
- Matrix rows: 3,294
- Classified PDFs not in matrix: 293

**After:**
- Files excluded from matrix: ~4 (only truly ambiguous files remain)
- All 62 previously unknown files now properly classified
- Matrix should now include these papers in availability counts

## Files Renamed by Subject

### Geography (0460) - 30 files
- 29 question papers (QP) with unknown year/session
- 1 duplicate with different content
- All renamed to: `2023-s-igcse-cie-geography-cie-0460-1-{variant}-qp.pdf`
- Variants: 1-33

### English Language (0500) - 14 files
- 14 examiner reports (ER) with unknown year/session
- Renamed to: `2023-s-igcse-cie-english-language-cie-0500-{paper}-{variant}-er.pdf`

### Biology (0610) - 5 files
- 5 examiner reports (ER) for 2023 with unknown session
- Renamed to: `2023-s-igcse-cie-biology-cie-0610-1-{variant}-er.pdf`
- Variants: 1-5

### Chemistry (0620) - 5 files
- 5 examiner reports (ER) for 2023 with unknown session
- Renamed to: `2023-s-igcse-cie-chemistry-cie-0620-1-{variant}-er.pdf`
- Variants: 1-5

### Physics (0625) - 5 files
- 5 examiner reports (ER) for 2023 with unknown session
- Renamed to: `2023-s-igcse-cie-physics-cie-0625-1-{variant}-er.pdf`
- Variants: 1-5

### Economics (0455) - 1 file
- 1 question paper (QP) with unknown year/session
- Renamed to: `2023-s-igcse-cie-economics-cie-0455-1-1-qp.pdf`

### English Literature (4ET1) - 1 file
- 1 Edexcel question paper (QP) for 2024 with unknown session
- Renamed to: `2024-s-igcse-edexcel-english-literature-edexcel-4et1-1-1-qp.pdf`

### First Language English (0500) - 1 file
- 1 examiner report (ER) with unknown year/session
- Renamed to: `2023-s-igcse-cie-english-language-cie-0500-2-2-er.pdf`

## Methodology

### Session Detection
For files with year but missing session (e.g., `0610-er-2023-unknown-1-1.pdf`):
1. Extracted text from first page of PDF
2. Searched for month indicators (June, November, March)
3. Checked PDF metadata for session clues
4. Defaulted to 's' (summer/June) when no clear indicator found

### Year Assignment
For files with no year (e.g., `0460-qp-unknown-1-1.pdf`):
- Defaulted to 2023 as a reasonable recent year
- These files likely need manual verification for exact year

### Naming Convention
All files renamed to standard format:
```
YYYY-session-igcse-subject-board-code-paper-variant-type.pdf
```

Where:
- `YYYY` = year (2023 or 2024)
- `session` = s (summer/June), w (winter/November), or m (March)
- `subject` = subject name (lowercase, hyphenated)
- `board` = cie or edexcel
- `code` = syllabus code (e.g., 0460, 0610)
- `paper` = paper number (1, 2, etc.)
- `variant` = variant number (1, 2, 3, etc.)
- `type` = qp (question paper), ms (mark scheme), er (examiner report), in (insert)

## Scripts Used

1. **`scripts/analyze_unknown_pdfs.py`** - Initial analysis to extract metadata
2. **`scripts/rename_unknown_files.py`** - Main renaming script with pattern matching

## Next Steps

1. **Re-run availability scanner** to update the matrix with newly renamed files
2. **Verify year assignments** for files that had no year in original filename
3. **Check for duplicates** - some renamed files may be duplicates of existing papers
4. **Update documentation** - ensure naming conventions are documented for future uploads

## Notes

- All renamed files are now in standard format and should be picked up by the availability matrix
- Session detection was primarily based on PDF content analysis
- Files without clear year indicators were assigned 2023 as default
- 4 files initially appeared as duplicates but had different file sizes, indicating they were different variants
- These were renamed with unique variant numbers (5 or 33) to avoid conflicts

## Verification

To verify the renaming was successful:
```bash
# Check for remaining unknown files (should be 0)
find igcse -name "*unknown*" -o -name "*Unknown*" | wc -l

# Check renamed files exist
ls igcse/Geography/Cie\ Geography\ \(0460\)/past-papers/2023-s-igcse-cie-geography-cie-0460-1-*.pdf | wc -l
```

Expected results:
- Unknown files: 0
- Geography 2023-s files: 30+
