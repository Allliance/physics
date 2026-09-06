"""Organize cached attachments in solutions/00 through solutions/70.

00 is the quantum-error-correction example; 01-70 keep the public challenge IDs.
Run python3 analysis/CritPt/scripts/solution_layout.py to reorganize an existing manifest.
"""

import json
from pathlib import Path
import re
import shutil
import tempfile


def challenge_folder(challenge_id):
    if not re.fullmatch(r"[0-9]{1,2}", str(challenge_id)) or not 0 <= int(challenge_id) <= 70:
        raise ValueError(f"Invalid CritPt challenge ID: {challenge_id!r}")
    return f"{int(challenge_id):02d}"


def entry_paths(entry):
    return entry.get("paths", [entry["path"]])


def solution_filename(name, extension=""):
    name = (re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .") or "file")[:150]
    if extension and not name.lower().endswith(extension):
        name += extension
    return name


def allocate_paths(file_id, challenge_ids, name, occupied, subdirectory=""):
    paths = []
    for challenge_id in challenge_ids:
        folder = challenge_folder(challenge_id)
        if subdirectory:
            folder += "/" + subdirectory
        candidate = f"{folder}/{name}"
        if occupied.get(candidate, file_id) != file_id:
            filename = Path(name)
            candidate = f"{folder}/{filename.stem}__{file_id}{filename.suffix}"
        if occupied.get(candidate, file_id) != file_id:
            raise ValueError(f"Conflicting solution path: {candidate}")
        occupied[candidate] = file_id
        if candidate not in paths:
            paths.append(candidate)
    if not paths:
        raise ValueError(f"File {file_id} has no challenge IDs")
    return paths


def copy_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".solution.", delete=False) as output:
            temporary_path = Path(output.name)
            with source.open("rb") as input_file:
                shutil.copyfileobj(input_file, output)
        temporary_path.replace(destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def create_challenge_folders(directory):
    for number in range(71):
        (directory / f"{number:02d}").mkdir(parents=True, exist_ok=True)


def organize_files(directory):
    from download_drive_files import EXPORTS, sha256_file
    from normalize_solutions import extraction_is_valid
    from update_annotations import atomic_write

    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("source_subdirectory") == "supporting":
        for entry in manifest["files"]:
            if entry.get("archive_extracted"):
                if not extraction_is_valid(entry, directory):
                    raise ValueError(f"Missing or changed extracted files for {entry['file_id']}")
            else:
                for path in entry_paths(entry):
                    if sha256_file(directory / path) != entry["sha256"]:
                        raise ValueError(f"Missing or changed source: {path}")
        return len(manifest["files"])
    occupied = {}
    for entry in manifest["files"]:
        for path in entry_paths(entry):
            occupied[path] = entry["file_id"]
    plan = []
    for entry in manifest["files"]:
        if entry.get("archive_extracted"):
            if not extraction_is_valid(entry, directory):
                raise ValueError(f"Missing or changed extracted files for {entry['file_id']}")
            continue
        old_paths = entry_paths(entry)
        source = directory / old_paths[0]
        if not source.is_file() or sha256_file(source) != entry["sha256"]:
            raise ValueError(f"Missing or changed source: {source}")
        extension = EXPORTS.get(entry.get("mime_type"), (None, ""))[1]
        name = solution_filename(entry["name"], extension)
        paths = allocate_paths(entry["file_id"], entry["challenge_ids"], name, occupied)
        for path in paths:
            destination = directory / path
            if destination.exists() and sha256_file(destination) != entry["sha256"]:
                raise ValueError(f"Refusing to replace a different file: {destination}")
        plan.append((entry, old_paths, paths))

    for entry, old_paths, paths in plan:
        for path in paths:
            destination = directory / path
            if not destination.exists():
                copy_file(directory / old_paths[0], destination)
            if sha256_file(destination) != entry["sha256"]:
                raise ValueError(f"Copy checksum mismatch: {destination}")
        entry["path"] = paths[0]
        entry["paths"] = paths
    create_challenge_folders(directory)
    atomic_write(manifest_path, (json.dumps(manifest, indent=2) + "\n").encode())

    # Remove old copies only after every destination and the new manifest exist.
    destinations = {path for _, _, paths in plan for path in paths}
    for _, old_paths, _ in plan:
        for path in old_paths:
            if path not in destinations:
                source = directory / path
                source.unlink()
                if source.parent != directory and not any(source.parent.iterdir()):
                    source.parent.rmdir()
    return len(manifest["files"])


if __name__ == "__main__":
    directory = Path(__file__).resolve().parents[1] / "solutions"
    count = organize_files(directory)
    print(f"Organized {count} Drive files in {directory}/00 through 70")
