"""Use the untouched upstream HLE judge contract with canonical transports.

Read only the prompt and response declaration. Importing the upstream CLI would
construct an OpenAI client and load dataset libraries before any work is needed.
"""

import ast
import hashlib
from pathlib import Path
import subprocess
import warnings

from eval import backends
from eval.datasets import ROOT
from eval.storage import file_hash, fingerprint


UPSTREAM_ROOT = ROOT / "benchmarks/hle"
JUDGE_SOURCE = UPSTREAM_ROOT / "hle_eval/run_judge_results.py"


def _field_schema(annotation: ast.expr) -> dict:
    if isinstance(annotation, ast.Name) and annotation.id in {"str", "int"}:
        return {"type": {"str": "string", "int": "integer"}[annotation.id]}
    if (isinstance(annotation, ast.Subscript) and
            isinstance(annotation.value, ast.Name) and annotation.value.id == "Literal"):
        nodes = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
        values = [ast.literal_eval(node) for node in nodes]
        if values == [True] and type(values[0]) is bool:
            return {"type": "boolean", "const": True}
        if values and all(isinstance(value, str) for value in values):
            return {"type": "string", "enum": values}
    raise ValueError("Upstream HLE response schema changed; review the judge adapter")


def load_contract(path: Path | None = None) -> tuple[str, dict]:
    source = path or JUDGE_SOURCE
    if not source.is_file():
        raise FileNotFoundError(
            "HLE upstream checkout is missing. Run: git submodule update --init benchmarks/hle"
        )
    with warnings.catch_warnings():
        # Upstream's literal contains \% escapes. Parsing it for data should
        # not emit Python's invalid-escape warning on every judged question.
        warnings.filterwarnings("ignore", message="invalid escape sequence", category=DeprecationWarning)
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    prompts = [node.value for node in tree.body if isinstance(node, ast.Assign)
               and any(isinstance(target, ast.Name) and target.id == "JUDGE_PROMPT"
                       for target in node.targets)]
    declarations = [node for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == "ExtractedAnswer"]
    if len(prompts) != 1 or len(declarations) != 1:
        raise ValueError("Upstream HLE judge contract changed; review the judge adapter")
    prompt = ast.literal_eval(prompts[0])
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Upstream HLE judge prompt must be a nonempty string")
    properties = {
        node.target.id: _field_schema(node.annotation)
        for node in declarations[0].body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    if set(properties) != set(backends.SCHEMA["required"]):
        raise ValueError("Upstream HLE response fields changed; review the judge adapter")
    return prompt, {"type": "object", "properties": properties,
                    "required": list(properties), "additionalProperties": False}


def provenance() -> dict:
    prompt, schema = load_contract()
    revision = subprocess.check_output(
        ["git", "-C", str(UPSTREAM_ROOT), "rev-parse", "HEAD"], text=True,
    ).strip()
    return {
        "repository": "https://github.com/centerforaisafety/hle.git",
        "commit": revision,
        "source": str(JUDGE_SOURCE.relative_to(ROOT)),
        "source_sha256": file_hash(JUDGE_SOURCE),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "schema_sha256": fingerprint(schema),
        "adapter_sha256": file_hash(Path(__file__)),
    }


def make_judge(args):
    prompt, schema = load_contract()
    judge = backends.make_judge(args, judge_prompt=prompt, schema=schema)

    def evaluate(question, prediction, answer):
        result = judge({**question, "reference_answer": answer}, prediction)
        content = result["judgment"]
        return {"correct_answer": answer, "model_answer": content["extracted_final_answer"],
                "reasoning": content["reasoning"], "correct": content["correct"],
                "confidence": content["confidence"], "actual_model": result["actual_model"]}

    return evaluate
