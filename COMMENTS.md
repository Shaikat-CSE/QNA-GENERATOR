# ContentGeneratorV2 - Review Comments & Notes

> Add your review comments, feedback, and notes here. This file is for tracking observations, issues, and improvement ideas.

---

## 2026-04-29

### Current Status
- **Key Points Display:** Fixed - now stay visible throughout video (no longer disappear after 2s)
- **Image Provider:** Switched from aisonnet to gemini_image (vectorengine) for proper 16:9 aspect ratio
- **API Retry Logic:** Implemented 3 retries with exponential backoff (4s, 8s, 12s delays)
- **Gemini API Issue:** Endpoint `https://hb.dockerspeeds.asia/v1/chat/completions` returning 400 Bad Request errors

### Pending Tests
- [ ] Test key points persistence in rendered video
- [ ] Verify vectorengine returns proper 1920x1080 images
- [ ] Resolve Gemini API connectivity (new key configured but still failing)

---

## Exam Paper Collection Strategy

### Target Year Range: 2015-Present
- **Priority:** Focus collection and analysis on papers from **2015 onwards**
- **Rationale:** Recent papers (last 10 years) are most relevant for current curriculum
- **Pre-2015 Papers:** Not required for initial collection and analysis
- **Current Coverage:** 4,857 papers from 2015-2024 (92% of total collection)

### Data Quality Issues
- **Invalid Years (2026+):** Any papers dated 2026 or later are **incorrect** - these are filename parsing errors
- **Action Required:** Clean up availability report to remove/fix entries with years ≥ 2026
- **Valid Range:** 2015-2025 only

### Action Items
- [ ] Filter availability report to show only 2015+ papers
- [ ] Prioritize filling gaps in 2015-2024 range
- [ ] Deprioritize pre-2015 papers in collection efforts

---

## Exam Paper Pairing Status

### Current Collection (from availability_report.csv)
- **Total Papers:** 5,278 exam papers tracked
- ✅ **Complete Pairs (QP + MS):** 3,292 papers (62.4%)
- ⚠️ **Missing Mark Scheme (MS):** 1,135 papers (21.5%) - have QP but no MS
- ⚠️ **Missing Question Paper (QP):** 851 papers (16.1%) - have MS but no QP

### Impact
- **QNA-Generacan tor can only process:** 3,292 complete pairs (62.4%)
- **Cannot process:** 1,986 papers (37.6%) - missing either QP or MS

### Priority Action Items
- [ ] **Find missing mark schemes (MS)** - 1,135 papers need MS to complete pairing
- [ ] **Find missing question papers (QP)** - 851 papers need QP to complete pairing
- [ ] Focus on 2015-2024 range first (4,857 papers)
- [ ] Generate filtered report showing incomplete pairs in target year range
- [ ] Source missing files from exam board websites or archives

### Notes
- Most common issue: Missing mark schemes (21.5% of collection)
- Complete pairs are ready for QNA markdown conversion
- Incomplete pairs block the QNA-Generator workflow

---

## Subject Code Structure

### Total Folders Requiring Subject Codes
- **IGCSE:** 42 folders (e.g., `igcse/Biology/Cie Biology (0610)/past-papers`)
  - **With PDFs:** 32 folders
  - **Empty (no PDFs):** 10 folders
- **A-Level:** 59 folders (e.g., `a-level/Accounting/AQA Accounting (7127)/past-papers`)
  - **With PDFs:** 43 folders
  - **Empty (no PDFs):** 16 folders
- **IB:** 47 folders (e.g., `ib/Biology/sl`, `ib/Biology/hl`)
  - **With PDFs:** 46 folders
  - **Empty (no PDFs):** 1 folder
- **Total:** **148 unique subject code folders**
  - **With PDFs:** 121 folders (82%)
  - **Empty:** 27 folders (18%)

### Current Subject Rules Coverage
- **IGCSE codes:** 46 (out of ~54-62 needed)
- **A-Level codes:** 21 (out of ~59 needed)
- **IB codes:** 0 (out of ~47 needed)
- **Total in subject_rules.json:** 68 codes
- **Total needed:** ~148 codes

### Code Pattern
- **IGCSE:** 0xxx (CIE), 4xxx (Edexcel)
- **A-Level:** 7xxx (AQA), 9xxx (Edexcel/CIE)
- **IB:** Subject + Level (SL/HL) combination

### Action Items
- [ ] Generate rules for remaining 38 IGCSE folders
- [ ] Generate rules for remaining 38 A-Level folders
- [ ] Generate rules for all 47 IB folders (SL/HL combinations)
- [ ] Update subject_rules.json with all 148 codes
- [ ] **Verify QNA-Generator scans all 148 folders** - ensure no folders are skipped during rule generation
- [ ] Run rule generator in batch mode to process all missing folders
- [ ] Validate that each folder has corresponding entry in subject_rules.json

### Verification Checklist
- [ ] Confirm all IGCSE board folders are detected (CIE, Edexcel, AQA)
- [ ] Confirm all A-Level board folders are detected (AQA, Edexcel, CIE, OCR)
- [ ] Confirm all IB sl/hl folders are detected for each subject
- [ ] Cross-reference folder count (148) with subject_rules.json entries
- [ ] Test renamer on sample PDFs from each folder to ensure rules work

---

## Expected vs Actual Paper Count (2015-2025)

### Calculation Method
**Expected papers per subject code:**
- Years: 2015-2025 = 11 years
- Sessions per year: 2-3 (Summer/Winter for most, May/Nov for IB)
- Papers per session: 1-4 (varies by subject)
- Variants: 1-3 (timezone variants for international exams)
- **Estimated range:** 22-132 papers per code (11 years × 2 sessions × 1-4 papers × 1-3 variants)

### Top Subject Codes (2015-2025 Complete Pairs)
| Code | Subject | Board | Level | Complete Pairs | Expected* | Coverage |
|------|---------|-------|-------|----------------|-----------|----------|
| 9708 | Economics | CIE | A-Level | 267 | ~88-132 | ✅ Excellent |
| 9701 | Chemistry | CIE | A-Level | 225 | ~88-132 | ✅ Excellent |
| 9700 | Biology | CIE | A-Level | 182 | ~88-132 | ✅ Excellent |
| 9709 | Mathematics | CIE | A-Level | 175 | ~88-132 | ✅ Excellent |
| 9696 | Geography | CIE | A-Level | 172 | ~88-132 | ✅ Excellent |
| 9706 | Accounting | CIE | A-Level | 148 | ~88-132 | ✅ Excellent |
| 0470 | History | CIE | IGCSE | 146 | ~66-99 | ✅ Excellent |
| 9702 | Physics | CIE | A-Level | 138 | ~88-132 | ✅ Good |
| 9609 | Business | CIE | A-Level | 116 | ~88-132 | ✅ Good |
| 9hi0 | History | Edexcel | A-Level | 115 | ~66-99 | ✅ Excellent |

*Expected = 11 years × 2 sessions × 2-3 papers × 2 variants (typical for CIE/Edexcel)

### Notes
- **Over-expected counts** (>132) indicate multiple variants, retake sessions, or specimen papers
- **Under-expected counts** (<22) indicate missing papers or incomplete collection
- Most major codes show **excellent coverage** (100-267 papers)
- Need to verify expected counts against official exam board schedules

### Action Items
- [ ] Research official exam schedules from CIE/Edexcel/AQA websites (2015-2025)
- [ ] Calculate exact expected paper count per code (years × sessions × papers × variants)
- [ ] Compare actual vs expected to identify gaps
- [ ] Prioritize filling gaps in high-priority subjects (Sciences, Maths, English, Business)
- [ ] Document expected counts in a reference table for each of the 121 active folders

---

## Exam Folder Restructuring

### Proposed Structure
```
exam/
  code/                    # All builder code and apps
    QNA-Generator/         # Move from exam/QNA-Generator
    demotest_exam_builder/ # Move from exam/demotest_exam_builder
    *.py                   # Move all Python scripts here
  summary/                 # Latest reports and analysis
    availability_report.csv
    exam_papers_analysis.csv
    exam_papers_analysis.xlsx
    *.csv, *.xlsx          # All current reports
  a-level/                 # Keep - PDF storage only
  ib/                      # Keep - PDF storage only
  igcse/                   # Keep - PDF storage only
```

### Rationale
- **Separation of concerns:** Code/apps separate from PDF data
- **Cleaner organization:** All builder tools in one `code/` folder
- **Easier maintenance:** Clear distinction between source code and exam papers

### Action Items
- [ ] Create `exam/code/` folder
- [ ] Create `exam/summary/` folder for latest reports
- [ ] Move `QNA-Generator/` to `exam/code/QNA-Generator/`
- [ ] Move `demotest_exam_builder/` to `exam/code/demotest_exam_builder/`
- [ ] Move Python scripts (*.py) to `exam/code/`
- [ ] Move CSV/XLSX reports to `exam/summary/`
- [ ] Keep `a-level/`, `ib/`, `igcse/` folders at root for PDF storage

---

## Your Comments Below

<!-- Add your review comments here -->

