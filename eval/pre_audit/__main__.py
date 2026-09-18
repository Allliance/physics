"""CLI for exporting pre-audit benchmark inputs and scoring supplied responses."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .pipeline import DATASETS, JudgeSettings, load_benchmark
from .runner import add_arguments as add_run_arguments, run as run_evaluation


def _write_jsonl(path: Path | None, rows) -> None:
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    if path is None:
        sys.stdout.write(text)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _read_responses(path: Path) -> dict[str, str]:
    if path.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        result = {}
        for row in rows:
            if not isinstance(row, dict) or "id" not in row:
                raise ValueError("Every response JSONL row needs id and response")
            response = row.get("response", row.get("completion"))
            if not isinstance(response, str) or not response.strip():
                raise ValueError(f"Response for {row.get('id')} must be nonempty text")
            qid = str(row["id"])
            if qid in result:
                raise ValueError(f"Duplicate response ID: {qid}")
            result[qid] = response
        return result
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not all(isinstance(v, str) and v.strip() for v in value.values()):
        raise ValueError("Response JSON must map IDs to nonempty response strings")
    return {str(key): response for key, response in value.items()}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("datasets", help="Describe the supported pre-audit datasets")
    export = sub.add_parser("export", help="Export normalized questions, native prompts, and references")
    export.add_argument("--dataset", required=True)
    export.add_argument("--output", type=Path)
    export.add_argument("--without-references", action="store_true")
    export.add_argument("--limit", type=int)
    evaluate = sub.add_parser("evaluate", help="Evaluate response JSON/JSONL with the dataset evaluator")
    evaluate.add_argument("--dataset", required=True)
    evaluate.add_argument("--responses", type=Path, required=True)
    evaluate.add_argument("--output", type=Path)
    evaluate.add_argument("--require-all", action="store_true")
    evaluate.add_argument("--timeout", type=float, default=180.0, help="Native scorer timeout per response")
    evaluate.add_argument("--judge-model", choices=["gpt-5.6-sol", "claude-fable-5"], default="gpt-5.6-sol")
    evaluate.add_argument("--judge-reasoning-effort", choices=["low", "medium", "high", "xhigh"], default="high")
    evaluate.add_argument("--judge-timeout", type=float, default=1800.0)
    evaluate.add_argument("--judge-max-output-tokens", type=int, default=8192)
    evaluate.add_argument("--fable-model")
    evaluate.add_argument("--codex-bin")
    evaluate.add_argument("--no-ugphysics-auxiliary", action="store_true",
                          help="Use only UGPhysics's strict rule grader, without its released auxiliary judge")
    run = sub.add_parser("run", help="Generate and score fresh model attempts")
    add_run_arguments(run)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "run":
            return run_evaluation(args)
        if args.command == "datasets":
            rows = []
            for name in DATASETS:
                pipeline = load_benchmark(name)
                rows.append({**pipeline.metadata, "ids": [problem.id for problem in pipeline.problems]})
            print(json.dumps(rows, indent=2, ensure_ascii=False))
            return 0
        if getattr(args, "limit", None) is not None and args.limit <= 0:
            raise ValueError("--limit must be positive")
        if args.command == "export":
            pipeline = load_benchmark(args.dataset)
            problems = pipeline.problems if args.limit is None else pipeline.problems[:args.limit]
            _write_jsonl(args.output, (problem.as_dict(include_reference=not args.without_references)
                                       for problem in problems))
            return 0
        if min(args.timeout, args.judge_timeout, args.judge_max_output_tokens) <= 0:
            raise ValueError("Timeouts and token limits must be positive")
        kwargs = {}
        if args.codex_bin:
            kwargs["codex_bin"] = args.codex_bin
        settings = JudgeSettings(model=args.judge_model,
                                 reasoning_effort=args.judge_reasoning_effort,
                                 timeout=args.judge_timeout,
                                 max_output_tokens=args.judge_max_output_tokens,
                                 fable_model=args.fable_model, **kwargs)
        pipeline = load_benchmark(args.dataset, judge_settings=settings,
                                  use_ugphysics_auxiliary=not args.no_ugphysics_auxiliary)
        responses = _read_responses(args.responses)
        results = pipeline.evaluate_many(responses, timeout=args.timeout, require_all=args.require_all)
        _write_jsonl(args.output, (result.as_dict() for result in results))
        return 0
    except (ValueError, KeyError, FileNotFoundError, ImportError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
