"""Exercise both native benchmark graders on known-correct answers."""

from __future__ import annotations

import copy
import json

from rlvr.prepare_data import PRISM_ROOT, _load_function
from rlvr.reward import PRISM_SOURCE, UGPHYSICS_SOURCE, compute_score


def main() -> None:
    filter_and_convert = _load_function(PRISM_ROOT / "utils" / "data_utils.py", "filter_and_convert")
    raw = json.loads((PRISM_ROOT / "datasets" / "01_cleaned_dag.json").read_text())[0]
    problem = filter_and_convert(copy.deepcopy(raw))
    assert problem is not None
    prism_solution = "\n".join(part["solution"] for part in problem["subquestions"])
    prism_truth = json.dumps({"grading_standard": problem["grading_standard"]})
    prism_result = compute_score(PRISM_SOURCE, prism_solution, prism_truth, timeout_seconds=60)
    if prism_result.get("acc") != 1.0:
        raise AssertionError(f"PRISM native reward smoke failed: {prism_result}")

    ug_solution = r"So the final answer is \boxed{2}."
    ug_truth = json.dumps({"answers": r"\boxed{2}"})
    ug_result = compute_score(UGPHYSICS_SOURCE, ug_solution, ug_truth, timeout_seconds=60)
    if ug_result.get("acc") != 1.0:
        raise AssertionError(f"UGPhysics native reward smoke failed: {ug_result}")

    print(json.dumps({"prism": prism_result, "ugphysics": ug_result}, indent=2))


if __name__ == "__main__":
    main()
