#!/usr/bin/env python3
"""Run Qwen through vLLM on audited PRISM or UGPhysics rows.

Rows labelled ``benchmark_failure`` in ``audit/all-responses`` are excluded
before generation.  Each benchmark is scored with its released deterministic
grader, and all artifacts are resumable JSONL files.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import multiprocessing
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_ROOT = REPO_ROOT / "audit" / "all-responses"
SYSTEM_PROMPT = """Solve the supplied physics problem yourself without tools, files, web search, or external context.
Think carefully in the model's private reasoning section. In the final response, give a rigorous,
self-contained solution and obey the problem's requested answer format. Put every requested final
answer in \\boxed{} so the benchmark's released deterministic grader can extract it."""


@dataclass(frozen=True)
class Config:
    benchmark: str
    model: str
    base_url: str
    max_workers: int
    timeout: float
    max_tokens: int
    temperature: float
    top_p: float
    top_k: int
    min_p: float
    presence_penalty: float
    repetition_penalty: float
    thinking_mode: str
    thinking_token_budget: int | None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def append_jsonl(path: Path, item: dict[str, Any], lock: threading.Lock) -> None:
    with lock, path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        handle.flush()


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    os.replace(temporary, path)


def endpoint(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    return (f"{base_url}/chat/completions" if base_url.endswith("/v1")
            else f"{base_url}/v1/chat/completions")


def audit_rows(benchmark: str) -> tuple[list[dict[str, Any]], set[str]]:
    rows = read_jsonl(AUDIT_ROOT / benchmark / "responses.jsonl")
    excluded = {
        str(row["problem_id"])
        for row in rows
        if row.get("AI_audit", {}).get("verdict") == "benchmark_failure"
    }
    kept = [row for row in rows if str(row["problem_id"]) not in excluded]
    if len({str(row["problem_id"]) for row in rows}) != len(rows):
        raise ValueError(f"duplicate {benchmark} problem IDs in audit source")
    return kept, excluded


def load_ugphysics() -> tuple[dict[str, dict[str, Any]], Any, Any]:
    root = REPO_ROOT / "benchmarks" / "ugphysics"
    sample = read_jsonl(root / "artifacts" / "gpt-5.6-sol-high-random-1000" / "sample.jsonl")
    by_id = {str(row["_eval_id"]): row for row in sample}
    codes = root / "codes"
    sys.path.insert(0, str(codes))
    from judge import Judger  # type: ignore
    from utils import make_prompt  # type: ignore
    return by_id, Judger(strict_extract=True), make_prompt


def load_prism() -> tuple[dict[str, dict[str, Any]], Any, Any]:
    root = REPO_ROOT / "benchmarks" / "prism"
    sys.path.insert(0, str(root))
    from utils.data_utils import filter_and_convert  # type: ignore
    from utils.grade_utils import grade_problem_dag  # type: ignore
    from utils.prompt_utils import get_eval_prompt  # type: ignore
    problems: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "datasets").glob("*_cleaned_dag.json")):
        for raw in json.loads(path.read_text(encoding="utf-8")):
            if raw.get("images"):
                continue
            problem = filter_and_convert(raw)
            if not problem:
                continue
            item_id = f"{path.stem}:{problem['id']}"
            problem["_eval_id"] = item_id
            problems[item_id] = problem
    return problems, grade_problem_dag, get_eval_prompt


def prepare_benchmark(benchmark: str, kept: list[dict[str, Any]]) -> tuple[dict, Any, Any]:
    if benchmark == "ugphysics":
        rows, grader, prompt_builder = load_ugphysics()
    elif benchmark == "prism":
        rows, grader, prompt_builder = load_prism()
    else:
        raise ValueError(benchmark)
    audit_ids = {str(row["problem_id"]) for row in kept}
    missing = sorted(audit_ids - set(rows))
    if missing:
        raise ValueError(f"{len(missing)} audited IDs absent from native data: {missing[:5]}")
    return {item_id: rows[item_id] for item_id in audit_ids}, grader, prompt_builder


def build_prompt(benchmark: str, row: dict[str, Any], prompt_builder: Any) -> str:
    if benchmark == "ugphysics":
        return f"{prompt_builder(row)}\n\n{row['problem']}"
    return prompt_builder(row)


def request_generation(item_id: str, prompt: str, config: Config,
                       attempts: int = 5) -> dict[str, Any]:
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
        "top_p": config.top_p,
        "top_k": config.top_k,
        "min_p": config.min_p,
        "presence_penalty": config.presence_penalty,
        "repetition_penalty": config.repetition_penalty,
    }
    if config.thinking_mode != "auto":
        payload["chat_template_kwargs"] = {
            "enable_thinking": config.thinking_mode == "on",
        }
    if config.thinking_mode == "on" and config.thinking_token_budget is not None:
        payload["thinking_token_budget"] = config.thinking_token_budget
    body = json.dumps(payload).encode()
    last_error = ""
    for request_attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            endpoint(config.base_url), data=body, method="POST",
            headers={"Authorization": "Bearer EMPTY", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=config.timeout) as response:
                raw = json.load(response)
            choice = raw["choices"][0]
            message = choice["message"]
            content = (message.get("content") or "").strip()
            return {
                "id": item_id,
                "response": content,
                "reasoning": message.get("reasoning") or message.get("reasoning_content"),
                "finish_reason": choice.get("finish_reason"),
                "usage": raw.get("usage") or {},
                "request_attempts": request_attempt,
                "created_at": utc_now(),
            }
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}: {exc.read().decode(errors='replace')}"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError,
                KeyError, IndexError, ValueError) as exc:
            last_error = repr(exc)
        if request_attempt < attempts:
            time.sleep(min(2 ** (request_attempt - 1), 8))
    raise RuntimeError(f"row {item_id} failed: {last_error}")


def prism_final_result(problem: dict[str, Any], matches: list[dict]) -> dict[str, Any]:
    standard = problem["grading_standard"]
    if isinstance(standard, str):
        standard = json.loads(standard.replace("\\", "\\\\").replace(r"\n", r"\n"))
    finals = [index for index, node in enumerate(standard)
              if node.get("is_final_answer", False)]
    if not finals and standard:
        finals = [len(standard) - 1]
    matched = {int(match["index_std"]) for match in matches}
    matched_finals = [index for index in finals if index in matched]
    return {
        "correct": bool(finals) and len(matched_finals) == len(finals),
        "final_answer_score": len(matched_finals) / len(finals) if finals else 0.0,
        "final_formula_count": len(finals),
        "matched_final_formula_count": len(matched_finals),
    }


@contextmanager
def alarm_timeout(seconds: float):
    def handler(_signum: int, _frame: Any) -> None:
        raise TimeoutError(f"native grading exceeded {seconds:g} seconds")
    previous = signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def grade_ugphysics(row: dict[str, Any], response: str, grader: Any) -> dict[str, Any]:
    correct = bool(grader.auto_judge(response, row["answers"], precision=1e-2))
    return {
        "correct": correct,
        "reference_answer": row["answers"],
        "extracted_answer": grader.extract_ans(response),
    }


def ug_worker(connection: Any, row: dict[str, Any], response: str) -> None:
    try:
        codes = REPO_ROOT / "benchmarks" / "ugphysics" / "codes"
        sys.path.insert(0, str(codes))
        from judge import Judger  # type: ignore
        connection.send(("ok", grade_ugphysics(row, response, Judger(strict_extract=True))))
    except BaseException as exc:
        connection.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        connection.close()


def score_one(benchmark: str, item_id: str, row: dict[str, Any], response: str,
              grader: Any, timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    error = None
    try:
        if benchmark == "prism":
            with alarm_timeout(timeout):
                process_score, matches = grader(row, response)
            result = {"process_score": float(process_score), "matches": matches}
            result.update(prism_final_result(row, matches))
        else:
            context = multiprocessing.get_context("fork")
            receiver, sender = context.Pipe(duplex=False)
            process = context.Process(target=ug_worker, args=(sender, row, response), daemon=True)
            process.start()
            sender.close()
            if receiver.poll(timeout):
                status, payload = receiver.recv()
            else:
                status, payload = "error", f"native grading exceeded {timeout:g} seconds"
            if process.is_alive():
                process.terminate()
            process.join()
            receiver.close()
            if status != "ok":
                raise RuntimeError(payload)
            result = payload
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        result = {"correct": False}
        if benchmark == "prism":
            result.update({"process_score": 0.0, "matches": [],
                           "final_answer_score": 0.0, "final_formula_count": 0,
                           "matched_final_formula_count": 0})
    result.update({
        "id": item_id,
        "grading_error": error,
        "grading_seconds": time.monotonic() - started,
        "created_at": utc_now(),
    })
    return result


def summary(benchmark: str, all_count: int, excluded: set[str], rows: dict[str, dict],
            generations: dict[str, dict], scores: dict[str, dict], config: Config) -> dict[str, Any]:
    correct = sum(bool(item["correct"]) for item in scores.values())
    usage_fields = ("prompt_tokens", "completion_tokens", "total_tokens")
    usage = {field: sum(int(item.get("usage", {}).get(field) or 0)
                        for item in generations.values()) for field in usage_fields}
    result = {
        "benchmark": benchmark,
        "config": asdict(config),
        "audit_source_rows": all_count,
        "benchmark_failure_excluded": len(excluded),
        "benchmark_failure_ids": sorted(excluded),
        "evaluated_rows": len(rows),
        "completed_generations": len(generations),
        "completed_scores": len(scores),
        "rule_based_correct": correct,
        "rule_based_accuracy": correct / len(rows) if rows else None,
        "scoring": ("PRISM released DAG formula grader; correct iff all final-answer nodes match"
                    if benchmark == "prism" else
                    "UGPhysics released deterministic auto_judge, precision=1e-2"),
        "mean_process_score": (sum(item.get("process_score", 0.0) for item in scores.values())
                               / len(scores) if benchmark == "prism" and scores else None),
        "grading_error_count": sum(bool(item.get("grading_error")) for item in scores.values()),
        "length_capped_count": sum(item.get("finish_reason") == "length"
                                   for item in generations.values()),
        "usage": usage,
        "unsolved_ids": sorted(item_id for item_id in rows
                               if not scores.get(item_id, {}).get("correct")),
        "updated_at": utc_now(),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark", choices=("prism", "ugphysics"))
    parser.add_argument("--base-url", default="http://mi355-gpu-38:8000/v1")
    parser.add_argument("--model", default="Qwen/Qwen3.5-9B")
    parser.add_argument("--max-workers", type=int, default=256)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--grade-timeout", type=float, default=180)
    parser.add_argument("--max-tokens", type=int, default=28672)
    parser.add_argument("--temperature", type=float, default=0.4)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--min-p", type=float, default=0.0)
    parser.add_argument("--presence-penalty", type=float, default=0.0)
    parser.add_argument("--repetition-penalty", type=float, default=1.0)
    parser.add_argument(
        "--thinking-mode",
        choices=("auto", "on", "off"),
        default="on",
        help=("Control the chat-template thinking switch. 'auto' omits the switch for "
              "fixed-mode checkpoints such as Qwen3-4B-Instruct/Thinking-2507."),
    )
    parser.add_argument("--thinking-token-budget", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--generation-only", action="store_true")
    parser.add_argument("--score-only", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if (args.max_workers < 1 or args.max_tokens < 1 or
            (args.thinking_token_budget is not None and args.thinking_token_budget < 1)):
        parser.error("worker and token counts must be positive")
    config = Config(
        benchmark=args.benchmark, model=args.model, base_url=args.base_url,
        max_workers=args.max_workers, timeout=args.timeout, max_tokens=args.max_tokens,
        temperature=args.temperature, top_p=args.top_p, top_k=args.top_k,
        min_p=args.min_p, presence_penalty=args.presence_penalty,
        repetition_penalty=args.repetition_penalty,
        thinking_mode=args.thinking_mode,
        thinking_token_budget=args.thinking_token_budget,
    )
    kept, excluded = audit_rows(args.benchmark)
    all_count = len(kept) + len(excluded)
    if args.limit is not None:
        kept = kept[:args.limit]
    rows, grader, prompt_builder = prepare_benchmark(args.benchmark, kept)
    ordered_ids = [str(item["problem_id"]) for item in kept]
    output = args.output_dir or (
        REPO_ROOT / "model_evals" / "qwen" / "runs" / f"qwen35-9b-{args.benchmark}-filtered"
    )
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(output / "manifest.json", {
        "config": asdict(config), "audit_source_rows": all_count,
        "excluded_benchmark_failure_count": len(excluded),
        "excluded_benchmark_failure_ids": sorted(excluded),
        "evaluated_ids": ordered_ids,
    })
    generation_path = output / "generations.jsonl"
    failure_path = output / "failures.jsonl"
    score_path = output / "scores.jsonl"
    generations = {str(item["id"]): item for item in read_jsonl(generation_path)}
    lock = threading.Lock()
    missing = ([] if args.score_only else
               [item_id for item_id in ordered_ids if item_id not in generations])
    print(f"{args.benchmark}: launching {len(missing)} missing generations ",
          f"with max_workers={config.max_workers}", flush=True)
    failures = []
    with ThreadPoolExecutor(max_workers=config.max_workers) as pool:
        futures = {
            pool.submit(request_generation, item_id,
                        build_prompt(args.benchmark, rows[item_id], prompt_builder), config): item_id
            for item_id in missing
        }
        for completed, future in enumerate(as_completed(futures), 1):
            item_id = futures[future]
            try:
                item = future.result()
                generations[item_id] = item
                append_jsonl(generation_path, item, lock)
            except Exception as exc:
                failure = {"id": item_id, "error": repr(exc), "created_at": utc_now()}
                failures.append(failure)
                append_jsonl(failure_path, failure, lock)
            if completed % 25 == 0 or completed == len(futures):
                print(f"generated {completed}/{len(futures)}; failures={len(failures)}", flush=True)
    if failures:
        raise RuntimeError(f"{len(failures)} generation failures; rerun to resume")
    if args.generation_only:
        return 0

    scores = {str(item["id"]): item for item in read_jsonl(score_path)}
    missing_scores = [item_id for item_id in ordered_ids
                      if item_id in generations and item_id not in scores]
    print(f"{args.benchmark}: scoring {len(missing_scores)} missing generations", flush=True)
    for completed, item_id in enumerate(missing_scores, 1):
        item = score_one(args.benchmark, item_id, rows[item_id],
                         generations[item_id]["response"], grader, args.grade_timeout)
        scores[item_id] = item
        append_jsonl(score_path, item, lock)
        if completed % 25 == 0 or completed == len(missing_scores):
            print(f"scored {completed}/{len(missing_scores)}", flush=True)
    result = summary(args.benchmark, all_count, excluded, rows, generations, scores, config)
    atomic_json(output / "summary.json", result)
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
