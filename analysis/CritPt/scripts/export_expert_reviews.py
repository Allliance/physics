#!/usr/bin/env python3
"""Export form questions and answers to solutions/NN/expert_review.txt.

Run directly to rebuild from annotations.csv. The Google Sheets updater also
refreshes these files. All submissions remain in spreadsheet row order.
"""

import argparse
import csv
from pathlib import Path

from solution_layout import challenge_folder


BASE = Path(__file__).resolve().parents[1]


def build_expert_reviews(headers, records):
    from update_annotations import FORM_ID_COLUMN, ID_COLUMN

    grouped = {f"{number:02d}": [] for number in range(71)}
    for row_number, record in enumerate(records, 2):
        folder = challenge_folder(record[ID_COLUMN].strip())
        grouped[folder].append((row_number, record))

    # final_grade is a local classification, not a respondent's form answer.
    questions = [header for header in headers if header != "final_grade"]
    reviews = {}
    for folder, submissions in grouped.items():
        parts = [f"Expert review — Challenge {folder}\n",
                 f"Form submissions: {len(submissions)}\n"]
        if not submissions:
            parts.append("\nNo form submission available in annotations.csv.\n")
        for number, (row_number, record) in enumerate(submissions, 1):
            parts.append(f"\n{'=' * 72}\nSubmission {number} (annotations.csv row {row_number})\n"
                         f"{'=' * 72}\n")
            for question in questions:
                label = FORM_ID_COLUMN if question == ID_COLUMN else question
                answer = record.get(question, "")
                parts.append(f"\nQuestion: {label}\nAnswer:\n"
                             + (answer if answer else "[No answer provided]") + "\n")
        reviews[folder] = "".join(parts).encode("utf-8")
    return reviews


def write_expert_reviews(directory, reviews):
    from update_annotations import atomic_write

    for folder, data in reviews.items():
        destination = directory / folder / "expert_review.txt"
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(destination, data)


def main():
    from update_annotations import parse_rows

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, default=BASE / "annotations.csv")
    parser.add_argument("--solutions", type=Path, default=BASE / "solutions")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with args.annotations.open(encoding="utf-8-sig", newline="") as source:
        headers, records = parse_rows(list(csv.reader(source)))
    reviews = build_expert_reviews(headers, records)
    if not args.dry_run:
        write_expert_reviews(args.solutions, reviews)
    action = "Validated" if args.dry_run else "Wrote"
    print(f"{action} {len(reviews)} expert_review.txt files from {len(records)} form submissions.")


if __name__ == "__main__":
    main()
