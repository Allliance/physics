"""CritPt's pre-audit judge contract over the shared evaluation transports."""

import json
from pathlib import Path

from eval import backends
from eval.storage import file_hash


PROMPTS = Path(__file__).parent / "prompts"
CONTRACT_FILES = ("critpt_judge.txt", "critpt_judge_system.txt", "critpt_judge_schema.json")


def provenance():
    return {
        "adapter_sha256": file_hash(Path(__file__)),
        "prompts_sha256": {name: file_hash(PROMPTS / name) for name in CONTRACT_FILES},
    }


def make_judge(args):
    prompt = (PROMPTS / CONTRACT_FILES[0]).read_text().strip()
    system = (PROMPTS / CONTRACT_FILES[1]).read_text().strip()
    schema = json.loads((PROMPTS / CONTRACT_FILES[2]).read_text())

    def render(question, prediction):
        payload = {
            "problem": question["question"],
            "ground_truth": question["reference_answer"],
            "model_solution": prediction["response"],
        }
        return prompt + "\n" + json.dumps(payload, ensure_ascii=False)

    return backends.make_judge(args, judge_prompt=render, system_prompt=system, schema=schema)
