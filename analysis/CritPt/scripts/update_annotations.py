#!/usr/bin/env python3
"""Pull annotations from Google Sheets using read-only service-account access.

Install: python3 -m pip install -r analysis/CritPt/requirements.txt
Run: GOOGLE_APPLICATION_CREDENTIALS=/path/outside/repo/key.json \
     python3 analysis/CritPt/scripts/update_annotations.py

Share the spreadsheet with the service account's client_email as a Viewer.
Use --sheet-title when more than one tab has a Challenge ID column.
Enable Google Drive API and share uploaded files or their folder as a Viewer too.
Attachments download to solutions/<two_digit_challenge_id>/<name>;
solutions/manifest.json maps each Drive file to its local paths. Folder 00 is
the example; 01-70 keep the public challenge IDs. Duplicate filenames gain a
Drive ID suffix. Google Docs/Slides/Drawings export to PDF, Sheets to XLSX.
ZIPs are extracted within their challenge folders and removed after verification.
After role normalization, source attachments stay in supporting/ and the
reviewed problem.tex, solution.tex and final_answer.tex files are refreshed.
Each challenge's expert_review.txt includes all form questions and responses,
including multiple submissions; it also refreshes with --annotations-only.
Unchanged, checksum-verified files are reused. Old files are retained.
Use --annotations-only to skip attachments. --dry-run checks metadata/access
without downloading or writing files. Reference originals remain unchanged.
"""

import argparse
import csv
import io
import os
from pathlib import Path
import tempfile
from urllib.parse import quote

from download_drive_files import DRIVE_SCOPE, sync_files
from export_expert_reviews import build_expert_reviews, write_expert_reviews


SPREADSHEET_ID = "1LSBYdccdvykcHcQHL_EE_XjklbtVmILKOSZTno1Bfo0"
DESTINATION = Path(__file__).resolve().parents[1] / "annotations.csv"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
ID_COLUMN = "Challenge ID"
FORM_ID_COLUMN = "Enter the challenge ID you are contributing to (a number between 1 and 70)"


def normalize_headers(row):
    headers = [str(value).strip() for value in row]
    return [ID_COLUMN if header == FORM_ID_COLUMN else header for header in headers]


def parse_rows(values):
    if not values or not values[0]:
        raise ValueError("The annotation tab is empty")
    headers = normalize_headers(values[0])
    if ID_COLUMN not in headers:
        raise ValueError("The first row must contain a Challenge ID column")
    if any(not h for h in headers) or len(set(headers)) != len(headers):
        raise ValueError("Column names must be nonempty and unique")
    records = []
    for number, row in enumerate(values[1:], 2):
        if not any(str(value).strip() for value in row):
            continue
        if len(row) > len(headers):
            raise ValueError(f"Row {number} has cells beyond the header")
        record = dict(zip(headers, [str(v) for v in row] + [""] * (len(headers) - len(row))))
        record[ID_COLUMN] = record[ID_COLUMN].strip()
        if not record[ID_COLUMN]:
            raise ValueError(f"Row {number} has no Challenge ID")
        records.append(record)
    if not records:
        raise ValueError("No annotation rows found; existing CSV was not replaced")
    return headers, records


def build_csv(values, destination):
    headers, records = parse_rows(values)
    # final_grade may be a local classification absent from the form responses.
    if destination.exists() and "final_grade" not in headers:
        with destination.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if "final_grade" in (reader.fieldnames or []):
                grades = {}
                for row in reader:
                    challenge_id = row[ID_COLUMN].strip()
                    grade = row["final_grade"]
                    if challenge_id in grades and grades[challenge_id] != grade:
                        raise ValueError(f"Conflicting local grades for {challenge_id}")
                    grades[challenge_id] = grade
                headers.append("final_grade")
                for record in records:
                    record["final_grade"] = grades.get(record[ID_COLUMN], "")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue().encode("utf-8"), len(records)


def atomic_write(destination, data):
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent,
                                         prefix=".annotations.", delete=False) as output:
            temporary_path = Path(output.name)
            output.write(data)
        if destination.exists():
            temporary_path.chmod(destination.stat().st_mode & 0o777)
        temporary_path.replace(destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def get_json(session, url, **params):
    response = session.get(url, params=params, timeout=60)
    if response.status_code in (401, 403, 404):
        raise ValueError(
            f"Google returned HTTP {response.status_code}. Enable the Google Sheets "
            "API in the credential's project and share the spreadsheet with the "
            "service account's client_email as a Viewer."
        )
    response.raise_for_status()
    return response.json()


def fetch_annotations(session, spreadsheet_id, sheet_title=None):
    base_url = f"https://sheets.googleapis.com/v4/spreadsheets/{quote(spreadsheet_id, safe='')}"
    metadata = get_json(session, base_url, fields="sheets(properties(title))")
    titles = [sheet["properties"]["title"] for sheet in metadata["sheets"]]
    if sheet_title is not None:
        if sheet_title not in titles:
            raise ValueError(f"Unknown tab {sheet_title!r}; available tabs: {titles}")
        titles = [sheet_title]
    candidates = []
    for title in titles:
        quoted_title = "'" + title.replace("'", "''") + "'"
        url = f"{base_url}/values/{quote(quoted_title, safe='')}"
        values = get_json(session, url, valueRenderOption="FORMATTED_VALUE").get("values", [])
        if values and ID_COLUMN in normalize_headers(values[0]):
            candidates.append((title, values))
    if len(candidates) != 1:
        raise ValueError(
            f"Expected one annotation tab; found {[title for title, _ in candidates]}. "
            "Use --sheet-title to select a tab with Challenge ID in its first row."
        )
    return candidates[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path,
                        default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
                        help="Service-account JSON key (or set GOOGLE_APPLICATION_CREDENTIALS)")
    parser.add_argument("--spreadsheet-id", default=SPREADSHEET_ID)
    parser.add_argument("--sheet-title", help="Exact tab title; otherwise auto-detect")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and validate without writing")
    parser.add_argument("--annotations-only", action="store_true", help="Skip Drive downloads")
    args = parser.parse_args()
    if args.credentials is None:
        parser.error("Set GOOGLE_APPLICATION_CREDENTIALS or pass --credentials /path/to/key.json")
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2.service_account import Credentials
    except ImportError:
        parser.exit(1, "Install dependencies: python3 -m pip install -r analysis/CritPt/requirements.txt\n")
    try:
        scopes = SCOPES if args.annotations_only else [*SCOPES, DRIVE_SCOPE]
        credentials = Credentials.from_service_account_file(str(args.credentials), scopes=scopes)
        with AuthorizedSession(credentials) as session:
            title, values = fetch_annotations(session, args.spreadsheet_id, args.sheet_title)
            data, count = build_csv(values, DESTINATION)
            headers, records = parse_rows(values)
            reviews = build_expert_reviews(headers, records)
            downloads = None
            if not args.annotations_only:
                downloads = sync_files(session, records, DESTINATION.parent / "solutions", args.dry_run)
        if not args.dry_run:
            atomic_write(DESTINATION, data)
            write_expert_reviews(DESTINATION.parent / "solutions", reviews)
    except Exception as error:
        parser.exit(1, f"Update failed: {error}\n")
    action = "Validated (dry run)" if args.dry_run else "Updated"
    print(f"{action}: {count} annotations from tab {title!r} -> {DESTINATION}")
    print(f"Expert reviews: {len(reviews)} challenge files" + (" (dry run; no writes)" if args.dry_run else ""))
    if downloads is not None:
        print(f"Attachments: {downloads['files']} files, {downloads['downloaded']} downloaded, "
              f"{downloads['cached']} reused" + (" (dry run; metadata checked only)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
