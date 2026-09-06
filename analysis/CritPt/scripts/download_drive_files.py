"""Download annotation attachments into solutions/<challenge_id>/ folders."""

import hashlib
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import parse_qs, urlsplit

from normalize_solutions import extraction_is_valid, normalize_archives

from solution_layout import (
    allocate_paths, copy_file, create_challenge_folders, entry_paths, solution_filename,
)


DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
EXPORTS = {
    "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.drawing": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"
    ),
}


def collect_files(records):
    files = {}
    for record in records:
        if "File uploads" not in record:
            raise ValueError("Missing File uploads column; use --annotations-only to skip downloads")
        # Form cells may contain comma-separated URLs or plain explanatory notes.
        for link in re.findall(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s;,<>]+", record["File uploads"]):
            link = link.rstrip(".)")
            parsed = urlsplit(link)
            if parsed.scheme != "https" or parsed.hostname not in ("drive.google.com", "docs.google.com"):
                raise ValueError(f"Unsupported attachment URL for challenge {record['Challenge ID']}: {link}")
            query = parse_qs(parsed.query)
            match = re.search(r"/d/([A-Za-z0-9_-]+)(?:/|$)", parsed.path)
            file_id = match.group(1) if match else query.get("id", [""])[0]
            if not re.fullmatch(r"[A-Za-z0-9_-]+", file_id):
                raise ValueError(f"Cannot extract Drive file ID from {link}")
            resource_key = query.get("resourcekey", [""])[0]
            if resource_key and not re.fullmatch(r"[A-Za-z0-9_-]+", resource_key):
                raise ValueError(f"Invalid resource key for {file_id}")
            entry = files.setdefault(file_id, {"file_id": file_id, "challenge_ids": [],
                                               "source_urls": [], "resource_key": ""})
            if resource_key:
                entry["resource_key"] = resource_key
            for field, value in (("challenge_ids", record["Challenge ID"]), ("source_urls", link)):
                if value not in entry[field]:
                    entry[field].append(value)
    return files


def check_response(response, file_id):
    if response.status_code in (401, 403, 404):
        raise ValueError(
            f"Cannot access Drive file {file_id} (HTTP {response.status_code}). "
            "Enable Google Drive API and share the file or its folder with the "
            "service account as a Viewer with downloads allowed."
        )
    response.raise_for_status()


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(session, url, params, headers, destination, metadata):
    temporary_path = None
    try:
        digest = hashlib.md5()
        size = 0
        with session.get(url, params=params, headers=headers, stream=True, timeout=60) as response:
            check_response(response, metadata["id"])
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".download.", delete=False) as output:
                temporary_path = Path(output.name)
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
        if params.get("alt") == "media":
            if "size" in metadata and size != int(metadata["size"]):
                raise ValueError(f"Incomplete download for {metadata['id']}")
            if metadata.get("md5Checksum") and digest.hexdigest() != metadata["md5Checksum"]:
                raise ValueError(f"Checksum mismatch for {metadata['id']}")
        checksum = sha256_file(temporary_path)
        temporary_path.replace(destination)
        return checksum
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def sync_files(session, records, directory, dry_run=False):
    files = collect_files(records)
    manifest_path = directory / "manifest.json"
    previous = {}
    manifest = {"files": []}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        previous = {entry["file_id"]: entry for entry in manifest["files"]}
    occupied = {path: entry["file_id"] for entry in previous.values() for path in entry_paths(entry)}
    entries = []
    downloaded = cached = 0
    for file_id, reference in files.items():
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
        headers = {}
        if reference["resource_key"]:
            headers["X-Goog-Drive-Resource-Keys"] = f"{file_id}/{reference['resource_key']}"
        with session.get(url, headers=headers, params={
            "fields": "id,name,mimeType,version,modifiedTime,size,md5Checksum,capabilities(canDownload)",
            "supportsAllDrives": "true",
        }, timeout=60) as response:
            check_response(response, file_id)
            metadata = response.json()
        if metadata.get("capabilities", {}).get("canDownload") is False:
            raise ValueError(f"Downloads are disabled for Drive file {file_id}")
        mime_type = metadata["mimeType"]
        export_mime, extension = EXPORTS.get(mime_type, (None, ""))
        if mime_type.startswith("application/vnd.google-apps.") and export_mime is None:
            raise ValueError(f"Unsupported Drive type {mime_type} for {file_id}; link a file directly")
        name = solution_filename(metadata["name"], extension)
        paths = allocate_paths(file_id, reference["challenge_ids"], name, occupied,
                               manifest.get("source_subdirectory", ""))
        relative_path = paths[0]
        destination = directory / relative_path
        fingerprint = {key: metadata.get(key) for key in
                       ("version", "modifiedTime", "md5Checksum", "size", "mimeType")}
        old = previous.get(file_id, {})
        if (old.get("fingerprint") == fingerprint and entry_paths(old) == paths
                and extraction_is_valid(old, directory)):
            entries.append({**old, **reference})
            cached += 1
            continue
        cached_source = None
        if old.get("fingerprint") == fingerprint:
            for path in entry_paths(old):
                candidate = directory / path
                if candidate.is_file() and old.get("sha256") == sha256_file(candidate):
                    cached_source = candidate
                    break
        entry = {**reference, "name": metadata["name"], "mime_type": mime_type,
                 "export_mime_type": export_mime, "path": relative_path, "paths": paths,
                 "fingerprint": fingerprint}
        if cached_source is not None:
            cached += 1
            entry["sha256"] = old["sha256"]
        elif not dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            params = {"mimeType": export_mime} if export_mime else {"alt": "media", "supportsAllDrives": "true"}
            entry["sha256"] = download(session, url + ("/export" if export_mime else ""),
                                       params, headers, destination, metadata)
            downloaded += 1
        if not dry_run:
            source = cached_source if cached_source is not None else destination
            for path in paths:
                target = directory / path
                if not target.is_file() or sha256_file(target) != entry["sha256"]:
                    copy_file(source, target)
        entries.append(entry)
    if not dry_run:
        # Import here to avoid a module cycle when the updater is run as a script.
        from update_annotations import atomic_write
        create_challenge_folders(directory)
        atomic_write(manifest_path, (json.dumps({**manifest, "files": entries}, indent=2) + "\n").encode())
        normalize_archives(directory)
        if manifest.get("normalize_roles"):
            from normalize_solution_roles import normalize_roles
            normalize_roles(directory, records=records)
    return {"files": len(files), "downloaded": downloaded, "cached": cached}
