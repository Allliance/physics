"""Extract solution ZIPs in place, verify contents, and then remove the archives."""

import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile

from solution_layout import copy_file, entry_paths


def extraction_is_valid(entry, directory):
    from download_drive_files import sha256_file

    return (entry.get("archive_extracted", False)
            and all((directory / item["path"]).is_file()
                    and sha256_file(directory / item["path"]) == item["sha256"]
                    for item in entry["extracted_files"])
            and all((directory / path).is_dir() for path in entry.get("extracted_directories", [])))


def extract_archive(archive, directory, prior_hashes):
    from download_drive_files import sha256_file

    files = []
    directories = []
    seen = set()
    with tempfile.TemporaryDirectory(dir=archive.parent, prefix=".extract.") as temporary:
        staging = Path(temporary)
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                path = PurePosixPath(member.filename)
                mode = stat.S_IFMT(member.external_attr >> 16)
                if (path.is_absolute() or ".." in path.parts or "\\" in member.filename
                        or not path.parts or ":" in path.parts[0]
                        or mode not in (0, stat.S_IFREG, stat.S_IFDIR)):
                    raise ValueError(f"Unsafe archive member: {member.filename!r}")
                if path in seen:
                    raise ValueError(f"Duplicate archive member: {member.filename!r}")
                seen.add(path)
                destination = archive.parent / path
                if not destination.resolve().is_relative_to(archive.parent.resolve()):
                    raise ValueError(f"Archive member escapes challenge folder: {member.filename!r}")
                relative = destination.relative_to(directory).as_posix()
                if member.is_dir():
                    if destination.exists() and not destination.is_dir():
                        raise ValueError(f"Directory conflicts with existing file: {destination}")
                    directories.append(relative)
                    continue
                if destination == archive or destination.is_symlink():
                    raise ValueError(f"Archive member conflicts with source or symlink: {destination}")
                staged = staging / path
                staged.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member) as input_file, staged.open("wb") as output:
                    shutil.copyfileobj(input_file, output)
                checksum = sha256_file(staged)
                if destination.exists():
                    if not destination.is_file() or sha256_file(destination) not in (
                            checksum, prior_hashes.get(relative)):
                        raise ValueError(f"Archive member conflicts with existing content: {destination}")
                files.append({"path": relative, "sha256": checksum})
        # All archive members and destination conflicts are checked before writing.
        for relative in directories:
            (directory / relative).mkdir(parents=True, exist_ok=True)
        for item in files:
            destination = directory / item["path"]
            copy_file(staging / destination.relative_to(archive.parent), destination)
            if sha256_file(destination) != item["sha256"]:
                raise ValueError(f"Extracted file failed verification: {destination}")
    return files, directories


def normalize_archives(directory):
    from update_annotations import atomic_write

    directory = directory.resolve()
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"files": []}
    count = 0
    extracted_count = 0
    while True:
        archives = sorted(p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() == ".zip")
        if not archives:
            break
        for archive in archives:
            relative = archive.relative_to(directory).as_posix()
            prior = {item["path"]: item["sha256"] for entry in manifest["files"]
                     for item in entry.get("extracted_files", [])}
            files, directories = extract_archive(archive, directory, prior)
            for entry in manifest["files"]:
                is_original = relative in entry_paths(entry)
                is_nested = any(item["path"] == relative for item in entry.get("extracted_files", []))
                if is_original or is_nested:
                    # Keep other challenge copies and replace this archive's descendants.
                    base = archive.parent.relative_to(directory)
                    retained = [item for item in entry.get("extracted_files", [])
                                if item["path"] != relative and
                                (is_nested or not Path(item["path"]).is_relative_to(base))]
                    entry["archive_extracted"] = True
                    entry["extracted_files"] = retained + files
                    entry["extracted_directories"] = sorted(set(entry.get("extracted_directories", []) + directories))
            if manifest_path.exists():
                atomic_write(manifest_path, (json.dumps(manifest, indent=2) + "\n").encode())
            archive.unlink()
            count += 1
            extracted_count += len(files)
            print(f"Extracted {relative}: {len(files)} files; removed ZIP")
    return {"archives": count, "extracted_files": extracted_count}


if __name__ == "__main__":
    result = normalize_archives(Path(__file__).resolve().parents[1] / "solutions")
    print(f"Finished: {result['archives']} ZIPs extracted and removed")
