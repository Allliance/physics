"""Aggregate the 70 public challenges and one example without executing notebooks."""

import hashlib
import json
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
OUTPUT_DIR = Path(__file__).resolve().parents[3] / "analysis" / "CritPt"


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


def main():
    public_dir = DATA_DIR / "public_test_challenges"
    expected = {f"Challenge_{i}.ipynb" for i in range(1, 71)}
    actual = {p.name for p in public_dir.glob("*.ipynb")}
    if actual != expected:
        raise ValueError(f"Unexpected public notebooks: {actual ^ expected}")

    records = []
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

    example_dir = DATA_DIR / "example_challenges"
    example = read_source(example_dir / "quantum_error_correction.ipynb")
    alternate = read_source(example_dir / "quantum_error_correction_main.ipynb")
    if extract_main(example["notebook"]) != extract_main(alternate["notebook"]):
        raise ValueError("Example notebooks disagree on the main challenge")
    records.append({
        "challenge_id": "quantum_error_correction",
        "problem_id": "quantum_error_correction_main",
        "split": "example",
        **extract_main(example["notebook"]),
        **example,
        "alternate_sources": [alternate],
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

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path = OUTPUT_DIR / "original_challenges.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Aggregated {len(records)} distinct challenges from {len(represented)} notebooks")
    print(jsonl_path)


if __name__ == "__main__":
    main()
