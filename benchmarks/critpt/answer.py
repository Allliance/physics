#!/usr/bin/env python3
"""Compare the executable final answers from two CritPt result directories."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


FENCE = re.compile(r"^```(?:python)?\s*\n(?P<code>.*)\n```\s*$", re.DOTALL)


def load_code(path: Path) -> str:
    code = json.loads(path.read_text())["generated_code"].strip()
    match = FENCE.match(code)
    return match.group("code") if match else code


def normalized_dump(code: str) -> str:
    return ast.dump(ast.parse(code), annotate_fields=True, include_attributes=False)


def answer_signature(code: str) -> str:
    tree = ast.parse(code)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if not functions or functions[0].name != "answer":
        raise ValueError("top-level answer() function not found")
    return ast.unparse(functions[0].args)


def noarg_value(code: str):
    if answer_signature(code):
        return None
    namespace: dict[str, object] = {}
    exec(compile(code, "answer.py", "exec"), namespace)
    return namespace["answer"]()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    rows = []
    for number in range(1, 71):
        name = f"Challenge_{number}_main.json"
        left_code = load_code(args.left / name)
        right_code = load_code(args.right / name)
        left_sig = answer_signature(left_code)
        right_sig = answer_signature(right_code)
        left_value = noarg_value(left_code)
        right_value = noarg_value(right_code)
        rows.append(
            {
                "challenge": number,
                "signature": left_sig,
                "same_signature": left_sig == right_sig,
                "same_ast": normalized_dump(left_code) == normalized_dump(right_code),
                "left_noarg_value": repr(left_value) if left_value is not None else None,
                "right_noarg_value": repr(right_value) if right_value is not None else None,
                "same_noarg_value": (
                    left_value == right_value if left_value is not None and right_value is not None else None
                ),
                "left_code": left_code,
                "right_code": right_code,
            }
        )

    rendered = json.dumps(rows, indent=2, default=str)
    if args.output:
        args.output.write_text(rendered + "\n")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
