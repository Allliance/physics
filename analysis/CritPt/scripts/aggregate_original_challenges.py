"""Aggregate challenges 0-70; challenge 0 uses the supplied main-example JSON."""

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


def main():
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

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path = OUTPUT_DIR / "original_challenges.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Aggregated {len(records)} distinct challenges from {len(represented)} notebooks")
    print(jsonl_path)


if __name__ == "__main__":
    main()
