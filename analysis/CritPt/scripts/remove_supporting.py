#!/usr/bin/env python3
"""Remove source upload folders, retaining assets referenced by canonical TeX."""

import json
from pathlib import Path
import re
import shutil

from download_drive_files import sha256_file
from solution_layout import copy_file


def remove_supporting(directory, report=None):
    from update_annotations import atomic_write

    directory = directory.resolve()
    report_path = directory.parent / "solution_normalization_report.json"
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if report is None:
        report = (json.loads(report_path.read_text()) if report_path.exists()
                  else manifest["normalization"])
    plans = []
    assets = {}
    for row in report["challenges"]:
        folder = directory / row["challenge"]
        for item in row["files"].values():
            path = directory / item["path"]
            if sha256_file(path) != item["sha256"]:
                raise ValueError(f"Canonical file was edited; review before cleanup: {path}")
            text = path.read_text()

            def replace(match):
                targets = []
                for target in match[3].split(","):
                    if target.startswith("supporting/"):
                        relative = Path(target.removeprefix("supporting/"))
                        if relative.is_absolute() or ".." in relative.parts:
                            raise ValueError(f"Unsafe asset reference: {target}")
                        source = folder / target
                        suffixes = ("", ".bib") if match[2] == "bibliography" else ("", ".tex", ".pdf", ".png", ".jpg", ".eps")
                        candidates = [(Path(str(source) + suffix), suffix) for suffix in suffixes
                                      if Path(str(source) + suffix).is_file()]
                        if not candidates:
                            # Standalone uploads may use assets from the bundle.
                            source = folder / "supporting/Submission" / relative
                            candidates = [(Path(str(source) + suffix), suffix) for suffix in suffixes
                                          if Path(str(source) + suffix).is_file()]
                        if not candidates:
                            raise ValueError(f"Missing referenced asset: {source}")
                        for candidate, suffix in candidates:
                            destination = folder / (str(relative) + suffix)
                            if destination.exists() and sha256_file(destination) != sha256_file(candidate):
                                raise ValueError(f"Asset conflicts with existing file: {destination}")
                            assets[destination] = candidate
                        target = relative.as_posix()
                    targets.append(target)
                return match[1] + ",".join(targets) + "}"

            updated = re.sub(r"(\\(includegraphics|input|include|bibliography)(?:\[[^\]]*\])?\{)([^{}]+)\}", replace, text)
            if updated != text:
                plans.append((path, updated.encode(), item))

    # Validate every reference/conflict before modifying files or deleting uploads.
    for destination, source in assets.items():
        copy_file(source, destination)
    for path, data, item in plans:
        atomic_write(path, data)
        item["sha256"] = sha256_file(path)
    report["source_policy"] = (
        "Source upload folders removed after normalization. Source paths and hashes "
        "are historical provenance; required TeX assets remain beside canonical files."
    )
    if report_path.exists():
        atomic_write(report_path, (json.dumps(report, indent=2) + "\n").encode())
    else:
        manifest["normalization"] = report
    manifest["remove_supporting"] = True
    atomic_write(manifest_path, (json.dumps(manifest, indent=2) + "\n").encode())
    removed = 0
    for number in range(71):
        supporting = directory / f"{number:02d}" / "supporting"
        if supporting.exists():
            shutil.rmtree(supporting)
            removed += 1
    return removed


if __name__ == "__main__":
    directory = Path(__file__).resolve().parents[1] / "solutions"
    print(f"Removed {remove_supporting(directory)} supporting folders.")
