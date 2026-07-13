from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .llm import make_llm
from .pipeline import GenerationConfig, RunConfig, run

DATASETS = ("FrontierPhysics", "Physics")
SPLITS = ("train", "validation", "test")
DATA_ROOT = Path(__file__).resolve().parent.parent / "final_datasets"


def resolve_dataset_path(dataset: str, split: str) -> Path:
    if dataset == "FrontierPhysics" and split == "validation":
        raise ValueError("FrontierPhysics has no validation split")
    path = DATA_ROOT / dataset / f"{split}.parquet"
    if not path.is_file():
        raise ValueError(f"dataset split does not exist: {path}")
    return path


def endpoint_args(parser: argparse.ArgumentParser, prefix: str) -> None:
    parser.add_argument(f"--{prefix}-backend", choices=["codex", "openai"], default="codex")
    parser.add_argument(f"--{prefix}-model", default="gpt-5.5")
    parser.add_argument(f"--{prefix}-url")
    parser.add_argument(f"--{prefix}-api-key", default=os.getenv("OPENAI_API_KEY", "EMPTY"))
    parser.add_argument(f"--{prefix}-reasoning-effort",
                        choices=["minimal", "low", "medium", "high", "xhigh"],
                        default="high" if prefix == "judge" else None)
    parser.add_argument(f"--{prefix}-max-tokens", type=int)
    parser.add_argument(f"--{prefix}-temperature", type=float, default=0.0)
    parser.add_argument(f"--{prefix}-top-p", type=float)
    parser.add_argument(f"--{prefix}-top-k", type=int)
    parser.add_argument(f"--{prefix}-min-p", type=float)
    parser.add_argument(f"--{prefix}-presence-penalty", type=float)
    parser.add_argument(f"--{prefix}-repetition-penalty", type=float)
    parser.add_argument(f"--{prefix}-extra-body", type=json.loads)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and LLM-judge one physics dataset split.")
    parser.add_argument("dataset", choices=DATASETS)
    parser.add_argument("split", choices=SPLITS)
    parser.add_argument("--mode", choices=["merged", "separated"], default="separated")
    parser.add_argument("--output-root", type=Path, default=Path("eval/artifacts"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--max-workers", type=int, default=32)
    parser.add_argument("--overwrite", action="store_true")
    endpoint_args(parser, "generator")
    endpoint_args(parser, "judge")
    args = parser.parse_args()
    try:
        dataset_path = resolve_dataset_path(args.dataset, args.split)
    except ValueError as exc:
        parser.error(str(exc))
    generator = make_llm(backend=args.generator_backend, model=args.generator_model,
                         url=args.generator_url, api_key=args.generator_api_key,
                         timeout=args.timeout, reasoning_effort=args.generator_reasoning_effort,
                         max_tokens=args.generator_max_tokens,
                         temperature=args.generator_temperature, top_p=args.generator_top_p,
                         top_k=args.generator_top_k, min_p=args.generator_min_p,
                         presence_penalty=args.generator_presence_penalty,
                         repetition_penalty=args.generator_repetition_penalty,
                         extra_body=args.generator_extra_body)
    judge = make_llm(backend=args.judge_backend, model=args.judge_model,
                     url=args.judge_url, api_key=args.judge_api_key,
                     timeout=args.timeout, reasoning_effort=args.judge_reasoning_effort,
                     max_tokens=args.judge_max_tokens)
    judge_name = args.judge_model
    generation = GenerationConfig(model=args.generator_model,
                       reasoning_effort=args.generator_reasoning_effort,
                       max_tokens=args.generator_max_tokens,
                       temperature=args.generator_temperature,
                       top_p=args.generator_top_p,
                       top_k=args.generator_top_k,
                       min_p=args.generator_min_p,
                       presence_penalty=args.generator_presence_penalty,
                       repetition_penalty=args.generator_repetition_penalty,
                       extra_body=args.generator_extra_body)
    config = RunConfig(mode=args.mode, generation=generation,
                       judge_name=judge_name, limit=args.limit,
                       overwrite=args.overwrite, max_workers=args.max_workers,
                       judge_reasoning_effort=args.judge_reasoning_effort,
                       judge_max_tokens=args.judge_max_tokens)
    print(run(dataset_path, args.output_root, config, generator, judge))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
