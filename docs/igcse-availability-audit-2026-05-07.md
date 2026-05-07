# IGCSE Availability Audit

Date: 2026-05-07
Folder audited: `C:\Users\gmhome\SynologyDrive\Ragmaterials\exam\igcse`

## Verdict

The availability matrix is broadly reliable for files it can classify, but it is not a perfect representation of everything on disk.

- Unknown-year exclusions: `0`
- Papers in matrix: `3294`
- Classified PDFs on disk: `6445`
- PDFs actually attached to matrix rows: `6152`
- Files needing review and excluded from matrix: `66`
- Classified PDFs not surfaced because a different file won the same slot: `293`

Practical interpretation:

- For standard, well-named files, the matrix is giving a good available/non-available picture.
- The main gap is the `66` review files. These are omitted from the matrix because their filenames are too ambiguous to assign an exact year/session/paper row.
- The `293` classified-but-unused files are mostly duplicates or alternate copies of papers that are already represented by another file in the same slot, so they do not usually change availability status.

## Matrix Summary

- Total matrix paper rows: `3294`
- Complete (QP + MS): `2415` (`73.3%`)
- Missing MS only: `475`
- Missing QP only: `354`
- Missing both: `50`
- Files needing review: `66`
- Unknown-year rows excluded from matrix: `0`

## Filesystem Summary

- Total PDFs in `igcse`: `6511`
- Classified PDFs: `6445`
- Review-item PDFs: `66`
- Matrix-used unique file paths: `6152`
- Classified PDFs not used by the matrix: `293`

## What The Matrix Gets Right

- There are no unknown-year exclusions. That means the matrix is not silently dropping a year-bucket the way it used to in `a-level` or `ib`.
- Every used matrix row points to real file paths on disk.
- Most non-used classified files are redundant copies rather than missing matrix rows.

## What Can Still Make The Matrix Incomplete

### 1. Ambiguous review files excluded from the matrix

All `66` review items were excluded because the scanner could not derive an exact year/session row from the filename.

Reason count:

- `66` -> `Filename was too ambiguous to derive an exact paper year and session`

Likely file kinds among those `66`:

- `33` QP-like files
- `33` ER-like files
- `0` MS-like files

This matters because:

- Omitted QP-like files can make the matrix say a paper is unavailable when a question paper file does exist on disk.
- Omitted ER-like files do not affect the QP/MS availability badge directly, but they do mean the row is incomplete as a file inventory.
- There is no sign here of omitted MS-like review files, so the biggest matrix risk is undercounting available QPs, not mark schemes.

Examples:

- `0460-qp-unknown-1-1.pdf`
- `0460_qp_Unknown_unknown_p1.pdf`
- `0455_qp_Unknown_unknown_p1.pdf`
- `0610-er-2023-unknown-1-1.pdf`
- `0625_er_2023_unknown_p1.pdf`
- `4ma1-qp-2019-jan-1-3.pdf`

### 2. Classified files collapsed into existing matrix rows

There are `293` classified files not surfaced by the matrix because another file was chosen for the same paper slot.

Breakdown:

- `197` have explicit `-dup` in the filename
- `96` do not have `-dup`, but still collide with an already-represented row

Typical examples:

- duplicate Cambridge accounting papers such as `2018-jun-igcse-accounting-cie-0452-1-1-dup1-qp.pdf`
- alternate Edexcel naming variants such as `2023-s-igcse-physics-edexcel-4ph1-01-n-qp.pdf` versus the normalized form the matrix prefers

These usually do not change the available/non-available answer because the row is already marked from another file, but they do mean the matrix is a de-duplicated view rather than a full raw file list.

## Reliability Assessment

### High confidence

- Unknown-year handling
- Standard Cambridge filenames
- Standard normalized AQA/Edexcel/Cambridge QP/MS pairs
- Overall availability counts for well-named papers

### Medium confidence

- Subjects/folders with many alternate Edexcel naming variants
- Rows where the only on-disk evidence is an ambiguously named QP-like review file

### Lower confidence / action needed

- Review-item pool of `66` files, especially the `33` QP-like ones

## Recommendation

If you want the matrix to be fully trustworthy as the source of "available vs non-available" for IGCSE, the next job is not the matrix logic itself. The next job is to normalize the `66` review filenames so they become classifiable.

Priority order:

1. `0460` QP-like unknown files
2. `0500` ER-like unknown files
3. `0610`, `0620`, `0625` ER-like unknown files
4. isolated Edexcel oddballs like `4ma1-qp-2019-jan-1-3.pdf`

## Bottom Line

The matrix is mostly correct for the classified corpus and does not have an unknown-year problem in `igcse`.

But as an authoritative list of all available papers on disk, it is not fully complete yet because `66` ambiguous files are excluded, including `33` QP-like files that can create false "not available" impressions for some rows.
