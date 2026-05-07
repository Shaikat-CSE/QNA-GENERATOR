#!/usr/bin/env python3
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pdf_availability_scanner import scan_pdf_directory_report

parser = argparse.ArgumentParser()
parser.add_argument('--base', required=True, help='Base directory to scan')
args = parser.parse_args()

base_path = Path(args.base)

print(f"Scanning {base_path.name} directory for missing files...")
print()

report = scan_pdf_directory_report(base_path)

# Statistics
total = len(report.papers)
complete = sum(1 for p in report.papers if p.has_qp and p.has_ms)
missing_ms = sum(1 for p in report.papers if p.has_qp and not p.has_ms)
missing_qp = sum(1 for p in report.papers if not p.has_qp and p.has_ms)
missing_both = sum(1 for p in report.papers if not p.has_qp and not p.has_ms)
unknown_year = sum(1 for p in report.papers if p.year == "unknown")

print(f"=== Availability Report ===")
print(f"Total papers: {total}")
print(f"Complete (QP+MS): {complete} ({complete/total*100:.1f}%)")
print(f"Missing MS only: {missing_ms}")
print(f"Missing QP only: {missing_qp}")
print(f"Missing both: {missing_both}")
print(f"Files need review: {len(report.review_items)}")
print(f"Unknown-year rows excluded from matrix: {unknown_year}")
print()

# By subject
from collections import defaultdict
by_subject = defaultdict(lambda: {"complete": 0, "missing_ms": 0, "missing_qp": 0})

for p in report.papers:
    if p.has_qp and p.has_ms:
        by_subject[p.subject]["complete"] += 1
    elif p.has_qp:
        by_subject[p.subject]["missing_ms"] += 1
    elif p.has_ms:
        by_subject[p.subject]["missing_qp"] += 1

print("=== By Subject ===")
for subject in sorted(by_subject.keys()):
    stats = by_subject[subject]
    total_subj = sum(stats.values())
    print(f"{subject}:")
    print(f"  Complete: {stats['complete']}/{total_subj}")
    print(f"  Missing MS: {stats['missing_ms']}")
    print(f"  Missing QP: {stats['missing_qp']}")

# Show some missing files
if missing_ms > 0:
    print(f"\n=== Sample Missing MS (first 10) ===")
    count = 0
    for p in report.papers:
        if p.has_qp and not p.has_ms:
            print(f"  {p.paper_key}")
            count += 1
            if count >= 10:
                break

if missing_qp > 0:
    print(f"\n=== Sample Missing QP (first 10) ===")
    count = 0
    for p in report.papers:
        if not p.has_qp and p.has_ms:
            print(f"  {p.paper_key}")
            count += 1
            if count >= 10:
                break

# Review items
if report.review_items:
    print(f"\n=== Files Needing Review (first 10) ===")
    for item in report.review_items[:10]:
        print(f"  {item.filename}")
        print(f"    Reason: {item.reason}")

if unknown_year > 0:
    print(f"\n=== Unknown-Year Rows Excluded From Matrix (first 10) ===")
    count = 0
    for p in report.papers:
        if p.year != "unknown":
            continue
        paths = [p.qp_path, p.ms_path, p.er_path, p.in_path, p.transcript_path]
        attached = next((path for path in paths if path and path != "-"), "-")
        print(f"  {p.paper_key}")
        print(f"    File: {Path(attached).name if attached != '-' else '-'}")
        count += 1
        if count >= 10:
            break
