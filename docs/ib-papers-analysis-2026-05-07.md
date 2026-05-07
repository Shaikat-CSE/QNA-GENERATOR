# IB Papers Analysis Report

Date: 2026-05-07

## Summary

The IB folder has a different situation compared to IGCSE:

### Files with "unknown" in filename: **4**
All 4 are legitimate literature study resources (LitCharts) with "unknown" in the title:
- `LitCharts-a-march-in-the-ranks-hard-prest-and-the-road-unknown.pdf`
- `LitCharts-an-unknown-girl.pdf`
- `LitCharts-i-travelled-among-unknown-men.pdf`
- `LitCharts-the-unknown-citizen.pdf`

**Action:** None needed - these are correctly named resources.

### Files in needs_review: **0**
No files in needs_review folders.

### Files with unknown years: **186**

These fall into two categories:

#### 1. Practice Papers (100 files)
- Format: `{subject}-set-{a/b}-practice-paper-{number}-{hl/sl}-{qp/ms}.pdf`
- Example: `biology-set-a-practice-paper-1a-hl-qp.pdf`
- **Status:** These are practice papers, not actual exam papers. They don't have years by design.
- **Action:** Should be moved to a separate `practice-papers` folder or renamed with "practice" prefix.

#### 2. SME/Specimen Papers (86 files)
- Format: `{subject}-sme-{hl/sl}-{subject}-paper-{number}-v{variant}-{qp/ms}.pdf`
- Example: `business-management-sme-hl-business-management-paper-1-v1-qp.pdf`
- **Status:** These are specimen/sample papers. "SME" likely means "Sample/Specimen Material for Examination"
- **Action:** Should be renamed to include "specimen" or "spec" session code.

## Availability Matrix Status

- **Matrix rows:** 355
- **Total PDFs:** 2,070
- **Matrix completeness:** Unknown (no audit report available)

## Comparison with IGCSE

| Metric | IGCSE | IB |
|--------|-------|-----|
| Files with "unknown" in name | 62 (exam papers) | 4 (literature resources) |
| Files needing rename | 62 | 186 (practice/specimen) |
| Files in needs_review | 2 (moved) | 0 |
| Issue type | Ambiguous year/session | Practice papers without year |

## Recommendations

### High Priority
1. **Separate practice papers** - Move 100 practice papers to dedicated folder
2. **Rename specimen papers** - Add year/session to 86 SME papers

### Medium Priority
3. **Create audit report** - Run availability audit similar to IGCSE
4. **Verify matrix completeness** - Check if all papers are properly tracked

### Low Priority
5. **Standardize naming** - Ensure all papers follow consistent format

## Proposed Actions

### 1. Move Practice Papers
```bash
# Move practice papers to separate folder
for subject in Biology Chemistry Physics Economics; do
  mkdir -p "ib/$subject/hl/practice-papers"
  mkdir -p "ib/$subject/sl/practice-papers"
  mv "ib/$subject/hl/past-papers/*practice*" "ib/$subject/hl/practice-papers/"
  mv "ib/$subject/sl/past-papers/*practice*" "ib/$subject/sl/practice-papers/"
done
```

### 2. Rename Specimen Papers
SME papers should be renamed to include year and session:
- Current: `business-management-sme-hl-business-management-paper-1-v1-qp.pdf`
- Proposed: `2024-spec-ib-business-management-hl-paper1-v1-qp.pdf`

This requires:
1. Analyzing PDF content to determine year
2. Applying standard IB naming convention
3. Updating availability matrix

## Next Steps

1. **Confirm approach** - Should practice papers be separated or renamed?
2. **Determine specimen years** - Analyze SME papers to extract year information
3. **Create rename script** - Similar to IGCSE script but for IB format
4. **Run availability audit** - Generate comprehensive audit report

## Notes

- IB papers use different naming convention than IGCSE
- Practice papers are legitimate resources, not misnamed files
- SME papers need year information extracted from PDF content
- No immediate "unknown" crisis like IGCSE had
