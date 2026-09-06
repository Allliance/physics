"""Build problem.tex, solution.tex and final_answer.tex from reviewed submissions.

Original submissions remain in each challenge's supporting/ directory. The
JSON report records provenance and the CSV report lists every exception.
No new physics answers are generated: combined documents are excerpted using
the explicitly reviewed rules below.
"""

import csv
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import re

from solution_layout import entry_paths


BASE = Path(__file__).resolve().parents[1]
ROLES = ("problem", "solution", "final_answer")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def between(text, start, end):
    if text.count(start) != 1:
        raise ValueError(f"Expected one start marker: {start}")
    offset = text.index(start)
    return text[offset:text.index(end, offset)]


def equation(text, marker):
    offset = text.index(marker)
    start = text.rfind(r"\begin{equation}", 0, offset)
    end = text.index(r"\end{equation}", offset) + len(r"\end{equation}")
    if start < 0:
        raise ValueError(f"No equation enclosing {marker}")
    return text[start:end]


def excerpt_document(text, body, number, role):
    """Keep the original preamble/macros when excerpting a standalone source."""
    if r"\begin{document}" not in text:
        return f"% Extracted from the submitted challenge {number:02d} document.\n" + body.strip() + "\n"
    preamble = text.split(r"\begin{document}", 1)[0]
    title = role.replace("_", " ").capitalize()
    return (preamble + f"\\title{{Challenge {number:02d}: {title}}}\n\\author{{}}\n"
            + "\\begin{document}\n\\maketitle\n" + body.strip() + "\n\\end{document}\n")


def original_problem_tex(record):
    text = record["problem_description"]
    text = text.replace("# Problem setup:", r"\section*{Problem setup}")
    text = text.replace("# Main problem:", r"\section*{Main problem}")
    text = re.sub(r"\$\$(.*?)\$\$", lambda m: "\\[" + m[1] + "\\]", text, flags=re.S)
    return ("% Official example statement; no reviewer revision was supplied.\n"
            "\\documentclass{article}\n\\usepackage{amsmath,amssymb}\n"
            "\\begin{document}\n" + text.strip() + "\n\\end{document}\n")


def timestamps(records):
    result = {}
    for record in records:
        try:
            stamp = datetime.strptime(record.get("Timestamp", ""), "%m/%d/%Y %H:%M:%S")
        except ValueError:
            stamp = datetime.min
        for file_id in re.findall(r"[?&]id=([A-Za-z0-9_-]+)|/d/([A-Za-z0-9_-]+)", record.get("File uploads", "")):
            identifier = next(part for part in file_id if part)
            result[identifier] = max(result.get(identifier, datetime.min), stamp)
    return result


def normalize_roles(directory, records=None, dry_run=False):
    from update_annotations import atomic_write

    directory = directory.resolve()
    report_path = directory.parent / "solution_normalization_report.json"
    exceptions_path = directory.parent / "solution_normalization_exceptions.csv"
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"files": []}
    originals = {int(row["challenge_id"].split("_")[-1]): row for row in
                 map(json.loads, (BASE / "original_challenges.jsonl").read_text().splitlines())}
    if records is None:
        with (directory.parent / "annotations.csv").open(newline="") as source:
            records = list(csv.DictReader(source))
    stamps = timestamps(records)
    path_stamps = {}
    for entry in manifest["files"]:
        for path in entry_paths(entry):
            path_stamps[path] = stamps.get(entry["file_id"], datetime.min)
    previous = json.loads(report_path.read_text()) if report_path.exists() else {"challenges": []}
    previous_hashes = {item["path"]: item["sha256"] for row in previous["challenges"]
                       for item in row["files"].values()}
    plans = []
    report = []

    for number in range(71):
        folder = directory / f"{number:02d}"
        # Cleaned challenges have canonical files only. Preserve them until fresh
        # uploads are downloaded; this also preserves the public example (00).
        if manifest.get("remove_supporting") and not (folder / "supporting").exists():
            row = next(row for row in previous["challenges"] if row["challenge"] == f"{number:02d}")
            for item in row["files"].values():
                path = directory / item["path"]
                if not path.is_file() or digest(path.read_bytes()) != item["sha256"]:
                    raise ValueError(f"Canonical file was edited; review before regenerating: {path}")
            report.append(row)
            continue
        source_root = folder / "supporting" if (folder / "supporting").is_dir() else folder
        files = sorted(source_root.rglob("*.tex")) if source_root.exists() else []
        selected = {}
        exceptions = []

        def read(path):
            return path.read_text(encoding="utf-8")

        def find(pattern):
            matches = [p for p in files if p.match(pattern)]
            if len(matches) != 1:
                raise ValueError(f"Challenge {number:02d}: expected one {pattern}, found {len(matches)}")
            return matches[0]

        def add(role, source, body=None, note="copied submitted file"):
            content = read(source) if body is None else body
            # Keep figures, bibliography, and TeX inputs reachable from the canonical file.
            source_dir = Path("supporting") / source.relative_to(source_root).parent
            for command in ("includegraphics", "input", "include", "bibliography"):
                pattern = r"(\\" + command + r"(?:\[[^\]]*\])?\{)([^{}]+)(\})"
                def rewrite(match):
                    target = match[2]
                    if target.startswith(("/", "http:", "https:")):
                        return match[0]
                    return match[1] + (source_dir / target).as_posix() + match[3]
                content = re.sub(pattern, rewrite, content)
            selected[role] = {"source": f"{number:02d}/supporting/{source.relative_to(source_root).as_posix()}",
                              "source_sha256": digest(source.read_bytes()), "action": note,
                              "content": content.encode("utf-8")}

        # Most submissions explicitly name each role. Exclude model answers and reports.
        for role in ROLES:
            candidates = [p for p in files if re.match(
                r"^" + role + r"(?:\.tex$| - |__|_revised(?: - |\.tex)|reviewed(?: - |\.tex)|_60(?: - |\.tex))", p.name)]
            if number in (16, 48) and role == "final_answer":
                candidates = []  # These labels actually contain full derivations.
            if number == 35:
                wrong = {digest(p.read_bytes()) for p in (directory / "17").rglob("*.tex")
                         if p.name.startswith(("solution", "final_answer"))}
                candidates = [p for p in candidates if digest(p.read_bytes()) not in wrong]
            if candidates:
                candidates.sort(key=lambda p: (path_stamps.get(p.relative_to(directory).as_posix(), datetime.min),
                                               "Submission" in p.parts, p.as_posix()))
                chosen = candidates[-1]
                add(role, chosen)
                if len(candidates) > 1:
                    distinct = len({digest(p.read_bytes()) for p in candidates})
                    exceptions.append(f"{role}: {'identical duplicate submissions' if distinct == 1 else 'different submissions; selected the latest form submission'}; all originals retained.")

        if number == 0 and files:
            source = find("detailed_solution.tex")
            add("solution", source, note="renamed official detailed solution")
            selected["problem"] = {"source": "../original_challenges.jsonl#Challenge_0",
                                   "source_sha256": digest(originals[0]["problem_description"].encode()),
                                   "action": "converted official example statement; not a reviewer revision",
                                   "content": original_problem_tex(originals[0]).encode()}
            exceptions.append("Official example, not a reviewer submission; problem.tex is the supplied original statement.")

        if number in (3, 53, 64) and files:
            source = next(p for p in files if p.name.startswith("solution -"))
            text = read(source)
            if number == 3:
                body = equation(text, r"\label{eq:wkb}") + "\n"
                body += between(text, r"\section{Renormalisation and result}", r"\section{Consistency checks}")
                exceptions.append("Final answer retains the author's undetermined operator-normalization factor and WKB qualification.")
            elif number == 53:
                body = equation(text, "A_2=1,") + "\n" + equation(text, r"\gamma^{(3)}_{ij}-A_3")
                body += "\n" + r"$A_3=\frac13$. At the critical dimension $d=6$ the second coefficient equals $-\frac23$."
            else:
                body = equation(text, "G_{(1)}=") + "\n" + equation(text, "G_{(2)}=")
            add("final_answer", source, excerpt_document(text, body, number, "final_answer"), "extracted explicit result from detailed solution")
            exceptions.append("No separate final-answer upload; final_answer.tex was extracted from the submitted solution.")

        if number in (16, 20, 39) and files:
            pattern = {16: "final_answer - *.tex", 20: "challenge20.tex", 39: "challenge39.tex"}[number]
            source = find(pattern)
            text = read(source)
            add("solution", source, note="combined submitted document contains the full detailed solution")
            if number == 16:
                statement = between(text, r"\section{Problem statement and interpretation}", r"\section{Noninteracting band structure}")
                statement += "\n" + originals[number]["main_problem"].split("# Main problem:", 1)[1]
                answer = between(text, "Thus the exact critical interaction strength is", r"\end{document}")
                exceptions.append("Upload named final_answer was a full derivation. Extracted its stated momentum-diagonal model and result; appended the unchanged original question. Result is conditional on that literal interaction, not a real-space Hubbard model.")
            elif number == 20:
                statement = between(text, r"\section{Statement and strategy}", "The derivation has four steps:")
                answer = "\n\n".join(equation(text, r"\label{eq:" + label + "}")
                                        for label in ("alpha", "L", "dalpha", "inertia", "omegat", "g"))
                answer += "\n" + r"$E_0^2=4P_0/(\pi w_0^2\epsilon_0c)$; $C=\tfrac12$ for the cycle-averaged convention, or $C=1$ in the cited paper's convention."
                exceptions.append("Combined document split into roles. Final answer retains the author's factor-of-two convention for g; generalized-problem and cross-check material remains supporting content.")
            else:
                statement = between(text, r"\section{Statement}", r"\section{Derivation}")
                statement = statement.replace(r"Sec.~\ref{sec:qutip}", "the accompanying detailed solution")
                answer = equation(text, r"\label{eq:coherent}")
                exceptions.append("Combined document split into roles. Used the coherent-input result requested by the challenge; squeezed-input bonus and cross-checks remain in the full submitted solution/supporting files.")
            add("problem", source, excerpt_document(text, statement, number, "problem"), "extracted author's problem statement/interpretation")
            add("final_answer", source, excerpt_document(text, answer, number, "final_answer"), "extracted designated result and its qualifications")

        if number in (42, 45, 59) and files:
            source = find({42: "Graphene*.tex", 45: "Goniopolarity*.tex", 59: "CDW*.tex"}[number])
            text = read(source)
            add("solution", source, note="renamed descriptive combined solution document")
            if number == 42:
                answer = between(text, "Therefore in summary, we have:", r"\vspace{1em}")
                exceptions.append("Final answer extracted from the author's summary, including all qualitative TI/scattering answers. No complete revised problem upload; clarification requests exist only in annotations.")
            elif number == 45:
                statement = between(text, "Consider a two-band, two-dimensional intrinsic semiconductor", r"\section*{1. Intrinsic chemical potential}")
                statement += "\n" + r"What condition should the effective masses $m_{c/v,\alpha}$, $\alpha=x,y$, satisfy to exhibit goniopolarity?"
                add("problem", source, excerpt_document(text, statement, number, "problem"), "extracted submitted model and retained original task")
                answer = equation(text, r"\label{eq:eta}") + "\n" + equation(text, r"\label{eq:A}")
                answer += "\n" + equation(text, r"\label{eq:Salpha}")
                answer += "\n" + between(text, r"\section*{4. Condition for goniopolarity}", r"\subsection*{Compact equivalent derivation}")
                exceptions.append("Problem and final answer extracted from the combined document. Retained equal, energy-independent lifetimes and distinguished the exact nondegenerate condition from its large-gap approximation.")
            else:
                answer = between(text, "Thus\n", "For the first-order term, using")
                answer += "\n" + between(text, "Around the parent peak", r"\newpage")
                exceptions.append("Final answer extracted from the first-order result. Higher-harmonic discussion is supporting derivation, not the designated first-order answer; no complete revised problem upload.")
            add("final_answer", source, excerpt_document(text, answer, number, "final_answer"), "extracted explicit answer from combined solution")

        if number == 48 and files:
            source = find("final_answer - *.tex")
            text = read(source)
            add("solution", source, note="file labelled final_answer contains the detailed derivation")
            answer = "\n\\subsubsection*{Final Answer}\n" + text[text.index("At\n"):]
            add("final_answer", source, answer, "extracted concluding numerical answer")
            exceptions.append("Split the file labelled final_answer into a detailed solution and concluding answer. The revised problem explicitly supplies the analytic-continuation prescription.")

        if number == 54 and files:
            source = find("solutionreviewed*.tex")
            answer = r"""\subsubsection*{Final Answer}
\[
\begin{array}{ccl}
\text{Isotope}&\text{Transition}&\text{Wavelength (nm)}\\
{}^{174}\mathrm{Yb}&\pi&\simeq532\\
{}^{174}\mathrm{Yb}&\sigma^{\pm}&\simeq483\quad\text{(inferred)}\\
{}^{171}\mathrm{Yb}&\pi&486.78\pm0.10\\
{}^{171}\mathrm{Yb}&\sigma^{\pm}&\simeq483
\end{array}
\]
These are the values discussed in the reviewed solution, drawn from different
experimental geometries. The 532 nm value is a reported near-magic condition;
the 174-Yb 483 nm entry is inferred from shared electronic polarizability.
The reviewer does not establish that this list exhausts all crossings from
400 to 600 nm. The 171-Yb 483 nm value uses polarization perpendicular to the
magnetic field. See solution.tex for the geometry and literature qualifications.
"""
            add("final_answer", source, answer, "collected the four explicit wavelength/transition results and retained reviewer qualifications")
            exceptions.append("Reviewed solution preserves an AI-derived/literature-based calculation with comments. Wavelengths use different geometries; the 174-Yb 483 nm result is inferred and the list is not established as exhaustive. No unambiguous revised problem supplied.")

        if number == 35 and files:
            exceptions.append("Excluded the entropy solution/final answer that are byte-identical to challenge 17 uploads. Selected the Hamiltonian-reconstruction pair for challenge 35; wrong attachments remain in supporting/.")
        if number == 38:
            exceptions.append("Annotations refer to explanation.txt, but no attachment URL or file was supplied.")
        if number in (26, 32, 50) and files:
            exceptions.append("Only a problem file was uploaded; review notes asserting verification are not a detailed solution or final answer.")
        if number in (56, 57) and files:
            exceptions.append("Selected the reviewer's replacement solution and answer, not ai_solution/ai_final_answer. The submitted problem was explicitly left unchanged; additional assumptions are in the solution. Figures and bibliography are retained under supporting/Submission/.")

        missing = [role + ".tex" for role in ROLES if role not in selected]
        if missing:
            exceptions.insert(0, "Missing: " + ", ".join(missing) + ".")
        row = {"challenge": f"{number:02d}", "files": {}, "missing": missing,
               "exceptions": exceptions}
        for role, item in selected.items():
            relative = f"{number:02d}/{role}.tex"
            destination = directory / relative
            if relative in previous_hashes and destination.exists() and digest(destination.read_bytes()) != previous_hashes[relative]:
                raise ValueError(f"Canonical file was edited; review before regenerating: {destination}")
            row["files"][role] = {key: value for key, value in item.items() if key != "content"}
            row["files"][role].update(path=relative, sha256=digest(item["content"]))
            plans.append((destination, item["content"]))
        report.append(row)

    payload = {"challenges": report, "complete_challenges": sum(not row["missing"] for row in report),
               "canonical_files": sum(len(row["files"]) for row in report),
               "source_policy": previous.get("source_policy") if manifest.get("remove_supporting") else
               "Original submissions preserved under each challenge's supporting/ directory."}
    if dry_run:
        return payload

    # Preserve original directory trees and bytes before publishing canonical files.
    for number in range(71):
        folder = directory / f"{number:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        supporting = folder / "supporting"
        if not supporting.exists():
            if manifest.get("remove_supporting"):
                continue
            children = [child for child in folder.iterdir() if child.name != "expert_review.txt"]
            if children:
                supporting.mkdir()
                for child in children:
                    child.rename(supporting / child.name)
    if manifest.get("source_subdirectory") != "supporting":
        def relocated(path):
            first, rest = path.split("/", 1)
            return f"{first}/supporting/{rest}"
        for entry in manifest["files"]:
            entry["path"] = relocated(entry["path"])
            entry["paths"] = [relocated(path) for path in entry["paths"]]
            for item in entry.get("extracted_files", []):
                item["path"] = relocated(item["path"])
            if "extracted_directories" in entry:
                entry["extracted_directories"] = [relocated(path) for path in entry["extracted_directories"]]
        manifest["source_subdirectory"] = "supporting"
    manifest["normalize_roles"] = True
    for destination, data in plans:
        atomic_write(destination, data)
    if manifest_path.exists():
        atomic_write(manifest_path, (json.dumps(manifest, indent=2) + "\n").encode())
    atomic_write(report_path, (json.dumps(payload, indent=2) + "\n").encode())
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["challenge", "exception"])
    for row in report:
        writer.writerows((row["challenge"], note) for note in row["exceptions"])
    atomic_write(exceptions_path, output.getvalue().encode())
    if manifest.get("remove_supporting"):
        from remove_supporting import remove_supporting
        remove_supporting(directory, payload)
    return payload


if __name__ == "__main__":
    result = normalize_roles(BASE / "solutions")
    print(f"Normalized {result['canonical_files']} files; {result['complete_challenges']} challenges have all three roles.")
    print(BASE / "solution_normalization_exceptions.csv")
