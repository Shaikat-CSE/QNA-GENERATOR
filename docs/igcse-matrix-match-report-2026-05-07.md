# IGCSE Matrix Match Report

Date: 2026-05-07
Folder: `C:\Users\gmhome\SynologyDrive\Ragmaterials\exam\igcse`

## Executive Summary

The matrix is a strong match to the classified IGCSE corpus, but it is not a perfect match to the full folder.

The exact result:

- Matrix rows: `3294`
- Classified PDFs on disk: `6445`
- Review / excluded PDFs: `66`
- Unknown-year exclusions: `0`
- Row-key mismatches between classified disk data and matrix: `0`
- QP/MS/ER/IN/transcript flag mismatches for classified rows: `0`

That means:

- For every paper row the scanner can classify, the matrix is matching correctly.
- The matrix is not inventing wrong availability states for classified rows.
- The remaining mismatch comes from files that never enter the matrix, not from row logic inside the matrix.

## Hard Conclusion

### Are the matrix and the actual available papers the same?

No, not completely.

### Are they close?

Yes.

### Is the matrix internally sane for what it tracks?

Yes.

## Exact Match Findings

I compared the matrix against the filesystem at the paper-key level.

Results:

- `missing_row_keys = 0`
- `extra_row_keys = 0`
- `kind_mismatches = 0`

Interpretation:

- Every classified paper-key seen on disk exists in the matrix.
- The matrix’s `has_qp`, `has_ms`, `has_er`, `has_in`, and `has_transcript` flags match the classified filesystem reality exactly.

So for the classifiable corpus, the matrix is correct.

## Where The Mismatch Actually Comes From

### 1. Review files excluded from the matrix

There are `66` PDFs that the scanner excludes because the filename is too ambiguous to derive an exact year/session/paper row.

All `66` have the same failure reason:

- `Filename was too ambiguous to derive an exact paper year and session`

These are not represented in the matrix at all.

Kind breakdown of those `66`:

- `33` QP-like
- `33` ER-like
- `0` MS-like

This is the main reason the matrix and the raw folder are not identical.

Practical effect:

- Some actual question papers exist on disk but do not count as available in the matrix yet.
- Examiner reports are also being missed, but that does not directly alter QP/MS availability badges.

### 2. Duplicate / alternate copies collapsed out of the matrix

There are `293` classified PDFs on disk that are not surfaced as the chosen file in the matrix.

Breakdown:

- with `-dup` in filename: `197`
- without `-dup`: `96`

These do not create row mismatches because the matrix already chose another file for the same paper slot.

This is mostly de-duplication, not wrong availability.

## Reliability Verdict By Category

### Fully trustworthy

- Standard Cambridge past-paper filenames
- Standard AQA/Edexcel/Cambridge rows once classified
- Matrix complete/missing counts for classified files
- Unknown-year handling (`0` unknown-year rows excluded)

### Trustworthy but de-duplicated

- Cases where multiple copies of the same paper exist
- Alternate but classifiable naming variants

### Not fully trustworthy yet

- Any paper that only exists through one of the `66` excluded review files

## Highest-Risk Excluded File Clusters

Most of the excluded files are concentrated in a few subjects / codes:

- `0460` Geography: `29`
- `0500` First Language English: `14`
- `0625` Physics: `5`
- `0610` Biology: `4`
- `0620` Chemistry: `4`
- plus isolated outliers like `0455`, `4ET1`, `4MA1`

Examples:

- `0460-qp-unknown-1-1.pdf`
- `0460_qp_Unknown_unknown_p1.pdf`
- `0500-er-unknown-1-13.pdf`
- `0610-er-2023-unknown-1-1.pdf`
- `0625_er_2023_unknown_p1.pdf`
- `4ma1-qp-2019-jan-1-3.pdf`

## What This Means For “Available vs Non-Available”

### Matrix says available

Usually safe to trust.

Why:

- Classified row logic matches disk exactly.
- There are no classified row-level availability mismatches.

### Matrix says unavailable

Usually correct, but not always.

Why:

- Some unavailable-looking rows may actually have a QP-like file on disk that sits in the excluded `66` review-file pool.
- So the matrix is slightly conservative.

## Final Bottom Line

If your question is:

“Is the matrix giving me the proper list of available and non-available papers?”

The precise answer is:

- **Yes for the classifiable paper corpus**
- **Not fully for the entire raw folder**

The matrix is structurally correct and sane, but it is incomplete by `66` ambiguous files, including `33` QP-like files that can make some rows look unavailable when there is actually a paper on disk.

## Next Best Action

To make the matrix truly authoritative for IGCSE, the next task is to normalize those `66` ambiguous filenames so they can enter the matrix.

Priority order:

1. `0460` QP files
2. `0500` ER files
3. `0610` / `0620` / `0625` ER files
4. single Edexcel outliers such as `4ma1-qp-2019-jan-1-3.pdf`
