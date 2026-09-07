"""Export all 71 original prompts as challenge_id/problem/ground_truth.

Audited references match corrected_challenge.jsonl, including references that
depend on repairs. The original prompts remain unchanged. Challenge 00 uses its
official example answer. Unknown or unresolved references are JSON null.
The source notebooks retain all original metadata and code templates.
"""

import hashlib
import json
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parents[3] / "benchmarks" / "critpt" / "data"
OUTPUT_DIR = Path(__file__).resolve().parents[1]


def cell_text(cell):
    source = cell["source"]
    return source if isinstance(source, str) else "".join(source)


def heading(cell):
    text = cell_text(cell).strip()
    return text.splitlines()[0].rstrip(":").lower() if text else ""


def read_source(path):
    raw = path.read_bytes()
    return {
        "source_notebook": path.relative_to(DATA_DIR).as_posix(),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "notebook": json.loads(raw),
    }


def extract_main(notebook):
    cells = notebook["cells"]
    setup = [cell_text(c) for c in cells
             if c["cell_type"] == "markdown"
             and heading(c) == "# problem setup"]
    main = [cell_text(c) for c in cells
            if c["cell_type"] == "markdown"
            and heading(c) == "# main problem"]
    templates = [i for i, c in enumerate(cells)
                 if c["cell_type"] == "markdown"
                 and heading(c) == "### parsing template"]
    if len(setup) != 1 or len(main) != 1 or not templates:
        raise ValueError("Expected one setup, one main problem, and a template")
    template = cells[templates[0] + 1]
    if template["cell_type"] != "code":
        raise ValueError("Parsing template must be followed by a code cell")
    return {
        "problem_setup": setup[0],
        "main_problem": main[0],
        "problem_description": setup[0] + "\n\n" + main[0],
        "code_template": cell_text(template),
    }


def build_example_record():
    example_dir = DATA_DIR / "example_challenges"
    json_path = example_dir / "json" / "quantum_error_correction_main.json"
    raw = json_path.read_bytes()
    original_json = json.loads(raw)
    problems = original_json["problems"]
    if len(problems) != 1 or problems[0]["problem_type"] != "main":
        raise ValueError("Expected exactly one main problem in the example JSON")
    problem = problems[0]
    setup = problem["metadata"]["problem_setup"]
    description = problem["problem_description"]
    if not description.startswith(setup) or description.count("# Main problem:") != 1:
        raise ValueError("Example JSON has an unexpected setup/main problem layout")
    main_problem = "# Main problem:" + description.split("# Main problem:", 1)[1]
    main_notebook = read_source(example_dir / "quantum_error_correction_main.ipynb")
    full_notebook = read_source(example_dir / "quantum_error_correction.ipynb")
    return {
        "challenge_id": "Challenge_0",
        "problem_id": "Challenge_0_main",
        "split": "example",
        "problem_setup": setup,
        "main_problem": main_problem,
        "problem_description": description,
        "code_template": problem["code_template"],
        **main_notebook,
        "alternate_sources": [full_notebook],
    }


def build_source_records():
    public_dir = DATA_DIR / "public_test_challenges"
    expected = {f"Challenge_{i}.ipynb" for i in range(1, 71)}
    actual = {p.name for p in public_dir.glob("*.ipynb")}
    if actual != expected:
        raise ValueError(f"Unexpected public notebooks: {actual ^ expected}")

    records = [build_example_record()]
    for i in range(1, 71):
        source = read_source(public_dir / f"Challenge_{i}.ipynb")
        records.append({
            "challenge_id": f"Challenge_{i}",
            "problem_id": f"Challenge_{i}_main",
            "split": "public_test",
            **extract_main(source["notebook"]),
            **source,
            "alternate_sources": [],
        })

    represented = {
        source["source_notebook"]
        for record in records
        for source in [record, *record["alternate_sources"]]
    }
    originals = {p.relative_to(DATA_DIR).as_posix()
                 for p in DATA_DIR.rglob("*.ipynb")}
    if represented != originals:
        raise ValueError(f"Unaccounted notebooks: {represented ^ originals}")
    assert len(records) == len({r["challenge_id"] for r in records}) == 71
    assert [r["challenge_id"] for r in records] == [f"Challenge_{i}" for i in range(71)]
    assert all(list(record) == list(records[1]) for record in records)

    return records


def project_original_records(records, ground_truths):
    return [{"challenge_id": f"{int(record['challenge_id'].split('_')[-1]):02d}",
             "problem": record["problem_description"].strip(),
             "ground_truth": ground_truths.get(f"{int(record['challenge_id'].split('_')[-1]):02d}")}
            for record in records]


def main():
    from build_corrected_challenges import build_corrected_challenges, text_body
    from update_annotations import atomic_write

    records = build_source_records()
    rows, _, _ = build_corrected_challenges(OUTPUT_DIR)
    ground_truths = {row["challenge_id"]: row["ground_truth"] for row in rows}
    example_path = OUTPUT_DIR / "solutions/00/final_answer.tex"
    if example_path.is_file():
        # The official example has already been verified against its website.
        ground_truths["00"] = text_body(example_path.read_text())
    projected = project_original_records(records, ground_truths)
    jsonl_path = OUTPUT_DIR / "original_challenges.jsonl"
    current = {}
    for line in jsonl_path.read_text().splitlines():
        record = json.loads(line)
        challenge = f"{int(record['challenge_id'].split('_')[-1]):02d}"
        current[challenge] = record.get("problem", record.get("problem_description", "")).strip()
    if current != {row["challenge_id"]: row["problem"] for row in projected}:
        raise ValueError("Original source statements changed; review before replacing the archive")

    data = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in projected).encode()
    # This is a schema-only migration of the reviewed original prompts. Keep the
    # audit's integrity snapshot in sync without blessing unrelated source edits.
    # build_corrected_challenges validated every reviewed source before this write.
    review_path = OUTPUT_DIR / "verdict_review.json"
    review = json.loads(review_path.read_text())
    review["source_sha256"]["original_challenges.jsonl"] = hashlib.sha256(data).hexdigest()
    review["policy"]["original_export"] = (
        "All 71 original statements, with zero-padded challenge_id, problem and ground_truth only. "
        "References are the audited answers used in the corrected dataset, which may depend on "
        "repairs; null denotes an unavailable or unresolved reference. The official example "
        "answer is included for 00. Original source notebooks retain metadata and templates."
    )
    atomic_write(jsonl_path, data)
    atomic_write(review_path, (json.dumps(review, indent=2, ensure_ascii=False) + "\n").encode())
    available = sum(row["ground_truth"] is not None for row in projected)
    print(f"Wrote {len(projected)} original challenges; {available} references, {len(projected)-available} null: {jsonl_path}")


if __name__ == "__main__":
    main()
